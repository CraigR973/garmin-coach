"""Leaderboard snapshot helper for non-trigger paths.

The Postgres ``matches_score_results`` trigger handles snapshot inserts
for the happy path (a match result is entered or overridden). A handful
of other paths also change point totals (or the rank that flows from
them) without updating a match's ``actual_*_score`` columns:

* :func:`src.routers.specials.award_specials` — awarding the special
  predictions bulk-writes ``special_predictions.points_awarded``. Without
  a snapshot refresh here the leaderboard is forever stale once the final
  is scored.
* :func:`src.routers.admin.cancel_match` — cancelling a match zeroes
  ``points_awarded`` on the related ``predictions`` /
  ``knockout_predictions`` rows. The trigger doesn't fire (the score
  columns aren't changed), so we recompute the snapshot ourselves.
* :func:`src.routers.admin.set_tiebreak_override` — settling a genuine
  all-axis tie writes a ``leaderboard_tiebreak_overrides`` row; the new
  manual order only takes effect once fresh snapshots are written.

This helper mirrors the per-league fan-out + U38 merit cascade from
``migrations/versions/026_tiebreak_cascade.py`` so the trigger path and
the non-trigger paths produce identical snapshot rows (same point totals,
same tiebreak counts, same rank). Keep the two SQL bodies in sync if
scoring sources, tiebreak axes, or league semantics ever change.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def recompute_leaderboard_snapshot(
    session: AsyncSession,
    triggered_by_match_id: uuid.UUID | None,
) -> None:
    """Insert one fresh ``leaderboard_snapshots`` row per active league membership.

    Reads the current sums of ``predictions.points_awarded``,
    ``knockout_predictions.points_awarded``, and
    ``special_predictions.points_awarded`` per profile — plus the five
    U38 tiebreak counts — the same shape the trigger uses, and ranks
    players within each league by the merit cascade::

        total_points DESC → exact_count DESC → correct_result_count DESC
        → correct_goals_count DESC → specials_correct_count DESC
        → ko_winner_correct_count DESC → manual tiebreak order ASC

    The final key, ``leaderboard_tiebreak_overrides.manual_order``, is
    normally absent (NULLS LAST), so it only decides a genuine all-axis
    tie an admin has explicitly settled. ``RANK()`` therefore ties two
    players only when they match on every merit axis with no override —
    exactly the state flagged for admin settlement.

    Pending session writes are flushed first so the helper sees the
    caller's in-memory mutations (e.g. ``award_specials`` mutating
    ``points_awarded`` on its loaded rows) before computing sums.

    Callers are expected to commit afterwards; this helper does not
    commit on its own.
    """
    await session.flush()
    await session.execute(
        text("""
            INSERT INTO leaderboard_snapshots (
                id, player_id, league_id, total_points, match_points,
                knockout_winner_points, special_points,
                exact_count, correct_result_count, correct_goals_count,
                specials_correct_count, ko_winner_correct_count,
                rank, snapshot_at, triggered_by_match_id
            )
            SELECT
                gen_random_uuid(),
                lm.player_id,
                lm.league_id,
                player_totals.total_points,
                player_totals.match_points,
                player_totals.knockout_winner_points,
                player_totals.special_points,
                player_totals.exact_count,
                player_totals.correct_result_count,
                player_totals.correct_goals_count,
                player_totals.specials_correct_count,
                player_totals.ko_winner_correct_count,
                -- RANK (not DENSE_RANK): tied players get the same rank and the
                -- next rank skips (e.g. two players tied 2nd → next is 4th). A
                -- tie now means equal on every merit axis (U38) — the cascade
                -- below resolves everything short of a true all-axis tie.
                RANK() OVER (
                    PARTITION BY lm.league_id
                    ORDER BY
                        player_totals.total_points DESC,
                        player_totals.exact_count DESC,
                        player_totals.correct_result_count DESC,
                        player_totals.correct_goals_count DESC,
                        player_totals.specials_correct_count DESC,
                        player_totals.ko_winner_correct_count DESC,
                        tbo.manual_order ASC NULLS LAST
                ),
                now(),
                :triggered_by_match_id
            FROM league_memberships lm
            JOIN (
                SELECT
                    pr.id AS player_id,
                    COALESCE((
                        SELECT SUM(points_awarded)::int FROM predictions
                        WHERE player_id = pr.id AND deleted_at IS NULL
                    ), 0) AS match_points,
                    COALESCE((
                        SELECT SUM(points_awarded)::int FROM knockout_predictions
                        WHERE player_id = pr.id
                    ), 0) AS knockout_winner_points,
                    COALESCE((
                        SELECT SUM(points_awarded)::int FROM special_predictions
                        WHERE player_id = pr.id
                    ), 0) AS special_points,
                    COALESCE((
                        SELECT SUM(points_awarded)::int FROM predictions
                        WHERE player_id = pr.id AND deleted_at IS NULL
                    ), 0)
                    + COALESCE((
                        SELECT SUM(points_awarded)::int FROM knockout_predictions
                        WHERE player_id = pr.id
                    ), 0)
                    + COALESCE((
                        SELECT SUM(points_awarded)::int FROM special_predictions
                        WHERE player_id = pr.id
                    ), 0) AS total_points,
                    COALESCE((
                        SELECT COUNT(*)::int FROM predictions
                        WHERE player_id = pr.id AND deleted_at IS NULL
                          AND (points_breakdown->>'exact')::int > 0
                    ), 0) AS exact_count,
                    COALESCE((
                        SELECT COUNT(*)::int FROM predictions
                        WHERE player_id = pr.id AND deleted_at IS NULL
                          AND (points_breakdown->>'result')::int > 0
                    ), 0) AS correct_result_count,
                    COALESCE((
                        SELECT COUNT(*)::int FROM predictions
                        WHERE player_id = pr.id AND deleted_at IS NULL
                          AND (points_breakdown->>'goals')::int > 0
                    ), 0) AS correct_goals_count,
                    COALESCE((
                        SELECT COUNT(*)::int FROM special_predictions
                        WHERE player_id = pr.id AND points_awarded > 0
                    ), 0) AS specials_correct_count,
                    COALESCE((
                        SELECT COUNT(*)::int FROM knockout_predictions
                        WHERE player_id = pr.id AND points_awarded > 0
                    ), 0) AS ko_winner_correct_count
                FROM profiles pr
                WHERE pr.deleted_at IS NULL
            ) AS player_totals ON player_totals.player_id = lm.player_id
            LEFT JOIN leaderboard_tiebreak_overrides tbo
                ON tbo.league_id = lm.league_id
               AND tbo.player_id = lm.player_id
            WHERE lm.deleted_at IS NULL
        """),
        {"triggered_by_match_id": triggered_by_match_id},
    )
