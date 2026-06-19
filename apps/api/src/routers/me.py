"""Cross-league endpoints scoped to the authenticated player (``/api/v1/me``)."""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import CurrentPlayer
from src.database import get_db
from src.models.league import League
from src.models.league_membership import LeagueMembership
from src.models.match import Match, MatchStatus
from src.models.prediction import LeaderboardSnapshot, Prediction, SpecialPrediction
from src.models.team import Team
from src.rate_limit import limiter, per_player_key

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/me", tags=["me"])

# Average rank is only meaningful across leagues with enough members to rank
# against (MD-7): a 1- or 2-person league is rank 1 by default and would game
# the average, so leagues below this size are excluded from the mean.
_MIN_MEMBERS_FOR_AVG = 3


class PerLeagueRank(BaseModel):
    slug: str
    name: str
    rank: int | None
    member_count: int
    rank_delta: int | None = None
    triggered_by_match_id: str | None = None


class CrossLeagueSummaryResponse(BaseModel):
    avg_rank: float | None
    total_points: int
    leagues_count: int
    per_league: list[PerLeagueRank]


@router.get("/cross-league-summary", response_model=CrossLeagueSummaryResponse)
@limiter.limit("120/minute", key_func=per_player_key)
async def cross_league_summary(
    request: Request,
    player: CurrentPlayer,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CrossLeagueSummaryResponse:
    """Average rank across the caller's leagues, with a per-league breakdown.

    Three fixed queries (no N+1 over leagues): the caller's memberships, the
    member count per league, and the caller's latest snapshot per league. Rank
    is read from the stored per-league snapshot rank (MD-13); the average only
    spans leagues with >= ``_MIN_MEMBERS_FOR_AVG`` members.
    """
    membership_rows = (
        await db.execute(
            select(League.id, League.slug, League.name)
            .join(LeagueMembership, LeagueMembership.league_id == League.id)
            .where(
                LeagueMembership.player_id == player.id,
                LeagueMembership.deleted_at.is_(None),
                League.deleted_at.is_(None),
            )
            .order_by(League.name)
        )
    ).all()

    if not membership_rows:
        return CrossLeagueSummaryResponse(
            avg_rank=None, total_points=0, leagues_count=0, per_league=[]
        )

    league_ids = [row.id for row in membership_rows]

    count_rows = (
        await db.execute(
            select(LeagueMembership.league_id, func.count().label("member_count"))
            .where(
                LeagueMembership.league_id.in_(league_ids),
                LeagueMembership.deleted_at.is_(None),
            )
            .group_by(LeagueMembership.league_id)
        )
    ).all()
    member_counts = {row.league_id: row.member_count for row in count_rows}

    # Top-2 snapshots per league via a window function so we can compute
    # rank_delta = prior.rank − latest.rank (positive = moved up).
    # The (snapshot_at DESC, id DESC) ordering is the same tie-safe rule used
    # by the leaderboard; rn=1 is the latest, rn=2 is the prior.
    _rn = (
        func.row_number()
        .over(
            partition_by=LeaderboardSnapshot.league_id,
            order_by=[
                LeaderboardSnapshot.snapshot_at.desc(),
                LeaderboardSnapshot.id.desc(),
            ],
        )
        .label("rn")
    )

    _snap_subq = (
        select(
            LeaderboardSnapshot.league_id,
            LeaderboardSnapshot.rank,
            LeaderboardSnapshot.total_points,
            LeaderboardSnapshot.triggered_by_match_id,
            _rn,
        )
        .where(
            LeaderboardSnapshot.player_id == player.id,
            LeaderboardSnapshot.league_id.in_(league_ids),
        )
        .subquery()
    )

    snapshot_rows = (
        await db.execute(
            select(_snap_subq)
            .where(_snap_subq.c.rn <= 2)
            .order_by(_snap_subq.c.league_id, _snap_subq.c.rn)
        )
    ).all()

    # Group into per-league lists; rn=1 is always the latest row.
    snapshots_by_league: dict[uuid.UUID, list[Any]] = {}
    for row in snapshot_rows:
        snapshots_by_league.setdefault(row.league_id, []).append(row)

    ranks = {lid: rows[0].rank for lid, rows in snapshots_by_league.items()}
    rank_deltas: dict[uuid.UUID, int | None] = {
        lid: (rows[1].rank - rows[0].rank if len(rows) >= 2 else None)
        for lid, rows in snapshots_by_league.items()
    }
    triggered_by: dict[uuid.UUID, uuid.UUID | None] = {
        lid: rows[0].triggered_by_match_id for lid, rows in snapshots_by_league.items()
    }
    # total_points is global per player (predictions are global), so any
    # league's snapshot carries the same value; 0 before any result lands.
    total_points = max((rows[0].total_points for rows in snapshots_by_league.values()), default=0)

    per_league: list[PerLeagueRank] = []
    ranks_for_avg: list[int] = []
    for row in membership_rows:
        member_count = member_counts.get(row.id, 0)
        rank = ranks.get(row.id)
        tbm = triggered_by.get(row.id)
        per_league.append(
            PerLeagueRank(
                slug=row.slug,
                name=row.name,
                rank=rank,
                member_count=member_count,
                rank_delta=rank_deltas.get(row.id),
                triggered_by_match_id=str(tbm) if tbm is not None else None,
            )
        )
        if rank is not None and member_count >= _MIN_MEMBERS_FOR_AVG:
            ranks_for_avg.append(rank)

    avg_rank = round(sum(ranks_for_avg) / len(ranks_for_avg), 2) if ranks_for_avg else None

    return CrossLeagueSummaryResponse(
        avg_rank=avg_rank,
        total_points=total_points,
        leagues_count=len(membership_rows),
        per_league=per_league,
    )


# ---------------------------------------------------------------------------
# GET /me/home — to-do + results roll-up (U17.1)
# ---------------------------------------------------------------------------


def _now_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class NextMatchTodo(BaseModel):
    id: str
    kickoff_utc: str
    home_label: str
    away_label: str
    predicted: bool


class HomeTodoBlock(BaseModel):
    specials_submitted: bool
    specials_count: int
    specials_lock_at: str | None
    upcoming_unpredicted: int
    next_match: NextMatchTodo | None
    opening_match_predicted: bool


class RollupMatch(BaseModel):
    match_id: str
    kickoff_utc: str
    home_label: str
    away_label: str
    home_flag: str | None
    away_flag: str | None
    actual_home: int | None
    actual_away: int | None
    predicted_home: int | None
    predicted_away: int | None
    points_breakdown: dict[str, Any] | None


class HomeRollupBlock(BaseModel):
    matchday: str
    points_gained: int
    match_count: int
    matches: list[RollupMatch]


class HomeResponse(BaseModel):
    todo: HomeTodoBlock
    rollup: HomeRollupBlock | None


@router.get("/home", response_model=HomeResponse)
@limiter.limit("120/minute", key_func=per_player_key)
async def me_home(
    request: Request,
    player: CurrentPlayer,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> HomeResponse:
    """To-do block + results roll-up for the home page (U17.1).

    Two logical halves:
    - ``todo``: what the caller needs to do next (specials + upcoming unpredicted)
    - ``rollup``: the most recent completed matchday the caller predicted; null pre-tournament
    """
    now = _now_utc()

    # --- specials lock (opening group match) ---
    opening = (
        await db.execute(
            select(Match)
            .where(
                Match.stage == "group",
                Match.deleted_at.is_(None),
            )
            .order_by(Match.kickoff_utc.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    specials_lock_at = opening.kickoff_utc.isoformat() + "Z" if opening is not None else None
    specials_locked = opening is not None and now >= opening.kickoff_utc

    # --- specials submitted? ---
    specials_count = (
        await db.execute(
            select(func.count())
            .select_from(SpecialPrediction)
            .where(
                SpecialPrediction.player_id == player.id,
                SpecialPrediction.submitted_at.is_not(None),
            )
        )
    ).scalar_one()
    specials_submitted = specials_count > 0

    # --- opening match predicted? ---
    opening_match_predicted = False
    if opening is not None:
        opening_pred_count = (
            await db.execute(
                select(func.count())
                .select_from(Prediction)
                .where(
                    Prediction.player_id == player.id,
                    Prediction.match_id == opening.id,
                    Prediction.deleted_at.is_(None),
                    Prediction.predicted_home.is_not(None),
                )
            )
        ).scalar_one()
        opening_match_predicted = opening_pred_count > 0

    # --- predicted match ids (for exclusion) ---
    predicted_match_ids_subq = (
        select(Prediction.match_id)
        .where(
            Prediction.player_id == player.id,
            Prediction.deleted_at.is_(None),
        )
        .scalar_subquery()
    )

    # --- upcoming unpredicted count (status=scheduled, kickoff > now, no prediction) ---
    upcoming_unpredicted = (
        await db.execute(
            select(func.count())
            .select_from(Match)
            .where(
                Match.status == MatchStatus.scheduled,
                Match.kickoff_utc > now,
                Match.deleted_at.is_(None),
                Match.id.not_in(predicted_match_ids_subq),
            )
        )
    ).scalar_one()

    # --- next upcoming scheduled match ---
    next_match_row = (
        await db.execute(
            select(Match)
            .where(
                Match.status == MatchStatus.scheduled,
                Match.kickoff_utc > now,
                Match.deleted_at.is_(None),
            )
            .order_by(Match.kickoff_utc.asc())
            .limit(1)
        )
    ).scalar_one_or_none()

    next_match_todo: NextMatchTodo | None = None
    if next_match_row is not None:
        # Fetch team labels for next match
        nm_team_ids = [
            tid
            for tid in [next_match_row.home_team_id, next_match_row.away_team_id]
            if tid is not None
        ]
        nm_teams: dict[str, Team] = {}
        if nm_team_ids:
            tr = await db.execute(select(Team).where(Team.id.in_(nm_team_ids)))
            nm_teams = {str(t.id): t for t in tr.scalars().all()}

        def _label(team_id: uuid.UUID | None, placeholder: str | None) -> str:
            if team_id is not None and str(team_id) in nm_teams:
                t = nm_teams[str(team_id)]
                return f"{t.flag_emoji} {t.name}"
            return placeholder or "?"

        # Check if caller has predicted this match
        has_pred = (
            await db.execute(
                select(func.count())
                .select_from(Prediction)
                .where(
                    Prediction.player_id == player.id,
                    Prediction.match_id == next_match_row.id,
                    Prediction.deleted_at.is_(None),
                )
            )
        ).scalar_one()
        next_match_todo = NextMatchTodo(
            id=str(next_match_row.id),
            kickoff_utc=next_match_row.kickoff_utc.isoformat() + "Z",
            home_label=_label(next_match_row.home_team_id, next_match_row.home_team_placeholder),
            away_label=_label(next_match_row.away_team_id, next_match_row.away_team_placeholder),
            predicted=has_pred > 0,
        )

    todo = HomeTodoBlock(
        specials_submitted=specials_submitted,
        specials_count=specials_count,
        specials_lock_at=specials_lock_at if not specials_locked else None,
        upcoming_unpredicted=upcoming_unpredicted,
        next_match=next_match_todo,
        opening_match_predicted=opening_match_predicted,
    )

    # --- rollup: most recent completed matchday the caller predicted ---
    # Group by UTC date of kickoff, find the latest date with scored predictions.
    matchday_subq = (
        select(cast(Match.kickoff_utc, Date).label("matchday"))
        .join(Prediction, Prediction.match_id == Match.id)
        .where(
            Prediction.player_id == player.id,
            Prediction.deleted_at.is_(None),
            Prediction.points_awarded.is_not(None),
            Match.deleted_at.is_(None),
        )
        .order_by(cast(Match.kickoff_utc, Date).desc())
        .limit(1)
        .scalar_subquery()
    )

    rollup_rows = (
        await db.execute(
            select(Prediction, Match)
            .join(Match, Match.id == Prediction.match_id)
            .where(
                Prediction.player_id == player.id,
                Prediction.deleted_at.is_(None),
                Prediction.points_awarded.is_not(None),
                Match.deleted_at.is_(None),
                cast(Match.kickoff_utc, Date) == matchday_subq,
            )
            .order_by(Match.kickoff_utc.asc(), Match.id.asc())
        )
    ).all()

    rollup: HomeRollupBlock | None = None
    if rollup_rows:
        # Batch-fetch teams for rollup matches
        rollup_team_ids: set[uuid.UUID] = set()
        for _, m in rollup_rows:
            if m.home_team_id is not None:
                rollup_team_ids.add(m.home_team_id)
            if m.away_team_id is not None:
                rollup_team_ids.add(m.away_team_id)

        rollup_teams: dict[str, Team] = {}
        if rollup_team_ids:
            tr2 = await db.execute(select(Team).where(Team.id.in_(rollup_team_ids)))
            rollup_teams = {str(t.id): t for t in tr2.scalars().all()}

        first_match = rollup_rows[0][1]
        matchday_str = first_match.kickoff_utc.date().isoformat()
        total_pts = sum(p.points_awarded or 0 for p, _ in rollup_rows)

        rollup_matches: list[RollupMatch] = []
        for pred, match in rollup_rows:
            ht = rollup_teams.get(str(match.home_team_id)) if match.home_team_id else None
            at = rollup_teams.get(str(match.away_team_id)) if match.away_team_id else None
            home_label = (
                f"{ht.flag_emoji} {ht.name}" if ht else (match.home_team_placeholder or "?")
            )
            away_label = (
                f"{at.flag_emoji} {at.name}" if at else (match.away_team_placeholder or "?")
            )
            rollup_matches.append(
                RollupMatch(
                    match_id=str(match.id),
                    kickoff_utc=match.kickoff_utc.isoformat() + "Z",
                    home_label=home_label,
                    away_label=away_label,
                    home_flag=ht.flag_emoji if ht else None,
                    away_flag=at.flag_emoji if at else None,
                    actual_home=match.actual_home_score,
                    actual_away=match.actual_away_score,
                    predicted_home=pred.predicted_home,
                    predicted_away=pred.predicted_away,
                    points_breakdown=pred.points_breakdown,
                )
            )

        rollup = HomeRollupBlock(
            matchday=matchday_str,
            points_gained=total_pts,
            match_count=len(rollup_rows),
            matches=rollup_matches,
        )

    return HomeResponse(todo=todo, rollup=rollup)
