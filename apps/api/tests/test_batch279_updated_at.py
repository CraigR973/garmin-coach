"""Batch 279: ``updated_at`` means one thing on every table that has it.

Before this batch the column advanced on five of the eighteen tables — four
whose writers stamped it by hand, and ``profiles``, whose migration-001 trigger
does — and on the other thirteen it was an insert time that looked like a write
time. ``models.base.updated_at_column`` now defines it once: the application's
clock at the row's last write, stamped by SQLAlchemy into every insert and
every UPDATE it emits, with an explicit value still winning. It is not
backfilled, and no DDL changes (``onupdate`` lives in the UPDATE statement, not
in the schema).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Integer, String, create_engine, event, inspect, select, update
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

import src.models  # noqa: F401 - registers every model on the metadata
from src.models.base import Base, UpdatedAtMixin

#: Every mapped class with an ``updated_at`` column — the eighteen tables that
#: have one in production (measured 2026-09-24). A model that joins the set has
#: to be named here, which is the point: it cannot join silently.
CLASSES_WITH_UPDATED_AT = {
    "Activity",
    "BriefGenerationStatus",
    "ConversationLearningProposal",
    "DailyMetric",
    "Experiment",
    "GarminWorkoutDelivery",
    "GenerationRequest",
    "KnowledgeBase",
    "ManualEntry",
    "MetricBaseline",
    "NotificationPreferences",
    "PlanBlock",
    "PlannedWorkout",
    "PostActivityGenerationStatus",
    "Profile",
    "Sleep",
    "WeatherDaily",
    "WorkoutDeliveryProposal",
}


def test_every_class_with_updated_at_is_named_and_stamps_every_write() -> None:
    mapped = {
        mapper.class_.__name__: mapper.local_table.c.updated_at
        for mapper in Base.registry.mappers
        if "updated_at" in mapper.local_table.c
    }

    assert set(mapped) == CLASSES_WITH_UPDATED_AT
    for name, column in mapped.items():
        # Stamped on insert and on every UPDATE, by the application's clock —
        # a Python callable, never a SQL expression SQLAlchemy would have to
        # expire after the flush (279.2; see ``updated_at_column``).
        assert column.default is not None and column.default.is_callable, name
        assert column.onupdate is not None and column.onupdate.is_callable, name
        assert column.server_default is not None, name
    # NotificationPreferences declares it on a bare Base; every other class
    # takes it from the mixin. Both shapes now mean the same thing.
    assert {
        mapper.class_.__name__
        for mapper in Base.registry.mappers
        if issubclass(mapper.class_, UpdatedAtMixin)
    } == CLASSES_WITH_UPDATED_AT - {"NotificationPreferences"}


# --------------------------------------------------------------------------
# The mixin's behaviour, on a throwaway model and SQLite
# --------------------------------------------------------------------------


class _LocalBase(DeclarativeBase):
    pass


class _Stamped(_LocalBase, UpdatedAtMixin):
    __tablename__ = "stamped"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String)


def _session() -> tuple[Session, list[tuple[str, Any]]]:
    engine = create_engine("sqlite://")
    _LocalBase.metadata.create_all(engine)
    statements: list[tuple[str, Any]] = []
    event.listen(
        engine,
        "before_cursor_execute",
        lambda _c, _cur, sql, params, _ctx, _many: statements.append((sql, params)),
    )
    return Session(engine, expire_on_commit=False), statements


def _updates(statements: list[tuple[str, Any]]) -> list[tuple[str, Any]]:
    return [(sql, params) for sql, params in statements if sql.lstrip().startswith("UPDATE")]


def test_an_update_advances_it_and_a_read_does_not() -> None:
    """279.4: it advances on a real update, and a row read but not written keeps it."""
    session, statements = _session()
    with session:
        row = _Stamped(id=1, name="wake")
        session.add(row)
        session.flush()
        inserted = row.updated_at
        # The same flush as ``created_at``, on the same clock — not Postgres's
        # transaction-start ``now()``, which is why 224 of 224 manual entries
        # read seconds *earlier* than their own creation (2026-09-24).
        assert abs(inserted - row.created_at) < timedelta(seconds=1)

        statements.clear()
        session.execute(select(_Stamped)).scalars().one()
        session.flush()
        assert _updates(statements) == []
        assert row.updated_at == inserted

        row.name = "settled"
        session.flush()
        [(sql, _params)] = _updates(statements)
        assert "updated_at" in sql
        assert row.updated_at >= inserted
        # Stamped in Python, so the value stays loaded after the flush — reading
        # it cannot become an implicit query under the async session.
        assert "updated_at" not in inspect(row).unloaded


def test_an_explicit_value_still_wins_so_hand_set_writers_are_not_double_stamped() -> None:
    """279.4: the lease and generation-status writers set it themselves; theirs stands."""
    session, statements = _session()
    with session:
        row = _Stamped(id=1, name="generating")
        session.add(row)
        session.flush()
        statements.clear()

        chosen = datetime(2026, 9, 24, 6, 30, 0)
        row.name = "ready"
        row.updated_at = chosen
        session.flush()

        [(sql, _params)] = _updates(statements)
        assert sql.count("updated_at") == 1
        session.expire(row)
        assert row.updated_at == chosen


def test_a_bulk_update_statement_is_stamped_too() -> None:
    """``update(Model)`` — how plan and knowledge-base edits are written."""
    session, statements = _session()
    with session:
        session.add(_Stamped(id=1, name="plan"))
        session.flush()
        statements.clear()

        session.execute(update(_Stamped).where(_Stamped.id == 1).values(name="replanned"))

        [(sql, _params)] = _updates(statements)
        assert "updated_at" in sql


# --------------------------------------------------------------------------
# Postgres: a table where it never advanced now does
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_daily_metric_update_advances_updated_at_in_postgres(
    db_conn: AsyncConnection,
) -> None:
    """``daily_metrics`` was one of the thirteen: 495 of 552 rows read *earlier*
    than their own ``created_at``, and none had ever advanced (2026-09-24)."""
    from src.models.coaching import DailyMetric
    from src.models.profile import Profile, UserRole

    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()
    long_ago = datetime(2020, 1, 1)
    async with session_factory() as session:
        session.add(
            Profile(
                id=user_id,
                display_name="Batch 279 freshness",
                role=UserRole.admin,
                timezone="Europe/London",
                is_active=True,
            )
        )
        await session.flush()
        metric = DailyMetric(
            user_id=user_id,
            calendar_date=date(2026, 9, 24),
            phase="morning",
            readiness_score=41,
            updated_at=long_ago,
        )
        session.add(metric)
        await session.flush()

        reread = await session.scalar(select(DailyMetric).where(DailyMetric.user_id == user_id))
        assert reread is metric
        await session.flush()
        assert metric.updated_at == long_ago

        metric.readiness_score = 44
        await session.flush()
        assert metric.updated_at > long_ago

        stored = await session.scalar(
            select(DailyMetric.updated_at).where(DailyMetric.user_id == user_id)
        )
        assert stored == metric.updated_at
