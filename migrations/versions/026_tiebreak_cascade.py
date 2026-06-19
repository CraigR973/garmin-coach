"""U38: merit-cascade tiebreaking on the leaderboard.

Replaces shared-rank-on-points with a strict merit cascade so two players
level on ``total_points`` are separated by, in order:

    total_points
    → exact scores
    → correct results
    → correct goals
    → specials correct
    → knockout-winner picks correct
    → (admin) manual tiebreak order

Three things change here:

* ``leaderboard_snapshots`` gains five per-player tiebreak counts
  (``exact_count``, ``correct_result_count``, ``correct_goals_count``,
  ``specials_correct_count``, ``ko_winner_correct_count``). They are
  computed alongside the point totals so the stored ``rank`` and the
  counts that justify it are written atomically.
* ``leaderboard_tiebreak_overrides`` is a new, normally-empty table. When
  two players genuinely tie on *every* merit axis (essentially never), the
  cascade leaves them sharing a rank — flagged for admin settlement. The
  admin sets a ``manual_order`` here to break it without any arbitrary
  (timing / alphabetical / random) rule. It is the final ORDER BY key, so
  it only ever decides an otherwise-exact tie.
* ``matches_score_results`` is rewritten to compute the counts and rank by
  the full cascade. ``RANK()`` now ties two players only when they match on
  all six merit axes *and* have no distinguishing override — so a shared
  rank is exactly the all-axis tie.

The Python twin ``src.services.leaderboard.recompute_leaderboard_snapshot``
mirrors this body for the non-trigger paths (specials award, match cancel,
admin tiebreak settle). Keep the two in sync.

Downgrade restores the migration-012 trigger (points-only RANK, no counts,
no override join) and drops the new columns / table.

Revision ID: 026
Revises: 025
Create Date: 2026-06-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "026"
down_revision: Union[str, None] = "025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Shared SQL fragment: the per-player totals + tiebreak counts subquery.
# Identical text lives in src/services/leaderboard.py; keep them in sync.
_PLAYER_TOTALS = """
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
"""


def upgrade() -> None:
    # --- 1. Tiebreak count columns on leaderboard_snapshots -----------------
    for col in (
        "exact_count",
        "correct_result_count",
        "correct_goals_count",
        "specials_correct_count",
        "ko_winner_correct_count",
    ):
        op.add_column(
            "leaderboard_snapshots",
            sa.Column(col, sa.Integer(), nullable=False, server_default="0"),
        )

    # --- 2. Admin manual-order override table (normally empty) --------------
    op.create_table(
        "leaderboard_tiebreak_overrides",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("league_id", UUID(as_uuid=True), nullable=False),
        sa.Column("player_id", UUID(as_uuid=True), nullable=False),
        # Lower sorts higher (rank 1 first). Only decides an all-axis tie.
        sa.Column("manual_order", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=False),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["league_id"], ["leagues.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["player_id"], ["profiles.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "league_id", "player_id", name="uq_tiebreak_override_league_player"
        ),
    )

    # --- 3. Rewrite the scoring trigger to rank by the merit cascade --------
    op.execute(f"""
        CREATE OR REPLACE FUNCTION matches_score_results()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        AS $func$
        DECLARE
            v_winner_id  UUID;
            v_round_pts  INT;
        BEGIN
            -- 1. Score predictions (group + knockout matches).
            UPDATE predictions p
            SET points_breakdown = calculate_match_points(
                    p.predicted_home, p.predicted_away,
                    NEW.actual_home_score, NEW.actual_away_score,
                    NEW.stage
                ),
                points_awarded = (calculate_match_points(
                    p.predicted_home, p.predicted_away,
                    NEW.actual_home_score, NEW.actual_away_score,
                    NEW.stage
                )->>'total')::int
            WHERE p.match_id = NEW.id
              AND p.deleted_at IS NULL;

            -- 2. Knockout winner predictions: only for knockout-stage matches.
            IF NEW.stage <> 'group' THEN
                IF NEW.actual_home_score > NEW.actual_away_score THEN
                    v_winner_id := NEW.home_team_id;
                ELSIF NEW.actual_home_score < NEW.actual_away_score THEN
                    v_winner_id := NEW.away_team_id;
                ELSE
                    v_winner_id := NEW.penalty_winner_id;
                END IF;

                v_round_pts := CASE NEW.stage
                    WHEN 'r32'         THEN 5
                    WHEN 'r16'         THEN 10
                    WHEN 'qf'          THEN 15
                    WHEN 'sf'          THEN 20
                    WHEN 'third_place' THEN 10
                    WHEN 'final'       THEN 25
                    ELSE 0
                END;

                UPDATE knockout_predictions kp
                SET points_awarded = CASE
                        WHEN v_winner_id IS NOT NULL
                             AND kp.predicted_winner_id = v_winner_id
                        THEN v_round_pts
                        ELSE 0
                    END
                WHERE kp.match_id = NEW.id;
            END IF;

            -- 3. Leaderboard snapshots: fan out per (player, active league),
            --    ranked by the U38 merit cascade. RANK() ties two players only
            --    when they match on every merit axis AND have no distinguishing
            --    manual override — so a shared rank IS the all-axis tie.
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
                NEW.id
            FROM league_memberships lm
            JOIN ({_PLAYER_TOTALS}) AS player_totals
                ON player_totals.player_id = lm.player_id
            LEFT JOIN leaderboard_tiebreak_overrides tbo
                ON tbo.league_id = lm.league_id
               AND tbo.player_id = lm.player_id
            WHERE lm.deleted_at IS NULL;

            RETURN NULL;
        END;
        $func$;
    """)


def downgrade() -> None:
    # --- Restore the migration-012 trigger (points-only RANK, no counts) ----
    op.execute("""
        CREATE OR REPLACE FUNCTION matches_score_results()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        AS $func$
        DECLARE
            v_winner_id  UUID;
            v_round_pts  INT;
        BEGIN
            UPDATE predictions p
            SET points_breakdown = calculate_match_points(
                    p.predicted_home, p.predicted_away,
                    NEW.actual_home_score, NEW.actual_away_score,
                    NEW.stage
                ),
                points_awarded = (calculate_match_points(
                    p.predicted_home, p.predicted_away,
                    NEW.actual_home_score, NEW.actual_away_score,
                    NEW.stage
                )->>'total')::int
            WHERE p.match_id = NEW.id
              AND p.deleted_at IS NULL;

            IF NEW.stage <> 'group' THEN
                IF NEW.actual_home_score > NEW.actual_away_score THEN
                    v_winner_id := NEW.home_team_id;
                ELSIF NEW.actual_home_score < NEW.actual_away_score THEN
                    v_winner_id := NEW.away_team_id;
                ELSE
                    v_winner_id := NEW.penalty_winner_id;
                END IF;

                v_round_pts := CASE NEW.stage
                    WHEN 'r32'         THEN 5
                    WHEN 'r16'         THEN 10
                    WHEN 'qf'          THEN 15
                    WHEN 'sf'          THEN 20
                    WHEN 'third_place' THEN 10
                    WHEN 'final'       THEN 25
                    ELSE 0
                END;

                UPDATE knockout_predictions kp
                SET points_awarded = CASE
                        WHEN v_winner_id IS NOT NULL
                             AND kp.predicted_winner_id = v_winner_id
                        THEN v_round_pts
                        ELSE 0
                    END
                WHERE kp.match_id = NEW.id;
            END IF;

            INSERT INTO leaderboard_snapshots (
                id, player_id, league_id, total_points, match_points,
                knockout_winner_points, special_points, rank,
                snapshot_at, triggered_by_match_id
            )
            SELECT
                gen_random_uuid(),
                lm.player_id,
                lm.league_id,
                player_totals.total_points,
                player_totals.match_points,
                player_totals.knockout_winner_points,
                player_totals.special_points,
                RANK() OVER (
                    PARTITION BY lm.league_id
                    ORDER BY player_totals.total_points DESC
                ),
                now(),
                NEW.id
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
                    ), 0) AS total_points
                FROM profiles pr
                WHERE pr.deleted_at IS NULL
            ) AS player_totals ON player_totals.player_id = lm.player_id
            WHERE lm.deleted_at IS NULL;

            RETURN NULL;
        END;
        $func$;
    """)

    op.drop_table("leaderboard_tiebreak_overrides")
    for col in (
        "ko_winner_correct_count",
        "specials_correct_count",
        "correct_goals_count",
        "correct_result_count",
        "exact_count",
    ):
        op.drop_column("leaderboard_snapshots", col)
