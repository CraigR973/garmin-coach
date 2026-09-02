"""Batch 247.2 — a rolling window on 82% of the database.

The purge is irreversible: `activity_timeseries` is excluded from every backup by
design, so there is no undo. These tests exist to make the window, the dry-run
default and both readers provable *before* it is ever pointed at production.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.models.coaching import Activity, ActivityTimeSeries
from src.models.profile import Profile, UserRole
from src.services.activity_timeseries_retention import (
    RETENTION_DAYS,
    measure_expired,
    purge_expired_timeseries,
    retention_cutoff,
)

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)


def test_the_window_is_ninety_days() -> None:
    assert RETENTION_DAYS == 90
    assert retention_cutoff(NOW) == NOW.replace(tzinfo=None) - timedelta(days=90)


async def _seed(
    db_conn: AsyncConnection,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """One activity inside the window, one outside, four samples each."""
    user_id = uuid.uuid4()
    recent_id = uuid.uuid4()
    old_id = uuid.uuid4()
    naive_now = NOW.replace(tzinfo=None)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add(
            Profile(
                id=user_id,
                display_name="Retention",
                role=UserRole.admin,
                timezone="Europe/London",
                is_active=True,
            )
        )
        await session.flush()
        for activity_id, start in (
            (recent_id, naive_now - timedelta(days=10)),
            # Deliberately just outside, so the test pins the boundary rather
            # than a comfortable margin either side of it.
            (old_id, naive_now - timedelta(days=RETENTION_DAYS + 1)),
        ):
            session.add(
                Activity(
                    id=activity_id,
                    user_id=user_id,
                    garmin_activity_id=abs(hash(activity_id)) % 10_000_000,
                    activity_name="Ride",
                    activity_type="indoor_cycling",
                    start_utc=start,
                    duration_sec=3600,
                    raw_summary={},
                )
            )
            await session.flush()
            for index in range(4):
                session.add(
                    ActivityTimeSeries(
                        id=uuid.uuid4(),
                        activity_id=activity_id,
                        sample_index=index,
                        timestamp_utc=start + timedelta(seconds=index),
                        power_watts=200.0 + index,
                        raw_metrics={},
                    )
                )
        await session.commit()
    return user_id, recent_id, old_id


async def _sample_count(session: AsyncSession, activity_id: uuid.UUID) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(ActivityTimeSeries)
            .where(ActivityTimeSeries.activity_id == activity_id)
        )
        or 0
    )


@pytest.mark.asyncio
async def test_a_dry_run_measures_and_deletes_nothing(db_conn: AsyncConnection) -> None:
    """The shipped production behaviour until it is deliberately changed.

    A purge of a table excluded from every backup is a decision with a row count
    attached, not something a deploy performs on its own.
    """
    _, recent_id, old_id = await _seed(db_conn)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        result = await purge_expired_timeseries(session, now_utc=NOW, dry_run=True)

        assert result.dry_run is True
        assert result.deleted_rows == 0
        assert result.expired_rows == 4
        assert result.expired_activities == 1
        # Nothing moved.
        assert await _sample_count(session, old_id) == 4
        assert await _sample_count(session, recent_id) == 4


@pytest.mark.asyncio
async def test_a_purge_removes_the_old_activity_and_keeps_the_recent_one(
    db_conn: AsyncConnection,
) -> None:
    _, recent_id, old_id = await _seed(db_conn)

    async with AsyncSession(
        bind=db_conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
    ) as session:
        result = await purge_expired_timeseries(session, now_utc=NOW, dry_run=False)

        assert result.dry_run is False
        assert result.deleted_rows == 4
        assert await _sample_count(session, old_id) == 0
        # The whole point: the in-window activity is untouched, so both readers
        # still work on everything they are supposed to.
        assert await _sample_count(session, recent_id) == 4


@pytest.mark.asyncio
async def test_an_activity_is_never_split_across_the_boundary(
    db_conn: AsyncConnection,
) -> None:
    """The reason the window is keyed on the activity, not on the sample.

    A long activity can span the cutoff. Keying on `timestamp_utc` would delete
    its early samples and keep its late ones — a half-readable ride that produces
    a *wrong* post-workout read rather than an absent one. Keyed on the activity,
    it is all or nothing.
    """
    user_id = uuid.uuid4()
    activity_id = uuid.uuid4()
    naive_now = NOW.replace(tzinfo=None)
    cutoff = retention_cutoff(NOW)

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add(
            Profile(
                id=user_id,
                display_name="Spanning",
                role=UserRole.admin,
                timezone="Europe/London",
                is_active=True,
            )
        )
        await session.flush()
        session.add(
            Activity(
                id=activity_id,
                user_id=user_id,
                garmin_activity_id=9_100_001,
                activity_name="Long ride",
                activity_type="indoor_cycling",
                start_utc=cutoff - timedelta(hours=1),
                duration_sec=7200,
                raw_summary={},
            )
        )
        await session.flush()
        # Two samples before the cutoff, two after it.
        for index, offset in enumerate((-90, -30, 30, 90)):
            session.add(
                ActivityTimeSeries(
                    id=uuid.uuid4(),
                    activity_id=activity_id,
                    sample_index=index,
                    timestamp_utc=cutoff + timedelta(minutes=offset),
                    raw_metrics={},
                )
            )
        await session.commit()
        assert naive_now > cutoff

    async with AsyncSession(
        bind=db_conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
    ) as session:
        result = await purge_expired_timeseries(session, now_utc=NOW, dry_run=False)

        # All four go, including the two whose own timestamps are inside the
        # window — because the activity they belong to is outside it.
        assert result.deleted_rows == 4
        assert await _sample_count(session, activity_id) == 0


@pytest.mark.asyncio
async def test_measure_expired_agrees_with_what_a_purge_removes(
    db_conn: AsyncConnection,
) -> None:
    """The dry-run count must be the number the confirmation is given against."""
    await _seed(db_conn)

    async with AsyncSession(
        bind=db_conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
    ) as session:
        _, measured_rows, measured_activities = await measure_expired(session, now_utc=NOW)
        result = await purge_expired_timeseries(session, now_utc=NOW, dry_run=False)

    assert measured_rows == result.deleted_rows
    assert measured_activities == result.expired_activities
