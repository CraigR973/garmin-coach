"""Batch 341 (CR327-06): a chat turn with no offer stores SQL NULL, not JSON ``null``."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.models.coaching import BriefMessage
from src.models.profile import Profile, UserRole


@pytest.mark.asyncio
async def test_a_turn_without_an_offer_or_usage_stores_sql_null(db_conn: AsyncConnection) -> None:
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        player = Profile(
            id=uuid.uuid4(),
            display_name="Brief Message Nulls",
            role=UserRole.admin,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(player)
        await session.flush()
        session.add(
            BriefMessage(
                user_id=player.id,
                role="assistant",
                content="An answer that offers nothing.",
                proposed_interval_change=None,
                proposed_plan_change=None,
                generation_usage=None,
            )
        )
        await session.flush()

        stored = (
            await session.execute(
                text(
                    "select proposed_interval_change is null, proposed_plan_change is null, "
                    "generation_usage is null from coach.brief_messages where user_id = :user_id"
                ),
                {"user_id": player.id},
            )
        ).one()

    assert tuple(stored) == (True, True, True)
