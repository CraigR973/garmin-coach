"""scoring: grade knockout 90-min draws identically to group draws

The knockout-winner pick now owns "who goes through", so the 90-minute
score prediction should be scored the same as a group-stage prediction:
a 1-1 draw at 90 minutes is a valid result and earns the +3 result points.

Upgrade: redefine calculate_match_points without the is_knockout draw-void
branch so draws always score.
Downgrade: restore the original draw-voiding logic for knockout stages.

Revision ID: 021
Revises: 020
Create Date: 2026-06-02
"""

from typing import Sequence, Union

from alembic import op

revision: str = "021"
down_revision: Union[str, None] = "020"
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
            goals_pts    INT := 0;
            result_pts   INT := 0;
            exact_pts    INT := 0;
            total_pts    INT := 0;
            pred_total   INT;
            actual_total INT;
            pred_diff    INT;
            actual_diff  INT;
        BEGIN
            IF predicted_home IS NULL OR predicted_away IS NULL THEN
                RETURN jsonb_build_object(
                    'goals', 0,
                    'result', 0,
                    'exact', 0,
                    'total', 0,
                    'no_prediction', TRUE
                );
            END IF;

            IF actual_home IS NULL OR actual_away IS NULL THEN
                RETURN jsonb_build_object(
                    'goals', 0,
                    'result', 0,
                    'exact', 0,
                    'total', 0,
                    'no_prediction', FALSE
                );
            END IF;

            pred_total   := predicted_home + predicted_away;
            actual_total := actual_home + actual_away;
            pred_diff    := predicted_home - predicted_away;
            actual_diff  := actual_home - actual_away;

            IF pred_total = actual_total THEN
                goals_pts := 2;
            END IF;

            IF sign(pred_diff) = sign(actual_diff) THEN
                result_pts := 3;
            END IF;

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
            IF predicted_home IS NULL OR predicted_away IS NULL THEN
                RETURN jsonb_build_object(
                    'goals', 0,
                    'result', 0,
                    'exact', 0,
                    'total', 0,
                    'no_prediction', TRUE
                );
            END IF;

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

            IF pred_total = actual_total THEN
                goals_pts := 2;
            END IF;

            IF sign(pred_diff) = sign(actual_diff)
               AND NOT (is_knockout AND pred_diff = 0)
               AND NOT (is_knockout AND actual_diff = 0) THEN
                result_pts := 3;
            END IF;

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
