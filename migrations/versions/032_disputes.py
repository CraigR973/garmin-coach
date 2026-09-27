"""Record Mark's disputes: a contested figure, or a dissent from a verdict (Batch 274).

Revision ID: 032
Revises: 031
Create Date: 2026-09-27

Until now Mark's only remedy for a figure he believed wrong was to argue with a
coach that agreed with him and could change nothing, and the argument evaporated
into chat. A contest now records the figure, the working the app showed for it
(Batch 273's provenance, snapshotted from the stored read), his reason and the
date; a dissent records the day's verdict as it stood and his reason.

Additive: a new table, read by nothing that decides anything. RLS is enabled where
Supabase's ``auth`` schema exists, the same guard every coach table since 015 uses.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "032"
down_revision: str | None = "031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RLS_TABLES: tuple[str, ...] = ("disputes",)


def upgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.create_table(
        "disputes",
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
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column(
            "analysis_id",
            UUID(as_uuid=True),
            sa.ForeignKey("analyses.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("subject_date", sa.Date(), nullable=False),
        sa.Column("figure", sa.String(120), nullable=True),
        sa.Column(
            "snapshot", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("reason", sa.Text(), nullable=False),
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
        schema="coach",
    )
    op.create_index(
        "ix_disputes_user_subject_date",
        "disputes",
        ["user_id", "subject_date"],
        schema="coach",
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT FROM information_schema.schemata WHERE schema_name = 'auth'
            ) THEN
                ALTER TABLE coach.disputes ENABLE ROW LEVEL SECURITY;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.drop_index(
        "ix_disputes_user_subject_date", table_name="disputes", schema="coach"
    )
    op.drop_table("disputes", schema="coach")
