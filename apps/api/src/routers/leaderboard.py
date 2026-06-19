"""Leaderboard endpoints — per-league overall, history, and per-round.

Data is served per-league under ``/api/v1/leagues/{slug}/leaderboard*``;
the league is resolved (and membership enforced) by the
``require_league_member`` dependency.
"""

import uuid
from collections import defaultdict
from datetime import UTC, datetime, time, timedelta
from typing import Annotated, Any
from zoneinfo import ZoneInfo

import structlog
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from src.auth import CurrentPlayer
from src.database import get_db
from src.models.league_membership import LeagueMembership
from src.models.match import Match
from src.models.prediction import KnockoutPrediction, LeaderboardSnapshot, Prediction
from src.models.profile import Profile
from src.models.team import TournamentStage
from src.rate_limit import limiter, per_player_key
from src.routers.leagues import LeagueMemberDep

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

league_router = APIRouter(prefix="/api/v1/leagues", tags=["leaderboard"])
global_router = APIRouter(prefix="/api/v1/leaderboard", tags=["leaderboard"])

# Tournament progression order, used to pick the "current" (furthest-progressed)
# stage for the temporal round metric. third_place (a consolation played before
# the final) ranks below the final so the final wins once it is settled.
_STAGE_ORDER: dict[TournamentStage, int] = {
    TournamentStage.group: 0,
    TournamentStage.r32: 1,
    TournamentStage.r16: 2,
    TournamentStage.qf: 3,
    TournamentStage.sf: 4,
    TournamentStage.third_place: 5,
    TournamentStage.final: 6,
    TournamentStage.winner: 7,
}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class LeaderboardEntryOut(BaseModel):
    rank: int
    player_id: str
    player_name: str
    total_points: int
    match_points: int
    knockout_winner_points: int
    special_points: int
    is_active: bool
    # U38 tiebreak counts — the merit cascade that orders players level on
    # total_points (exact → result → goals → specials → KO-winner). Stored on
    # the snapshot, so they always justify the rank shown alongside them.
    exact_count: int = 0
    correct_result_count: int = 0
    correct_goals_count: int = 0
    specials_correct_count: int = 0
    ko_winner_correct_count: int = 0
    # True when this player shares a rank with another — i.e. a genuine all-axis
    # tie the cascade could not break, flagged for admin settlement (U38.4).
    tied: bool = False
    # Temporal metrics (U22.2), derived at query time — never stored. Match-scoped
    # points only (scoreline + knockout winner); tournament-long specials excluded.
    last_match_points: int = 0  # points on the most recently settled match
    today_points: int = 0  # points from matches settled in the viewer's local day
    round_points: int = 0  # points in the current (furthest-progressed) stage
    # Avatar (U23.1) — null when the player hasn't set a photo
    avatar_url: str | None = None


class SnapshotPoint(BaseModel):
    snapshot_at: str
    total_points: int
    rank: int


class HistoryEntryOut(BaseModel):
    player_id: str
    player_name: str
    snapshots: list[SnapshotPoint]


class RoundEntryOut(BaseModel):
    rank: int
    player_id: str
    player_name: str
    avatar_url: str | None = None
    points: int
    # U38 tiebreak counts, scoped to this stage. Specials are tournament-long and
    # not attributable to a round, so the round cascade stops at KO-winner picks.
    exact_count: int = 0
    correct_result_count: int = 0
    correct_goals_count: int = 0
    ko_winner_correct_count: int = 0
    tied: bool = False


# ---------------------------------------------------------------------------
# Query helpers (per-league)
# ---------------------------------------------------------------------------


