"""Add activity-scoped post-session read generation status (Batch 159).

Revision ID: 022
Revises: 021
Create Date: 2026-07-26

The morning brief status table is deliberately one row per user/date and cannot
represent mixed days safely. This table records one status per synced activity,
optionally linked to the planned workout it completed, so the Week view can tell
absent, generating, and failed reads apart without conflating same-day sessions.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "022"
down_revision: str | None = "021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RLS_TABLES: tuple[str, ...] = ("post_activity_generation_status",)


def upgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.create_table(
        "post_activity_generation_status",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "activity_id",
            UUID(as_uuid=True),
            sa.ForeignKey("activities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "planned_workout_id",
            UUID(as_uuid=True),
            sa.ForeignKey("planned_workouts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("subject_date", sa.Date(), nullable=False),
        sa.Column("analysis_type", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("reason", sa.String(40), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint(
            "user_id",
            "activity_id",
            name="uq_post_activity_generation_status_user_activity",
        ),
        schema="coach",
    )
    op.create_index(
        "ix_post_activity_generation_status_planned_workout",
        "post_activity_generation_status",
        ["planned_workout_id"],
        schema="coach",
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT FROM information_schema.schemata WHERE schema_name = 'auth'
            ) THEN
                ALTER TABLE coach.post_activity_generation_status
                    ENABLE ROW LEVEL SECURITY;
            END IF;
        END $$;
        """
    )
    # Link already-generated reads to their active planned session so the Week
    # view benefits immediately after deploy. Rank distinct activities, not
    # analysis rows: prompt/check-in regeneration can leave several historical
    # analyses for one activity and all versions belong to the same workout.
    op.execute(
        """
        WITH latest_post_activities AS (
            SELECT DISTINCT ON (a.user_id, a.activity_id)
                a.user_id,
                a.activity_id,
                a.subject_date,
                CASE a.analysis_type
                    WHEN 'post_workout' THEN 'ride'
                    WHEN 'post_strength' THEN 'strength'
                    WHEN 'post_flexibility' THEN 'flexibility'
                    WHEN 'post_walk' THEN 'walk'
                END AS activity_kind
            FROM coach.analyses AS a
            WHERE a.activity_id IS NOT NULL
              AND a.analysis_type IN (
                  'post_workout',
                  'post_strength',
                  'post_flexibility',
                  'post_walk'
              )
            ORDER BY
                a.user_id,
                a.activity_id,
                a.generated_at_utc DESC,
                a.id DESC
        ),
        ranked_activities AS (
            SELECT
                p.*,
                row_number() OVER (
                    PARTITION BY p.user_id, p.subject_date, p.activity_kind
                    ORDER BY p.activity_id
                ) AS session_number
            FROM latest_post_activities AS p
        ),
        ranked_workouts AS (
            SELECT
                w.id AS workout_id,
                w.user_id,
                w.workout_date,
                CASE
                    WHEN w.workout_type LIKE 'bike_%' THEN 'ride'
                    WHEN w.workout_type LIKE 'strength_%' THEN 'strength'
                    WHEN w.workout_type = 'mobility' THEN 'flexibility'
                    WHEN w.workout_type IN ('walk', 'walking', 'walk_recovery')
                      OR w.workout_type LIKE 'walk_%' THEN 'walk'
                END AS workout_kind,
                row_number() OVER (
                    PARTITION BY
                        w.user_id,
                        w.workout_date,
                        CASE
                            WHEN w.workout_type LIKE 'bike_%' THEN 'ride'
                            WHEN w.workout_type LIKE 'strength_%' THEN 'strength'
                            WHEN w.workout_type = 'mobility' THEN 'flexibility'
                            WHEN w.workout_type IN ('walk', 'walking', 'walk_recovery')
                              OR w.workout_type LIKE 'walk_%' THEN 'walk'
                        END
                    ORDER BY w.version DESC, w.id
                ) AS session_number
            FROM coach.planned_workouts AS w
            WHERE w.is_active IS TRUE
        ),
        links AS (
            SELECT
                a.user_id,
                a.activity_id,
                w.workout_id
            FROM ranked_activities AS a
            JOIN ranked_workouts AS w
              ON w.user_id = a.user_id
             AND w.workout_date = a.subject_date
             AND w.workout_kind = a.activity_kind
             AND w.session_number = a.session_number
        ),
        linked_analyses AS (
            UPDATE coach.analyses AS a
            SET planned_workout_id = links.workout_id
            FROM links
            WHERE a.user_id = links.user_id
              AND a.activity_id = links.activity_id
              AND a.planned_workout_id IS NULL
              AND a.analysis_type IN (
                  'post_workout',
                  'post_strength',
                  'post_flexibility',
                  'post_walk'
              )
            RETURNING links.workout_id
        )
        UPDATE coach.planned_workouts AS w
        SET status = 'completed'
        WHERE w.id IN (SELECT workout_id FROM linked_analyses)
        """
    )


def downgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.drop_index(
        "ix_post_activity_generation_status_planned_workout",
        table_name="post_activity_generation_status",
        schema="coach",
        if_exists=True,
    )
    op.drop_table("post_activity_generation_status", schema="coach")
