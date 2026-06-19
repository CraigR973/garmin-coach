"""Group standings endpoints."""

from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import CurrentPlayer
from src.database import get_db
from src.models.group import Group
from src.models.match import Match, MatchStatus
from src.models.team import Team

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/groups", tags=["groups"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class TeamStanding(BaseModel):
    position: int
    team_id: str
    team_name: str
    team_code: str
    flag_emoji: str
    played: int
    won: int
    drawn: int
    lost: int
    gf: int
    ga: int
    gd: int
    points: int


class GroupResponse(BaseModel):
    id: str
    name: str
    standings: list[TeamStanding]


# ---------------------------------------------------------------------------
# Standings computation
# ---------------------------------------------------------------------------


def _compute_standings(
    teams: list[Team],
    matches: list[Match],
    override: list[str] | None,
) -> list[TeamStanding]:
    """Compute group standings with FIFA tiebreaker: points → GD → GF → H2H."""
    stats: dict[str, dict[str, Any]] = {
        t.code: {
            "team": t,
            "played": 0,
            "won": 0,
            "drawn": 0,
            "lost": 0,
            "gf": 0,
            "ga": 0,
        }
        for t in teams
    }
    team_by_id: dict[Any, Team] = {t.id: t for t in teams}

    for m in matches:
        if m.status != MatchStatus.completed:
            continue
        if m.home_team_id is None or m.away_team_id is None:
            continue
        if m.actual_home_score is None or m.actual_away_score is None:
            continue
        ht = team_by_id.get(m.home_team_id)
        at = team_by_id.get(m.away_team_id)
        if ht is None or at is None:
            continue

        hs, as_ = m.actual_home_score, m.actual_away_score
        stats[ht.code]["played"] += 1
        stats[ht.code]["gf"] += hs
        stats[ht.code]["ga"] += as_
        stats[at.code]["played"] += 1
        stats[at.code]["gf"] += as_
        stats[at.code]["ga"] += hs

        if hs > as_:
            stats[ht.code]["won"] += 1
            stats[at.code]["lost"] += 1
        elif hs < as_:
            stats[ht.code]["lost"] += 1
            stats[at.code]["won"] += 1
        else:
            stats[ht.code]["drawn"] += 1
            stats[at.code]["drawn"] += 1

    def _pts(s: dict[str, Any]) -> int:
        return int(s["won"]) * 3 + int(s["drawn"])

    def _gd(s: dict[str, Any]) -> int:
        return int(s["gf"]) - int(s["ga"])

    def _primary_key(code: str) -> tuple[int, int, int, str]:
        s = stats[code]
        return (-_pts(s), -_gd(s), -s["gf"], code)

    sorted_codes = sorted(stats.keys(), key=_primary_key)
    if len(sorted_codes) > 1:
        sorted_codes = _apply_h2h(sorted_codes, stats, matches, team_by_id)

    if override:
        pos_map = {code: i for i, code in enumerate(override)}
        sorted_codes = sorted(sorted_codes, key=lambda c: pos_map.get(c, 999))

    result = []
    for pos, code in enumerate(sorted_codes, 1):
        s = stats[code]
        t = s["team"]
        result.append(
            TeamStanding(
                position=pos,
                team_id=str(t.id),
                team_name=t.name,
                team_code=t.code,
                flag_emoji=t.flag_emoji,
                played=s["played"],
                won=s["won"],
                drawn=s["drawn"],
                lost=s["lost"],
                gf=s["gf"],
                ga=s["ga"],
                gd=_gd(s),
                points=_pts(s),
            )
        )
    return result


def _apply_h2h(
    sorted_codes: list[str],
    stats: dict[str, dict[str, Any]],
    matches: list[Match],
    team_by_id: dict[Any, Any],
) -> list[str]:
    """Re-sort within blocks of teams tied on points, GD, and GF using H2H."""

    def _pts(s: dict[str, Any]) -> int:
        return int(s["won"]) * 3 + int(s["drawn"])

    def _gd(s: dict[str, Any]) -> int:
        return int(s["gf"]) - int(s["ga"])

    # Partition consecutive equal-statistic blocks
    blocks: list[list[str]] = []
    current: list[str] = [sorted_codes[0]]
    for code in sorted_codes[1:]:
        prev_s = stats[current[-1]]
        curr_s = stats[code]
        same = (
            _pts(prev_s) == _pts(curr_s)
            and _gd(prev_s) == _gd(curr_s)
            and prev_s["gf"] == curr_s["gf"]
        )
        if same:
            current.append(code)
        else:
            blocks.append(current)
            current = [code]
    blocks.append(current)

    result: list[str] = []
    for block in blocks:
        if len(block) == 1:
            result.extend(block)
            continue

        block_set = set(block)
        h2h: dict[str, dict[str, int]] = {c: {"pts": 0, "gd": 0, "gf": 0} for c in block}

        for m in matches:
            if m.status != MatchStatus.completed:
                continue
            if m.home_team_id is None or m.away_team_id is None:
                continue
            if m.actual_home_score is None or m.actual_away_score is None:
                continue
            ht = team_by_id.get(m.home_team_id)
            at = team_by_id.get(m.away_team_id)
            if ht is None or at is None:
                continue
            if ht.code not in block_set or at.code not in block_set:
                continue

            hs, as_ = m.actual_home_score, m.actual_away_score
            h2h[ht.code]["gf"] += hs
            h2h[ht.code]["gd"] += hs - as_
            h2h[at.code]["gf"] += as_
            h2h[at.code]["gd"] += as_ - hs
            if hs > as_:
                h2h[ht.code]["pts"] += 3
            elif hs < as_:
                h2h[at.code]["pts"] += 3
            else:
                h2h[ht.code]["pts"] += 1
                h2h[at.code]["pts"] += 1

        def _h2h_key(code: str) -> tuple[int, int, int, str]:
            h = h2h[code]
            return (-h["pts"], -h["gd"], -h["gf"], code)

        result.extend(sorted(block, key=_h2h_key))

    return result


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------


async def _build_group_response(group: Group, db: AsyncSession) -> GroupResponse:
    teams_r = await db.execute(select(Team).where(Team.group_id == group.id))
    teams = list(teams_r.scalars().all())

    matches_r = await db.execute(
        select(Match).where(
            Match.group_id == group.id,
            Match.deleted_at.is_(None),
        )
    )
    matches = list(matches_r.scalars().all())

    override: list[str] | None = group.standings_override
    standings = _compute_standings(teams, matches, override)

    return GroupResponse(id=str(group.id), name=group.name, standings=standings)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=list[GroupResponse])
async def list_groups(
    player: CurrentPlayer,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[GroupResponse]:
    result = await db.execute(select(Group).order_by(Group.name))
    groups = result.scalars().all()
    return [await _build_group_response(g, db) for g in groups]


@router.get("/{name}", response_model=GroupResponse)
async def get_group(
    name: str,
    player: CurrentPlayer,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> GroupResponse:
    result = await db.execute(select(Group).where(Group.name == name.upper()))
    group = result.scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    return await _build_group_response(group, db)