async def _leaderboard_entries(
    db: AsyncSession, league_id: uuid.UUID, *, include_inactive: bool
) -> list[LeaderboardEntryOut]:
    """Latest snapshot per player within one league.

    Postgres ``DISTINCT ON`` picks exactly one snapshot per player. Multiple
    recomputes inside one transaction (e.g. trigger + specials helper) share
    ``transaction_timestamp()``, so ``snapshot_at`` ties are real; the
    secondary ``id DESC`` sort breaks them deterministically. ``league_id``
    is already filtered, so ``player_id`` alone keys the DISTINCT ON.
    """
    latest_per_player = (
        select(LeaderboardSnapshot)
        .where(LeaderboardSnapshot.league_id == league_id)
        .distinct(LeaderboardSnapshot.player_id)
        .order_by(
            LeaderboardSnapshot.player_id,
            LeaderboardSnapshot.snapshot_at.desc(),
            LeaderboardSnapshot.id.desc(),
        )
        .subquery()
    )
    latest_snap = aliased(LeaderboardSnapshot, latest_per_player)

    stmt = (
        select(Profile, latest_snap)
        .join(latest_snap, latest_snap.player_id == Profile.id)
        .join(
            LeagueMembership,
            (LeagueMembership.player_id == Profile.id)
            & (LeagueMembership.league_id == league_id)
            & (LeagueMembership.deleted_at.is_(None)),
        )
        .where(Profile.deleted_at.is_(None))
    )
    if not include_inactive:
        stmt = stmt.where(Profile.is_active.is_(True))
    stmt = stmt.order_by(latest_snap.rank.asc(), Profile.display_name.asc())

    rows = (await db.execute(stmt)).all()
    # A shared rank survives the merit cascade only when two players tie on every
    # axis — the genuine all-axis tie flagged for admin settlement (U38.4). Count
    # rank occurrences so each tied row can carry that flag.
    rank_counts: dict[int, int] = defaultdict(int)
    for _profile, snapshot in rows:
        rank_counts[snapshot.rank] += 1
    return [
        LeaderboardEntryOut(
            rank=snapshot.rank,
            player_id=str(profile.id),
            player_name=profile.display_name,
            total_points=snapshot.total_points,
            match_points=snapshot.match_points,
            knockout_winner_points=snapshot.knockout_winner_points,
            special_points=snapshot.special_points,
            exact_count=snapshot.exact_count,
            correct_result_count=snapshot.correct_result_count,
            correct_goals_count=snapshot.correct_goals_count,
            specials_correct_count=snapshot.specials_correct_count,
            ko_winner_correct_count=snapshot.ko_winner_correct_count,
            tied=rank_counts[snapshot.rank] > 1,
            is_active=profile.is_active,
            avatar_url=profile.avatar_url,
        )
        for profile, snapshot in rows
    ]


async def _leaderboard_history(
    db: AsyncSession, league_id: uuid.UUID, *, include_inactive: bool
) -> list[HistoryEntryOut]:
    stmt = (
        select(Profile, LeaderboardSnapshot)
        .join(LeaderboardSnapshot, LeaderboardSnapshot.player_id == Profile.id)
        .join(
            LeagueMembership,
            (LeagueMembership.player_id == Profile.id)
            & (LeagueMembership.league_id == league_id)
            & (LeagueMembership.deleted_at.is_(None)),
        )
        .where(Profile.deleted_at.is_(None))
        .where(LeaderboardSnapshot.league_id == league_id)
        .order_by(LeaderboardSnapshot.snapshot_at.asc(), Profile.display_name.asc())
    )
    if not include_inactive:
        stmt = stmt.where(Profile.is_active.is_(True))

    rows = (await db.execute(stmt)).all()

    players: dict[str, HistoryEntryOut] = {}
    for profile, snapshot in rows:
        pid = str(profile.id)
        if pid not in players:
            players[pid] = HistoryEntryOut(
                player_id=pid,
                player_name=profile.display_name,
                snapshots=[],
            )
        players[pid].snapshots.append(
            SnapshotPoint(
                snapshot_at=snapshot.snapshot_at.isoformat() + "Z",
                total_points=snapshot.total_points,
                rank=snapshot.rank,
            )
        )
    return list(players.values())


