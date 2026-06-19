"""Stats endpoints — per-player and league-wide."""

import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import CurrentPlayer
from src.database import get_db
from src.deps import shared_league_player_ids
from src.models.league_membership import LeagueMembership
from src.models.profile import Profile
from src.routers.leagues import LeagueMemberDep
from src.services.stats import PlayerStatsData, get_league_stats, get_player_stats

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/stats", tags=["stats"])
league_router = APIRouter(prefix="/api/v1/leagues", tags=["stats"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class PlayerStatsOut(BaseModel):
    player_id: str
    player_name: str
    total_predictions_settled: int
    accuracy_pct: float
    exact_rate_pct: float
    avg_pts_per_prediction: float
    total_points: int
    best_round: str | None
    best_round_points: int | None
    worst_round: str | None
    worst_round_points: int | None
    current_streak: int
    avg_prediction_timing_mins: float | None
    # U38 — Match / Knockout / Special decomposition + merit-cascade counts,
    # surfaced on the player profile.
    match_points: int = 0
    knockout_winner_points: int = 0
    special_points: int = 0
    exact_count: int = 0
    correct_result_count: int = 0
    correct_goals_count: int = 0
    specials_correct_count: int = 0
    ko_winner_correct_count: int = 0
    # Avatar (U23.1) — null when the player hasn't uploaded a photo
    avatar_url: str | None = None


def _to_out(data: PlayerStatsData, avatar_url: str | None = None) -> PlayerStatsOut:
    return PlayerStatsOut(
        player_id=data.player_id,
        player_name=data.player_name,
        total_predictions_settled=data.total_predictions_settled,
        accuracy_pct=data.accuracy_pct,
        exact_rate_pct=data.exact_rate_pct,
        avg_pts_per_prediction=data.avg_pts_per_prediction,
        total_points=data.total_points,
        best_round=data.best_round,
        best_round_points=data.best_round_points,
        worst_round=data.worst_round,
        worst_round_points=data.worst_round_points,
        current_streak=data.current_streak,
        avg_prediction_timing_mins=data.avg_prediction_timing_mins,
        match_points=data.match_points,
        knockout_winner_points=data.knockout_winner_points,
        special_points=data.special_points,
        exact_count=data.exact_count,
        correct_result_count=data.correct_result_count,
        correct_goals_count=data.correct_goals_count,
        specials_correct_count=data.specials_correct_count,
        ko_winner_correct_count=data.ko_winner_correct_count,
        avatar_url=avatar_url,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/stats/me
# ---------------------------------------------------------------------------


@router.get("/me", response_model=PlayerStatsOut)
async def get_my_stats(
    player: CurrentPlayer,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PlayerStatsOut:
    stats = await get_player_stats(player.id, player.display_name, db)
    return _to_out(stats, avatar_url=player.avatar_url)


# ---------------------------------------------------------------------------
# GET /api/v1/leagues/{slug}/stats
# ---------------------------------------------------------------------------


@league_router.get("/{slug}/stats", response_model=list[PlayerStatsOut])
async def get_league_stats_endpoint(
    ctx: LeagueMemberDep,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[PlayerStatsOut]:
    """Per-player stats for the active members of one league."""
    _player, league = ctx
    member_ids = (
        (
            await db.execute(
                select(LeagueMembership.player_id).where(
                    LeagueMembership.league_id == league.id,
                    LeagueMembership.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    stats_list = await get_league_stats(db, player_ids=list(member_ids))
    return [_to_out(s) for s in stats_list]


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# GET /api/v1/stats/{player_id}
# ---------------------------------------------------------------------------


@router.get("/{player_id}", response_model=PlayerStatsOut)
async def get_player_stats_by_id(
    player_id: uuid.UUID,
    requester: CurrentPlayer,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PlayerStatsOut:
    result = await db.execute(
        select(Profile).where(Profile.id == player_id, Profile.deleted_at.is_(None))
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found")
    shared = await shared_league_player_ids(requester.id, db)
    if player_id not in shared:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not share a league with this player",
        )
    stats = await get_player_stats(player_id, profile.display_name, db)
    return _to_out(stats, avatar_url=profile.avatar_url)
