"""scoring function: calculate_match_points

Adds the Postgres function `calculate_match_points` used by the scoring
trigger (phase 1.6) and any application code that needs to compute the
JSONB points breakdown for a single (prediction, result) pair.

Group stage rules:
  - correct combined goals (predicted total == actual total)  -> 2 pts
  - correct W/D/L result (sign of predicted == sign of actual) -> 3 pts
  - exact scoreline                                            -> 5 pts
  - max 10 pts per match

Knockout score predictions:
  - same point structure, but the result is always W/L (no draws).
  - if either the predicted or the actual 90-minute score is a draw,
    no result points are awarded (since draws are not a valid knockout
    outcome — the match is decided in extra time / penalties).
  - score predictions are still scored on the 90-minute score, even when
    the match itself is decided on penalties.

NULL predictions return:
  {"goals": 0, "result": 0, "exact": 0, "total": 0, "no_prediction": true}

Revision ID: 004
Revises: 003
Create Date: 2026-05-08

"""

from typing import Sequence, Union

from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION calculate_match_points(
            predicted_home INT,
            predicted_away INT,
            actual_home    INT,
            actual_away    INT,
            stage          tournament_stage
        ) RETURNS JSONB
        LANGUAGE plpgsql
        IMMUTABLE
        AS $func$
        DECLARE
            goals_pts    INT     := 0;
            result_pts   INT     := 0;
            exact_pts    INT     := 0;
            total_pts    INT     := 0;
            is_knockout  BOOLEAN;
            pred_total   INT;
            actual_total INT;
            pred_diff    INT;
            actual_diff  INT;
        BEGIN
            -- No prediction submitted: zero points, flagged.
            IF predicted_home IS NULL OR predicted_away IS NULL THEN
                RETURN jsonb_build_object(
                    'goals', 0,
                    'result', 0,
                    'exact', 0,
                    'total', 0,
                    'no_prediction', TRUE
                );
            END IF;

            -- No actual result yet: scoring is not applicable. Return zero
            -- with no_prediction=false so callers can distinguish "scored to
            -- zero" from "no prediction".
            IF actual_home IS NULL OR actual_away IS NULL THEN
                RETURN jsonb_build_object(
                    'goals', 0,
                    'result', 0,
                    'exact', 0,
                    'total', 0,
                    'no_prediction', FALSE
                );
            END IF;

            is_knockout  := stage <> 'group';
            pred_total   := predicted_home + predicted_away;
            actual_total := actual_home + actual_away;
            pred_diff    := predicted_home - predicted_away;
            actual_diff  := actual_home - actual_away;

            -- Goals: correct combined goal total.
            IF pred_total = actual_total THEN
                goals_pts := 2;
            END IF;

            -- Result: correct W/D/L. Knockout draws (either side) never count.
            IF sign(pred_diff) = sign(actual_diff)
               AND NOT (is_knockout AND pred_diff = 0)
               AND NOT (is_knockout AND actual_diff = 0) THEN
                result_pts := 3;
            END IF;

            -- Exact scoreline.
            IF predicted_home = actual_home AND predicted_away = actual_away THEN
                exact_pts := 5;
            END IF;

            total_pts := goals_pts + result_pts + exact_pts;

            RETURN jsonb_build_object(
                'goals', goals_pts,
                'result', result_pts,
                'exact', exact_pts,
                'total', total_pts,
                'no_prediction', FALSE
            );
        END;
        $func$;
    """)


def downgrade() -> None:
    op.execute(
        "DROP FUNCTION IF EXISTS calculate_match_points(INT, INT, INT, INT, tournament_stage)"
    )