async def _round_leaderboard(
    db: AsyncSession,
    league_id: uuid.UUID,
    stage: TournamentStage,
    *,
    include_inactive: bool,
) -> list[RoundEntryOut]:
    """Points + merit-cascade order for one tournament stage, scoped to members.

    Predictions are global, but the leaderboard only ranks this league's
    members — so the player set is constrained to active memberships.

    Includes both scoreline (``predictions``) and knockout-winner
    (``knockout_predictions``) points so a knockout stage's per-round total
    matches the leaderboard's "round" metric (U22.2). The group stage has no
    knockout predictions, so its total is unchanged.

    Ties are broken by the same merit cascade as the overall standings, but
    scoped to this stage: ``points → exact → result → goals → KO-winner``.
    Specials are tournament-long, not attributable to a round, so the round
    cascade omits them. Two players share a rank only when level on every
    stage-scoped axis; display name is a pure output stabiliser, never a rank
    differentiator.
    """
    member_stmt = (
        select(Profile)
        .join(
            LeagueMembership,
            (LeagueMembership.player_id == Profile.id)
            & (LeagueMembership.league_id == league_id)
            & (LeagueMembership.deleted_at.is_(None)),
        )
        .where(Profile.deleted_at.is_(None))
    )
    if not include_inactive:
        member_stmt = member_stmt.where(Profile.is_active.is_(True))
    members = list((await db.execute(member_stmt)).scalars().all())
    if not members:
        return []
    member_ids = [m.id for m in members]

    # Stage-scoped scoreline predictions: points + the breakdown that feeds the
    # exact/result/goals counts.
    pred_rows = (
        await db.execute(
            select(
                Prediction.player_id,
                Prediction.points_awarded,
                Prediction.points_breakdown,
            )
            .join(Match, Match.id == Prediction.match_id)
            .where(
                Match.stage == stage,
                Match.deleted_at.is_(None),
                Prediction.deleted_at.is_(None),
                Prediction.points_awarded.is_not(None),
                Prediction.player_id.in_(member_ids),
            )
        )
    ).all()
    # Stage-scoped knockout-winner picks: points only (a correct pick > 0).
    ko_rows = (
        await db.execute(
            select(
                KnockoutPrediction.player_id,
                KnockoutPrediction.points_awarded,
            )
            .join(Match, Match.id == KnockoutPrediction.match_id)
            .where(
                Match.stage == stage,
                Match.deleted_at.is_(None),
                KnockoutPrediction.points_awarded.is_not(None),
                KnockoutPrediction.player_id.in_(member_ids),
            )
        )
    ).all()

    # Aggregate per player: [points, exact, result, goals, ko_winner].
    agg: dict[uuid.UUID, list[int]] = defaultdict(lambda: [0, 0, 0, 0, 0])
    for player_id, pts, breakdown in pred_rows:
        a = agg[player_id]
        a[0] += pts
        if breakdown:
            if breakdown.get("exact", 0) > 0:
                a[1] += 1
            if breakdown.get("result", 0) > 0:
                a[2] += 1
            if breakdown.get("goals", 0) > 0:
                a[3] += 1
    for player_id, pts in ko_rows:
        a = agg[player_id]
        a[0] += pts
        if pts > 0:
            a[4] += 1

    # Cascade key (higher is better on every axis); name is a stable tiebreak for
    # output order only, so it never separates a genuine all-axis tie.
    def cascade_key(m: Profile) -> tuple[int, int, int, int, int, str]:
        a = agg[m.id]
        return (-a[0], -a[1], -a[2], -a[3], -a[4], m.display_name.lower())

    ordered = sorted(members, key=cascade_key)

    entries: list[RoundEntryOut] = []
    rank = 0
    prev_merit: tuple[int, int, int, int, int] | None = None
    for idx, m in enumerate(ordered, start=1):
        a = agg[m.id]
        merit = (a[0], a[1], a[2], a[3], a[4])
        if merit != prev_merit:
            rank = idx  # competition ranking: skip after a shared block
            prev_merit = merit
        entries.append(
            RoundEntryOut(
                rank=rank,
                player_id=str(m.id),
                player_name=m.display_name,
                avatar_url=m.avatar_url,
                points=a[0],
                exact_count=a[1],
                correct_result_count=a[2],
                correct_goals_count=a[3],
                ko_winner_correct_count=a[4],
            )
        )

    # Flag genuine ties (shared rank) so the round view can mark them too.
    rank_counts: dict[int, int] = defaultdict(int)
    for e in entries:
        rank_counts[e.rank] += 1
    for e in entries:
        e.tied = rank_counts[e.rank] > 1
    return entries


def _viewer_day_bounds_utc(
    tz_name: str, *, now_utc: datetime | None = None
) -> tuple[datetime, datetime]:
    """[start, end) of the viewer's *local* calendar day, as naive UTC datetimes.

    ``matches.result_entered_at`` is stored naive-UTC, so the bounds are too.
    Falls back to UTC if the stored IANA name is missing/invalid. ``now_utc`` (a
    naive UTC instant) is injectable for deterministic tests; production passes
    nothing and the wall clock is used.
    """
    try:
        tz = ZoneInfo(tz_name)
    except Exception:  # noqa: BLE001 — any bad/unknown tz string → UTC
        tz = ZoneInfo("UTC")
    base = now_utc if now_utc is not None else datetime.now(UTC).replace(tzinfo=None)
    local = base.replace(tzinfo=UTC).astimezone(tz)
    start_local = datetime.combine(local.date(), time.min, tzinfo=tz)
    end_local = datetime.combine(local.date() + timedelta(days=1), time.min, tzinfo=tz)
    return (
        start_local.astimezone(UTC).replace(tzinfo=None),
        end_local.astimezone(UTC).replace(tzinfo=None),
    )


