"""Match read endpoints."""

import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import CurrentPlayer
from src.database import get_db
from src.models.group import Group
from src.models.match import Match, MatchStatus
from src.models.team import Team, TournamentStage

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/matches", tags=["matches"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class TeamRef(BaseModel):
    id: str
    name: str
    code: str
    flag_emoji: str


class MatchResponse(BaseModel):
    id: str
    match_number: int
    stage: str
    group_id: str | None
    group_name: str | None = None  # e.g. "A", "B" — only set for group-stage matches
    home_team: TeamRef | None
    away_team: TeamRef | None
    home_team_placeholder: str | None
    away_team_placeholder: str | None
    kickoff_utc: str
    venue: str | None
    status: str
    actual_home_score: int | None
    actual_away_score: int | None
    extra_time: bool
    penalties: bool
    postponed_reason: str | None
    # Live elapsed minute (U27.B1). The football-data.org v4 competition-matches
    # feed the result-fetcher consumes does not carry a per-match minute, and the
    # matches table has no column for it, so this is currently always null. The
    # field is part of the contract so the live hub can light up the minute the
    # day a source for it exists, without another schema/API round-trip.
    elapsed_minutes: int | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _load_team_map(db: AsyncSession) -> dict[uuid.UUID, Team]:
    result = await db.execute(select(Team))
    return {t.id: t for t in result.scalars().all()}


async def _load_group_map(db: AsyncSession) -> dict[uuid.UUID, str]:
    result = await db.execute(select(Group))
    return {g.id: g.name for g in result.scalars().all()}


def _team_ref(tid: uuid.UUID | None, team_map: dict[uuid.UUID, Team]) -> TeamRef | None:
    if tid is None:
        return None
    t = team_map.get(tid)
    if t is None:
        return None
    return TeamRef(id=str(t.id), name=t.name, code=t.code, flag_emoji=t.flag_emoji)


def _to_response(
    m: Match,
    team_map: dict[uuid.UUID, Team],
    group_map: dict[uuid.UUID, str] | None = None,
) -> MatchResponse:
    return MatchResponse(
        id=str(m.id),
        match_number=m.match_number,
        stage=m.stage.value,
        group_id=str(m.group_id) if m.group_id else None,
        group_name=group_map.get(m.group_id) if (group_map and m.group_id) else None,
        home_team=_team_ref(m.home_team_id, team_map),
        away_team=_team_ref(m.away_team_id, team_map),
        home_team_placeholder=m.home_team_placeholder,
        away_team_placeholder=m.away_team_placeholder,
        kickoff_utc=m.kickoff_utc.isoformat() + "Z",
        venue=m.venue,
        status=m.status.value,
        actual_home_score=m.actual_home_score,
        actual_away_score=m.actual_away_score,
        extra_time=m.extra_time,
        penalties=m.penalties,
        postponed_reason=m.postponed_reason,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=list[MatchResponse])
async def list_matches(
    player: CurrentPlayer,
    db: Annotated[AsyncSession, Depends(get_db)],
    stage: str | None = Query(None),
) -> list[MatchResponse]:
    if stage is not None:
        try:
            TournamentStage(stage)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid stage: {stage!r}",
            )

    q = (
        select(Match)
        .where(Match.deleted_at.is_(None))
        .order_by(Match.kickoff_utc, Match.match_number)
    )
    if stage is not None:
        q = q.where(Match.stage == stage)

    result = await db.execute(q)
    matches = result.scalars().all()
    team_map = await _load_team_map(db)
    group_map = await _load_group_map(db)
    return [_to_response(m, team_map, group_map) for m in matches]


@router.get("/upcoming", response_model=list[MatchResponse])
async def upcoming_matches(
    player: CurrentPlayer,
    db: Annotated[AsyncSession, Depends(get_db)],
    n: int = Query(10, ge=1, le=50),
) -> list[MatchResponse]:
    q = (
        select(Match)
        .where(Match.deleted_at.is_(None), Match.status == MatchStatus.scheduled)
        .order_by(Match.kickoff_utc, Match.match_number)
        .limit(n)
    )
    result = await db.execute(q)
    matches = result.scalars().all()
    team_map = await _load_team_map(db)
    group_map = await _load_group_map(db)
    return [_to_response(m, team_map, group_map) for m in matches]


@router.get("/live", response_model=list[MatchResponse])
async def live_matches(
    player: CurrentPlayer,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[MatchResponse]:
    q = (
        select(Match)
        .where(Match.deleted_at.is_(None), Match.status == MatchStatus.live)
        .order_by(Match.kickoff_utc, Match.match_number)
    )
    result = await db.execute(q)
    matches = result.scalars().all()
    team_map = await _load_team_map(db)
    group_map = await _load_group_map(db)
    return [_to_response(m, team_map, group_map) for m in matches]


@router.get("/{match_id}", response_model=MatchResponse)
async def get_match(
    match_id: uuid.UUID,
    player: CurrentPlayer,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MatchResponse:
    result = await db.execute(select(Match).where(Match.id == match_id, Match.deleted_at.is_(None)))
    match = result.scalar_one_or_none()
    if match is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Match not found")
    team_map = await _load_team_map(db)
    group_map = await _load_group_map(db)
    return _to_response(match, team_map, group_map)
