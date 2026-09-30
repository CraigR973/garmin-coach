"""Store what Claude read in each morning check-in's notes (Batch 297).

Revision ID: 034
Revises: 033
Create Date: 2026-09-30

The colour never read Mark's notes. A reader now takes one structured reading per
check-in version, before the verdict, and stores it here with its model and prompt
version: each flag present, absent or unclear, with his words, who it concerns and
when. A regenerated brief reuses the reading; a failed call is recorded and retried
in place. The flags can only add caution.

Additive: a new table, unique on the check-in and a SHA-256 of the notes it read.
RLS is enabled where Supabase's ``auth`` schema exists, the same guard every coach
table since 015 uses. Craig's go, 30 Sep 2026.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "034"
down_revision: str | None = "033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RLS_TABLES: tuple[str, ...] = ("check_in_readings",)


def upgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.create_table(
        "check_in_readings",
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
            "manual_entry_id",
            UUID(as_uuid=True),
            sa.ForeignKey("manual_entries.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("notes_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "reading", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("model_name", sa.String(80), nullable=True),
        sa.Column("prompt_version", sa.String(80), nullable=False),
        sa.Column("error", sa.String(300), nullable=True),
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
            "manual_entry_id", "notes_sha256", name="uq_check_in_readings_entry_notes"
        ),
        sa.CheckConstraint(
            "status IN ('read', 'failed')", name="ck_check_in_readings_status"
        ),
        schema="coach",
    )
    op.create_index(
        "ix_check_in_readings_user_created",
        "check_in_readings",
        ["user_id", "created_at"],
        schema="coach",
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT FROM information_schema.schemata WHERE schema_name = 'auth'
            ) THEN
                ALTER TABLE coach.check_in_readings ENABLE ROW LEVEL SECURITY;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.drop_index(
        "ix_check_in_readings_user_created",
        table_name="check_in_readings",
        schema="coach",
    )
    op.drop_table("check_in_readings", schema="coach")
