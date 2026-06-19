"""Head-to-head comparison endpoint."""

import uuid
from collections import defaultdict
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.models.league_membership import LeagueMembership
from src.models.match import Match
from src.models.prediction import KnockoutPrediction, Prediction
from src.models.profile import Profile
from src.models.team import Team
from src.routers.leagues import LeagueMemberDep

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

league_router = APIRouter(prefix="/api/v1/leagues", tags=["compare"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class PlayerRef(BaseModel):
    id: str
    name: str


class H2HSummary(BaseModel):
    player_a_wins: int
    player_b_wins: int
    draws: int


class H2HMatchEntry(BaseModel):
    match_id: str
    stage: str
    kickoff_utc: str
    home_team_name: str | None
    away_team_name: str | None
    home_team_flag: str | None
    away_team_flag: str | None
    actual_home: int | None
    actual_away: int | None
    player_a_predicted_home: int | None
    player_a_predicted_away: int | None
    player_a_points: int
    player_b_predicted_home: int | None
    player_b_predicted_away: int | None
    player_b_points: int
    winner: str  # "a", "b", or "draw"


class H2HResponse(BaseModel):
    player_a: PlayerRef
    player_b: PlayerRef
    summary: H2HSummary
    matches: list[H2HMatchEntry]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _winner(pts_a: int, pts_b: int) -> str:
    if pts_a > pts_b:
        return "a"
    if pts_b > pts_a:
        return "b"
    return "draw"


# ---------------------------------------------------------------------------
# Comparison core (shared)
# ---------------------------------------------------------------------------


async def _compute_h2h(
    player_a_id: uuid.UUID,
    player_b_id: uuid.UUID,
    db: AsyncSession,
) -> H2HResponse:
    """Match-by-match head-to-head comparison between two players.

    Settled predictions are included even if a player was later removed.
    Matches where neither player made a prediction are excluded.
    Missing predictions for one player are treated as 0 points.
    """
    # Validate both players exist (allow soft-deleted — they may have old preds)
    result_a = await db.execute(select(Profile).where(Profile.id == player_a_id))
    profile_a = result_a.scalar_one_or_none()
    if profile_a is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player A not found")

    result_b = await db.execute(select(Profile).where(Profile.id == player_b_id))
    profile_b = result_b.scalar_one_or_none()
    if profile_b is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player B not found")

    both_ids = [player_a_id, player_b_id]

    # Fetch settled group predictions for both players
    group_stmt = (
        select(Prediction, Match)
        .join(Match, Match.id == Prediction.match_id)
        .where(
            Prediction.player_id.in_(both_ids),
            Prediction.deleted_at.is_(None),
            Prediction.points_awarded.is_not(None),
            Match.deleted_at.is_(None),
        )
        .order_by(Match.kickoff_utc.asc())
    )
    group_rows = (await db.execute(group_stmt)).all()

    # Fetch settled knockout predictions for both players
    ko_stmt = (
        select(KnockoutPrediction, Match)
        .join(Match, Match.id == KnockoutPrediction.match_id)
        .where(
            KnockoutPrediction.player_id.in_(both_ids),
            KnockoutPrediction.points_awarded.is_not(None),
            Match.deleted_at.is_(None),
        )
        .order_by(Match.kickoff_utc.asc())
    )
    ko_rows = (await db.execute(ko_stmt)).all()

    # Group by match_id, keyed by player
    # match_id -> player_id -> (Prediction | KnockoutPrediction, Match)
    GroupRowData = tuple[int | None, int | None, int, Match]  # (pred_home, pred_away, pts, match)
    by_match: dict[uuid.UUID, dict[uuid.UUID, GroupRowData]] = defaultdict(dict)

    for pred, match in group_rows:
        by_match[match.id][pred.player_id] = (
            pred.predicted_home,
            pred.predicted_away,
            pred.points_awarded or 0,
            match,
        )

    for pred, match in ko_rows:
        by_match[match.id][pred.player_id] = (
            None,
            None,
            pred.points_awarded or 0,
            match,
        )

    # Collect team IDs for batch fetch
    team_ids: set[uuid.UUID] = set()
    for player_preds in by_match.values():
        for _, _, _, match in player_preds.values():
            if match.home_team_id is not None:
                team_ids.add(match.home_team_id)
            if match.away_team_id is not None:
                team_ids.add(match.away_team_id)

    teams: dict[str, Team] = {}
    if team_ids:
        team_result = await db.execute(select(Team).where(Team.id.in_(team_ids)))
        teams = {str(t.id): t for t in team_result.scalars().all()}

    # Build match entries, preserving kickoff order
    match_entries: list[H2HMatchEntry] = []
    wins_a = wins_b = draws = 0

    # Collect unique matches in kickoff order
    seen_match_ids: list[uuid.UUID] = []
    match_order: dict[uuid.UUID, Match] = {}
    for player_preds in by_match.values():
        for _, _, _, match in player_preds.values():
            if match.id not in match_order:
                match_order[match.id] = match

    for match_id in sorted(match_order, key=lambda mid: match_order[mid].kickoff_utc or ""):
        seen_match_ids.append(match_id)

    for match_id in seen_match_ids:
        player_preds = by_match[match_id]
        match = match_order[match_id]

        a_data = player_preds.get(player_a_id)
        b_data = player_preds.get(player_b_id)

        a_home = a_data[0] if a_data else None
        a_away = a_data[1] if a_data else None
        a_pts = a_data[2] if a_data else 0
        b_home = b_data[0] if b_data else None
        b_away = b_data[1] if b_data else None
        b_pts = b_data[2] if b_data else 0

        w = _winner(a_pts, b_pts)
        if w == "a":
            wins_a += 1
        elif w == "b":
            wins_b += 1
        else:
            draws += 1

        home_key = str(match.home_team_id) if match.home_team_id else ""
        away_key = str(match.away_team_id) if match.away_team_id else ""

        match_entries.append(
            H2HMatchEntry(
                match_id=str(match.id),
                stage=match.stage.value,
                kickoff_utc=match.kickoff_utc.isoformat() + "Z",
                home_team_name=teams[home_key].name
                if home_key in teams
                else match.home_team_placeholder,
                away_team_name=teams[away_key].name
                if away_key in teams
                else match.away_team_placeholder,
                home_team_flag=teams[home_key].flag_emoji if home_key in teams else None,
                away_team_flag=teams[away_key].flag_emoji if away_key in teams else None,
                actual_home=match.actual_home_score,
                actual_away=match.actual_away_score,
                player_a_predicted_home=a_home,
                player_a_predicted_away=a_away,
                player_a_points=a_pts,
                player_b_predicted_home=b_home,
                player_b_predicted_away=b_away,
                player_b_points=b_pts,
                winner=w,
            )
        )

    return H2HResponse(
        player_a=PlayerRef(id=str(player_a_id), name=profile_a.display_name),
        player_b=PlayerRef(id=str(player_b_id), name=profile_b.display_name),
        summary=H2HSummary(
            player_a_wins=wins_a,
            player_b_wins=wins_b,
            draws=draws,
        ),
        matches=match_entries,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/leagues/{slug}/compare/{player_a_id}/{player_b_id}
# ---------------------------------------------------------------------------


async def _require_league_members(
    league_id: uuid.UUID,
    player_ids: list[uuid.UUID],
    db: AsyncSession,
) -> None:
    """Reject the comparison unless every player is an active league member."""
    rows = (
        (
            await db.execute(
                select(LeagueMembership.player_id).where(
                    LeagueMembership.league_id == league_id,
                    LeagueMembership.player_id.in_(player_ids),
                    LeagueMembership.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    if set(rows) != set(player_ids):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Both players must be members of this league",
        )


@league_router.get("/{slug}/compare/{player_a_id}/{player_b_id}", response_model=H2HResponse)
async def compare_league_players(
    player_a_id: uuid.UUID,
    player_b_id: uuid.UUID,
    ctx: LeagueMemberDep,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> H2HResponse:
    """Head-to-head comparison constrained to two members of one league."""
    _player, league = ctx
    await _require_league_members(league.id, [player_a_id, player_b_id], db)
    return await _compute_h2h(player_a_id, player_b_id, db)


# ---------------------------------------------------------------------------
