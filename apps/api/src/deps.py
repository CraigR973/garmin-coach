"""Shared FastAPI dependencies."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.league_membership import LeagueMembership


async def shared_league_player_ids(
    requester_id: uuid.UUID, db: AsyncSession
) -> frozenset[uuid.UUID]:
    """IDs of all players who share ≥1 active league with requester (includes self).

    Always includes requester_id so a player can always read their own data.
    """
    requester_leagues_sq = (
        select(LeagueMembership.league_id)
        .where(
            LeagueMembership.player_id == requester_id,
            LeagueMembership.deleted_at.is_(None),
        )
        .scalar_subquery()
    )
    result = await db.execute(
        select(LeagueMembership.player_id)
        .where(
            LeagueMembership.league_id.in_(requester_leagues_sq),
            LeagueMembership.deleted_at.is_(None),
        )
        .distinct()
    )
    return frozenset(result.scalars().all()) | {requester_id}
