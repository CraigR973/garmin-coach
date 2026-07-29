from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from src.models.coaching import DailyMetric
from src.models.profile import Profile, UserRole
from src.services.body_metrics import resolve_effective_weight_kg


async def _seed_player(session: AsyncSession, user_id: uuid.UUID) -> None:
    session.add(
        Profile(
            id=user_id,
            display_name="Weight Test",
            role=UserRole.admin,
            timezone="Europe/London",
            is_active=True,
        )
    )
    await session.flush()


@pytest.mark.asyncio
async def test_resolve_effective_weight_kg_carries_most_recent_weigh_in_forward(
    db_conn: AsyncConnection,
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()

    async with session_factory() as session:
        await _seed_player(session, user_id)
        session.add(
            DailyMetric(
                user_id=user_id,
                calendar_date=date(2026, 7, 24),
                weight_kg=79.4,
                raw_payload={},
            )
        )
        session.add(
            DailyMetric(
                user_id=user_id,
                calendar_date=date(2026, 7, 27),
                weight_kg=None,
                raw_payload={},
            )
        )
        await session.commit()

        weight_kg, as_of = await resolve_effective_weight_kg(session, user_id, date(2026, 7, 29))

        assert weight_kg == 79.4
        assert as_of == date(2026, 7, 24)


@pytest.mark.asyncio
async def test_resolve_effective_weight_kg_ignores_weigh_in_outside_lookback_window(
    db_conn: AsyncConnection,
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()

    async with session_factory() as session:
        await _seed_player(session, user_id)
        session.add(
            DailyMetric(
                user_id=user_id,
                calendar_date=date(2026, 7, 1),
                weight_kg=80.0,
                raw_payload={},
            )
        )
        await session.commit()

        weight_kg, as_of = await resolve_effective_weight_kg(session, user_id, date(2026, 7, 29))

        assert weight_kg is None
        assert as_of is None


@pytest.mark.asyncio
async def test_resolve_effective_weight_kg_prefers_the_newest_row_in_window(
    db_conn: AsyncConnection,
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()

    async with session_factory() as session:
        await _seed_player(session, user_id)
        session.add(
            DailyMetric(
                user_id=user_id,
                calendar_date=date(2026, 7, 25),
                weight_kg=79.0,
                raw_payload={},
            )
        )
        session.add(
            DailyMetric(
                user_id=user_id,
                calendar_date=date(2026, 7, 28),
                weight_kg=78.5,
                raw_payload={},
            )
        )
        await session.commit()

        weight_kg, as_of = await resolve_effective_weight_kg(session, user_id, date(2026, 7, 29))

        assert weight_kg == 78.5
        assert as_of == date(2026, 7, 28)
