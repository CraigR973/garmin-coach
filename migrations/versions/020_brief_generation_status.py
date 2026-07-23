"""Add brief_generation_status: honest failure signal for a day's brief (Batch 141).

Revision ID: 020
Revises: 019
Create Date: 2026-07-21

Before this, a failed morning-brief generation left no trace: the check-in
background task caught the error and returned, so the daily-loop envelope simply
never gained a ``morningAnalysis`` and the app polled "Writing your brief"
forever (the 2026-07-21 Anthropic credit outage). This table records the state of
each day's generation — ``generating`` when the check-in schedules it, ``ready``
on success, ``failed`` (+ a classified ``reason`` such as ``billing``) on error —
so the envelope can surface a retryable failure instead of an endless spinner.

One row per ``(user_id, subject_date)``, upserted in place. RLS is ENABLEd in the
same guarded style as migration 015/019 (no policies — the backend connects as the
owning role and bypasses RLS; guarded by the ``auth`` schema check so it's a no-op
on plain Postgres/CI), keeping ``test_every_coach_model_table_is_under_rls`` green.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "020"
down_revision: str | None = "019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The one coach table this migration adds under RLS (same shape as 015/019 so
# tests/test_coach_rls_migration.py can assert full model coverage).
RLS_TABLES: tuple[str, ...] = ("brief_generation_status",)


def upgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.create_table(
        "brief_generation_status",
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
        sa.Column("subject_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("reason", sa.String(40), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")
        ),
        sa.UniqueConstraint(
            "user_id", "subject_date", name="uq_brief_generation_status_user_date"
        ),
        schema="coach",
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT FROM information_schema.schemata WHERE schema_name = 'auth'
            ) THEN
                ALTER TABLE coach.brief_generation_status ENABLE ROW LEVEL SECURITY;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.drop_table("brief_generation_status", schema="coach")
