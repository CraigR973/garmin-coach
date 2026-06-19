"""Player statistics computation service."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.match import Match
from src.models.prediction import KnockoutPrediction, Prediction, SpecialPrediction
from src.models.profile import Profile


@dataclass
class _PredRow:
    """Minimal prediction data needed for stats computation."""

    player_id: UUID
    points_awarded: int
    points_breakdown: dict[str, Any] | None
    submitted_at: datetime | None
    stage: str
    kickoff_utc: datetime | None


@dataclass
class PlayerStatsData:
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
    # U38 — Match / Knockout / Special points decomposition (moved from the
    # leaderboard) and the merit-cascade counts, surfaced on the player profile.
    # Defaulted so existing direct constructions stay valid.
    match_points: int = 0
    knockout_winner_points: int = 0
    special_points: int = 0
    exact_count: int = 0
    correct_result_count: int = 0
    correct_goals_count: int = 0
    specials_correct_count: int = 0
    ko_winner_correct_count: int = 0


def _compute_stats(
    player_id: UUID,
    player_name: str,
    group_rows: list[_PredRow],
    ko_rows: list[_PredRow],
    special_points: int = 0,
    specials_correct_count: int = 0,
) -> PlayerStatsData:
    # Accuracy / exact — group predictions only (they have score breakdowns)
    scored_group = [
        r for r in group_rows if r.points_breakdown and not r.points_breakdown.get("no_prediction")
    ]
    n_scored = len(scored_group)
    correct_outcome = sum(
        1 for r in scored_group if (r.points_breakdown or {}).get("result", 0) > 0
    )
    exact_score = sum(1 for r in scored_group if (r.points_breakdown or {}).get("exact", 0) > 0)
    goals_correct = sum(1 for r in scored_group if (r.points_breakdown or {}).get("goals", 0) > 0)
    accuracy_pct = (correct_outcome / n_scored * 100) if n_scored else 0.0
    exact_rate_pct = (exact_score / n_scored * 100) if n_scored else 0.0

    # Total points and avg across all settled predictions. total_points stays
    # scoreline + knockout (the avg-per-prediction denominator); tournament-long
    # specials are reported separately in the decomposition below.
    all_rows = group_rows + ko_rows
    total_settled = len(all_rows)
    match_points = sum(r.points_awarded for r in group_rows)
    knockout_winner_points = sum(r.points_awarded for r in ko_rows)
    total_points = match_points + knockout_winner_points
    avg_pts = (total_points / total_settled) if total_settled else 0.0
    # U38 merit-cascade counts — exact/result/goals from group breakdowns,
    # KO-winner from scoring knockout picks.
    ko_winner_correct_count = sum(1 for r in ko_rows if r.points_awarded > 0)

    # Best / worst round by stage
    round_points: dict[str, int] = defaultdict(int)
    for r in all_rows:
        round_points[r.stage] += r.points_awarded

    best_round: str | None = None
    best_round_points: int | None = None
    worst_round: str | None = None
    worst_round_points: int | None = None
    if round_points:
        best_stage = max(round_points, key=lambda s: round_points[s])
        worst_stage = min(round_points, key=lambda s: round_points[s])
        best_round = best_stage
        best_round_points = round_points[best_stage]
        worst_round = worst_stage
        worst_round_points = round_points[worst_stage]

    # Current streak — consecutive predictions with points > 0, most-recent first
    all_sorted = sorted(all_rows, key=lambda r: r.kickoff_utc or datetime.min, reverse=True)
    current_streak = 0
    for row in all_sorted:
        if row.points_awarded > 0:
            current_streak += 1
        else:
            break

    # Prediction timing — avg minutes before kickoff
    timing_mins: list[float] = []
    for r in all_rows:
        if r.submitted_at is not None and r.kickoff_utc is not None:
            delta = (r.kickoff_utc - r.submitted_at).total_seconds() / 60
            if delta >= 0:
                timing_mins.append(delta)
    avg_timing: float | None = sum(timing_mins) / len(timing_mins) if timing_mins else None

    return PlayerStatsData(
        player_id=str(player_id),
        player_name=player_name,
        total_predictions_settled=total_settled,
        accuracy_pct=round(accuracy_pct, 1),
        exact_rate_pct=round(exact_rate_pct, 1),
        avg_pts_per_prediction=round(avg_pts, 2),
        total_points=total_points,
        best_round=best_round,
        best_round_points=best_round_points,
        worst_round=worst_round,
        worst_round_points=worst_round_points,
        current_streak=current_streak,
        avg_prediction_timing_mins=round(avg_timing, 1) if avg_timing is not None else None,
        match_points=match_points,
        knockout_winner_points=knockout_winner_points,
        special_points=special_points,
        exact_count=exact_score,
        correct_result_count=correct_outcome,
        correct_goals_count=goals_correct,
        specials_correct_count=specials_correct_count,
        ko_winner_correct_count=ko_winner_correct_count,
    )


async def _fetch_group_rows(
    db: AsyncSession,
    player_id: UUID | None = None,
) -> list[_PredRow]:
    stmt = (
        select(Prediction, Match)
        .join(Match, Match.id == Prediction.match_id)
        .where(
            Prediction.deleted_at.is_(None),
            Prediction.points_awarded.is_not(None),
            Match.deleted_at.is_(None),
        )
        .order_by(Match.kickoff_utc.asc())
    )
    if player_id is not None:
        stmt = stmt.where(Prediction.player_id == player_id)

    result = await db.execute(stmt)
    rows = result.all()
    return [
        _PredRow(
            player_id=pred.player_id,
            points_awarded=pred.points_awarded or 0,
            points_breakdown=pred.points_breakdown,
            submitted_at=pred.submitted_at,
            stage=match.stage.value,
            kickoff_utc=match.kickoff_utc,
        )
        for pred, match in rows
    ]


async def _fetch_ko_rows(
    db: AsyncSession,
    player_id: UUID | None = None,
) -> list[_PredRow]:
    stmt = (
        select(KnockoutPrediction, Match)
        .join(Match, Match.id == KnockoutPrediction.match_id)
        .where(
            KnockoutPrediction.points_awarded.is_not(None),
            Match.deleted_at.is_(None),
        )
        .order_by(Match.kickoff_utc.asc())
    )
    if player_id is not None:
        stmt = stmt.where(KnockoutPrediction.player_id == player_id)

    result = await db.execute(stmt)
    rows = result.all()
    return [
        _PredRow(
            player_id=pred.player_id,
            points_awarded=pred.points_awarded or 0,
            points_breakdown=None,
            submitted_at=pred.submitted_at,
            stage=match.stage.value,
            kickoff_utc=match.kickoff_utc,
        )
        for pred, match in rows
    ]


async def _fetch_special_totals(
    db: AsyncSession,
    player_id: UUID | None = None,
) -> dict[UUID, tuple[int, int]]:
    """Per-player ``(special_points, specials_correct_count)`` from awarded specials.

    ``points_awarded > 0`` is a correct special pick; awarded-but-zero rows
    (a wrong pick that has been graded) count toward neither.
    """
    stmt = select(SpecialPrediction.player_id, SpecialPrediction.points_awarded).where(
        SpecialPrediction.points_awarded.is_not(None)
    )
    if player_id is not None:
        stmt = stmt.where(SpecialPrediction.player_id == player_id)
    rows = (await db.execute(stmt)).all()
    totals: dict[UUID, list[int]] = defaultdict(lambda: [0, 0])
    for pid, pts in rows:
        totals[pid][0] += pts
        if pts > 0:
            totals[pid][1] += 1
    return {pid: (v[0], v[1]) for pid, v in totals.items()}


async def get_player_stats(
    player_id: UUID,
    player_name: str,
    db: AsyncSession,
) -> PlayerStatsData:
    group_rows = await _fetch_group_rows(db, player_id)
    ko_rows = await _fetch_ko_rows(db, player_id)
    special_points, specials_correct = (await _fetch_special_totals(db, player_id)).get(
        player_id, (0, 0)
    )
    return _compute_stats(
        player_id,
        player_name,
        group_rows,
        ko_rows,
        special_points=special_points,
        specials_correct_count=specials_correct,
    )


async def get_league_stats(
    db: AsyncSession,
    player_ids: list[UUID] | None = None,
) -> list[PlayerStatsData]:
    """League-wide stats for active players.

    When ``player_ids`` is provided the player set is restricted to those ids
    (the active members of a league); predictions themselves stay global, so
    per-player stats are identical regardless of which league asks.
    """
    query = select(Profile).where(Profile.deleted_at.is_(None), Profile.is_active.is_(True))
    if player_ids is not None:
        query = query.where(Profile.id.in_(player_ids))
    players_result = await db.execute(query.order_by(Profile.display_name))
    players = players_result.scalars().all()

    if not players:
        return []

    all_group = await _fetch_group_rows(db)
    all_ko = await _fetch_ko_rows(db)
    special_totals = await _fetch_special_totals(db)

    group_by_player: dict[UUID, list[_PredRow]] = defaultdict(list)
    for row in all_group:
        group_by_player[row.player_id].append(row)

    ko_by_player: dict[UUID, list[_PredRow]] = defaultdict(list)
    for row in all_ko:
        ko_by_player[row.player_id].append(row)

    return [
        _compute_stats(
            p.id,
            p.display_name,
            group_by_player.get(p.id, []),
            ko_by_player.get(p.id, []),
            special_points=special_totals.get(p.id, (0, 0))[0],
            specials_correct_count=special_totals.get(p.id, (0, 0))[1],
        )
        for p in players
    ]
