"""Persist scheduled-job outcomes for operator monitoring (Batch 195).

Revision ID: 027
Revises: 026
Create Date: 2026-08-15

``job_runs`` is deliberately operator-only: it has no profile owner and no
authenticated-user policy. RLS is enabled when the Supabase ``auth`` schema is
present, so browser/client roles cannot read operational failure details while
the server owner can record them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "027"
down_revision: str | None = "026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RLS_TABLES: tuple[str, ...] = ("job_runs",)


def upgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.create_table(
        "job_runs",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("job_name", sa.String(64), nullable=False),
        sa.Column("scheduled_window_start_utc", sa.DateTime(), nullable=False),
        sa.Column("scheduled_window_end_utc", sa.DateTime(), nullable=False),
        sa.Column("started_at_utc", sa.DateTime(), nullable=False),
        sa.Column("finished_at_utc", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(128), nullable=True),
        sa.Column(
            "counters",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.CheckConstraint(
            "status IN ('succeeded', 'skipped', 'degraded', 'failed')",
            name="ck_job_runs_status",
        ),
        sa.CheckConstraint(
            "scheduled_window_end_utc > scheduled_window_start_utc",
            name="ck_job_runs_window",
        ),
        sa.CheckConstraint(
            "finished_at_utc >= started_at_utc",
            name="ck_job_runs_duration",
        ),
        schema="coach",
    )
    op.create_index(
        "ix_job_runs_job_started",
        "job_runs",
        ["job_name", "started_at_utc"],
        schema="coach",
    )
    op.create_index(
        "ix_job_runs_status_started",
        "job_runs",
        ["status", "started_at_utc"],
        schema="coach",
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT FROM information_schema.schemata WHERE schema_name = 'auth'
            ) THEN
                ALTER TABLE coach.job_runs ENABLE ROW LEVEL SECURITY;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.drop_index(
        "ix_job_runs_status_started",
        table_name="job_runs",
        schema="coach",
        if_exists=True,
    )
    op.drop_index(
        "ix_job_runs_job_started",
        table_name="job_runs",
        schema="coach",
        if_exists=True,
    )
    op.drop_table("job_runs", schema="coach")