async def _temporal_points(
    db: AsyncSession,
    member_ids: list[uuid.UUID],
    viewer_tz: str,
) -> dict[uuid.UUID, tuple[int, int, int]]:
    """Per-player ``(last_match, today, round)`` points for the given members.

    All three are derived at query time from settled matches — the leaderboard
    snapshot stores only cumulative totals, so temporal deltas are computed, not
    stored (U22.2). Points are match-scoped: scoreline (``predictions``) plus
    knockout-winner (``knockout_predictions``); tournament-long specials are not
    attributable to a match/day/round and are excluded.

    * **last_match** — points on the single most recently settled match (global,
      by ``result_entered_at``); a player who did not predict it scores 0.
    * **today** — points from matches whose result landed in the viewer's local
      calendar day.
    * **round** — points in the current (furthest-progressed) stage; group is one
      round, each knockout stage its own.
    """
    if not member_ids:
        return {}

    # Settled matches are the source of truth for "last", "today" and the current
    # stage. result_entered_at is stamped once, at first result entry.
    settled = (
        await db.execute(
            select(Match.id, Match.stage, Match.result_entered_at).where(
                Match.result_entered_at.is_not(None),
                Match.deleted_at.is_(None),
            )
        )
    ).all()
    if not settled:
        return {}

    start_utc, end_utc = _viewer_day_bounds_utc(viewer_tz)
    last_match_id = max(settled, key=lambda r: r.result_entered_at).id
    current_stage = max((r.stage for r in settled), key=lambda s: _STAGE_ORDER.get(s, -1))
    today_match_ids = {r.id for r in settled if start_utc <= r.result_entered_at < end_utc}
    round_match_ids = {r.id for r in settled if r.stage == current_stage}

    # Per-(player, match) points from both prediction kinds, scoped to members.
    # points_awarded IS NOT NULL ⟺ that match has been scored.
    pred_rows = (
        await db.execute(
            select(
                Prediction.player_id,
                Prediction.match_id,
                Prediction.points_awarded,
            ).where(
                Prediction.player_id.in_(member_ids),
                Prediction.points_awarded.is_not(None),
                Prediction.deleted_at.is_(None),
            )
        )
    ).all()
    ko_rows = (
        await db.execute(
            select(
                KnockoutPrediction.player_id,
                KnockoutPrediction.match_id,
                KnockoutPrediction.points_awarded,
            ).where(
                KnockoutPrediction.player_id.in_(member_ids),
                KnockoutPrediction.points_awarded.is_not(None),
            )
        )
    ).all()

    last: dict[uuid.UUID, int] = defaultdict(int)
    today: dict[uuid.UUID, int] = defaultdict(int)
    rnd: dict[uuid.UUID, int] = defaultdict(int)
    for player_id, match_id, pts in (*pred_rows, *ko_rows):
        if match_id == last_match_id:
            last[player_id] += pts
        if match_id in today_match_ids:
            today[player_id] += pts
        if match_id in round_match_ids:
            rnd[player_id] += pts

    return {pid: (last.get(pid, 0), today.get(pid, 0), rnd.get(pid, 0)) for pid in member_ids}


# ---------------------------------------------------------------------------
# GET /api/v1/leagues/{slug}/leaderboard
# ---------------------------------------------------------------------------


@league_router.get("/{slug}/leaderboard", response_model=list[LeaderboardEntryOut])
@limiter.limit("120/minute", key_func=per_player_key)
async def get_league_leaderboard(
    request: Request,
    ctx: LeagueMemberDep,
    db: Annotated[AsyncSession, Depends(get_db)],
    include_inactive: bool = Query(default=False),
) -> list[LeaderboardEntryOut]:
    player, league = ctx
    entries = await _leaderboard_entries(db, league.id, include_inactive=include_inactive)
    # Attach temporal metrics (U22.2). "today" is the viewer's local day, so it is
    # computed from the caller's own timezone, not the row owner's.
    member_ids = [uuid.UUID(e.player_id) for e in entries]
    temporal = await _temporal_points(db, member_ids, player.timezone)
    for e in entries:
        last, today, rnd = temporal.get(uuid.UUID(e.player_id), (0, 0, 0))
        e.last_match_points = last
        e.today_points = today
        e.round_points = rnd
    return entries


@league_router.get("/{slug}/leaderboard/history", response_model=list[HistoryEntryOut])
async def get_league_leaderboard_history(
    ctx: LeagueMemberDep,
    db: Annotated[AsyncSession, Depends(get_db)],
    include_inactive: bool = Query(default=False),
) -> list[HistoryEntryOut]:
    _player, league = ctx
    return await _leaderboard_history(db, league.id, include_inactive=include_inactive)


