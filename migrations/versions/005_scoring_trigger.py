"""scoring trigger: cascade match results into predictions, knockout
predictions, and leaderboard snapshots — atomically.

Two triggers fire when ``actual_home_score`` / ``actual_away_score`` on
``matches`` transition from NULL to a value (i.e. a result is being
entered for the first time):

  1. BEFORE UPDATE — ``matches_set_result_entered_at``: stamps
     ``matches.result_entered_at`` with now() so the row update happens
     in a single statement.
  2. AFTER UPDATE — ``matches_score_results``:
       a) updates every ``predictions`` row for the match with
          ``points_awarded`` and the JSONB ``points_breakdown`` produced
          by ``calculate_match_points``;
       b) for knockout-stage matches, computes the actual winner (90-min
          winner, falling back to ``penalty_winner_id`` for 90-min draws)
          and writes ``knockout_predictions.points_awarded`` based on the
          per-round table;
       c) inserts a fresh row into ``leaderboard_snapshots`` for every
          active player (``profiles.deleted_at IS NULL``) with their
          updated total / match / knockout / special points and current
          rank, all stamped ``triggered_by_match_id = NEW.id``.

All three sub-steps run inside the trigger's own transaction (the same
transaction as the originating ``UPDATE matches``), so concurrent reads
never observe a partially-scored result.

Per-round knockout points (matches the architecture spec):
    r32 = 5, r16 = 10, qf = 15, sf = 20, third_place = 10, final = 25.
The ``winner`` stage is excluded — it is a synthetic stage used only on
the ``teams`` table to mark elimination, never on a real match.

Revision ID: 005
Revises: 004
Create Date: 2026-05-08

"""

from typing import Sequence, Union

from alembic import op

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # BEFORE UPDATE: stamp result_entered_at on the same row update.
    op.execute("""
        CREATE OR REPLACE FUNCTION matches_set_result_entered_at()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        AS $func$
        BEGIN
            NEW.result_entered_at := now();
            RETURN NEW;
        END;
        $func$;
    """)
    op.execute("DROP TRIGGER IF EXISTS matches_set_result_entered_at ON matches")
    op.execute("""
        CREATE TRIGGER matches_set_result_entered_at
        BEFORE UPDATE OF actual_home_score, actual_away_score ON matches
        FOR EACH ROW
        WHEN (
            (OLD.actual_home_score IS NULL OR OLD.actual_away_score IS NULL)
            AND NEW.actual_home_score IS NOT NULL
            AND NEW.actual_away_score IS NOT NULL
        )
        EXECUTE FUNCTION matches_set_result_entered_at();
    """)

    # AFTER UPDATE: cascade scoring into predictions, knockout predictions,
    # and leaderboard snapshots.
    op.execute("""
        CREATE OR REPLACE FUNCTION matches_score_results()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        AS $func$
        DECLARE
            v_winner_id  UUID;
            v_round_pts  INT;
        BEGIN
            -- 1. Score predictions (group AND knockout matches).
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
                    -- 90-min draw: penalty shootout decides the winner.
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

            -- 3. Leaderboard snapshot for every active player.
            INSERT INTO leaderboard_snapshots (
                id, player_id, total_points, match_points,
                knockout_winner_points, special_points, rank,
                snapshot_at, triggered_by_match_id
            )
            SELECT
                gen_random_uuid(),
                player_totals.player_id,
                player_totals.total_points,
                player_totals.match_points,
                player_totals.knockout_winner_points,
                player_totals.special_points,
                RANK() OVER (ORDER BY player_totals.total_points DESC),
                now(),
                NEW.id
            FROM (
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
            ) AS player_totals;

            RETURN NULL;
        END;
        $func$;
    """)
    op.execute("DROP TRIGGER IF EXISTS matches_score_results ON matches")
    op.execute("""
        CREATE TRIGGER matches_score_results
        AFTER UPDATE OF actual_home_score, actual_away_score ON matches
        FOR EACH ROW
        WHEN (
            (OLD.actual_home_score IS NULL OR OLD.actual_away_score IS NULL)
            AND NEW.actual_home_score IS NOT NULL
            AND NEW.actual_away_score IS NOT NULL
        )
        EXECUTE FUNCTION matches_score_results();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS matches_score_results ON matches")
    op.execute("DROP TRIGGER IF EXISTS matches_set_result_entered_at ON matches")
    op.execute("DROP FUNCTION IF EXISTS matches_score_results()")
    op.execute("DROP FUNCTION IF EXISTS matches_set_result_entered_at()")