@league_router.get("/{slug}/leaderboard/round/{stage}", response_model=list[RoundEntryOut])
async def get_league_round_leaderboard(
    stage: TournamentStage,
    ctx: LeagueMemberDep,
    db: Annotated[AsyncSession, Depends(get_db)],
    include_inactive: bool = Query(default=False),
) -> list[RoundEntryOut]:
    _player, league = ctx
    return await _round_leaderboard(db, league.id, stage, include_inactive=include_inactive)


# ---------------------------------------------------------------------------
# Global leaderboard helpers
# ---------------------------------------------------------------------------


async def _global_leaderboard_entries(db: AsyncSession) -> list[LeaderboardEntryOut]:
    """Latest snapshot per player across ALL leagues, re-ranked globally.

    Because predictions, knockout_predictions, and special_predictions are all
    keyed by player_id (not league_id), every player's points are identical
    across their league snapshots.  We pick the latest snapshot for each player
    regardless of which league wrote it, then re-rank the full cross-league
    roster using the same merit cascade as the per-league endpoint.
    """
    latest_per_player = (
        select(LeaderboardSnapshot)
        .distinct(LeaderboardSnapshot.player_id)
        .order_by(
            LeaderboardSnapshot.player_id,
            LeaderboardSnapshot.snapshot_at.desc(),
            LeaderboardSnapshot.id.desc(),
        )
        .subquery()
    )
    latest_snap = aliased(LeaderboardSnapshot, latest_per_player)

    stmt = (
        select(Profile, latest_snap)
        .join(latest_snap, latest_snap.player_id == Profile.id)
        .where(Profile.deleted_at.is_(None))
        .where(Profile.is_active.is_(True))
    )
    rows = (await db.execute(stmt)).all()

    # Re-rank globally using the same cascade as the per-league endpoint:
    # total_points → exact → result → goals → specials → KO-winner → name.
    def _cascade_key(
        row: Any,
    ) -> tuple[int, int, int, int, int, int, str]:
        profile, snap = row
        return (
            -snap.total_points,
            -snap.exact_count,
            -snap.correct_result_count,
            -snap.correct_goals_count,
            -snap.specials_correct_count,
            -snap.ko_winner_correct_count,
            profile.display_name.lower(),
        )

    sorted_rows = sorted(rows, key=_cascade_key)

    # Competition ranking: tied players share a rank; next rank skips ahead.
    assigned_ranks: list[int] = []
    rank = 0
    prev_merit: tuple[int, int, int, int, int, int] | None = None
    rank_counts: dict[int, int] = defaultdict(int)
    for idx, (profile, snap) in enumerate(sorted_rows, start=1):
        merit = (
            snap.total_points,
            snap.exact_count,
            snap.correct_result_count,
            snap.correct_goals_count,
            snap.specials_correct_count,
            snap.ko_winner_correct_count,
        )
        if merit != prev_merit:
            rank = idx
            prev_merit = merit
        assigned_ranks.append(rank)
        rank_counts[rank] += 1

    return [
        LeaderboardEntryOut(
            rank=r,
            player_id=str(profile.id),
            player_name=profile.display_name,
            total_points=snap.total_points,
            match_points=snap.match_points,
            knockout_winner_points=snap.knockout_winner_points,
            special_points=snap.special_points,
            exact_count=snap.exact_count,
            correct_result_count=snap.correct_result_count,
            correct_goals_count=snap.correct_goals_count,
            specials_correct_count=snap.specials_correct_count,
            ko_winner_correct_count=snap.ko_winner_correct_count,
            tied=rank_counts[r] > 1,
            is_active=profile.is_active,
            avatar_url=profile.avatar_url,
        )
        for (profile, snap), r in zip(sorted_rows, assigned_ranks)
    ]


# ---------------------------------------------------------------------------
# GET /api/v1/leaderboard/global
# ---------------------------------------------------------------------------


@global_router.get("/global", response_model=list[LeaderboardEntryOut])
@limiter.limit("60/minute", key_func=per_player_key)
async def get_global_leaderboard(
    request: Request,
    player: CurrentPlayer,  # any authenticated player — no league restriction
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[LeaderboardEntryOut]:
    """Cross-league standings: every active player on the platform, ranked globally.

    Re-ranks the full roster using the same merit cascade as the per-league
    endpoint.  Temporal metrics (today / round) are not included — the global
    view shows total points only.
    """
    return await _global_leaderboard_entries(db)
