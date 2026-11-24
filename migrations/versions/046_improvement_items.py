"""The self-improving loop's private queue (Batch 390).

Revision ID: 046
Revises: 045
Create Date: 2026-11-24

One row per finding, from any source: an operator alert, a degraded or failed job, a
rating's written correction, a coach pass-on, a figure dispute, and later the daily
reviewer's findings and Mark's suggestions (G14, Decision #507). A stable fingerprint
folds repeats into one open row (a partial unique index: a closed row's fingerprint may
open a new one). ``words`` holds any free text (Mark's words, the coach's summary) and
is wiped 90 days after the row closes; its codes and dates stay. RLS is enabled where
Supabase's ``auth`` schema exists, with no policy: only the service reads it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "046"
down_revision: str | None = "045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RLS_TABLES: tuple[str, ...] = ("improvement_items",)


def upgrade() -> None:
    op.create_table(
        "improvement_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("coach.profiles.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("fingerprint", sa.String(200), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="new"),
        sa.Column("lane", sa.String(16), nullable=True),
        sa.Column("summary", sa.String(240), nullable=False),
        sa.Column(
            "detail",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("words", postgresql.JSONB(), nullable=True),
        sa.Column("proposal", postgresql.JSONB(), nullable=True),
        sa.Column(
            "source_refs",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("occurrences", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("first_seen_utc", sa.DateTime(), nullable=False),
        sa.Column("last_seen_utc", sa.DateTime(), nullable=False),
        sa.Column("updated_utc", sa.DateTime(), nullable=False),
        sa.Column("closed_utc", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "source IN ('alert', 'job_outcome', 'correction', 'pass_on', 'dispute', "
            "'review', 'suggestion')",
            name="ck_improvement_items_source",
        ),
        sa.CheckConstraint(
            "state IN ('new', 'triaged', 'proposed', 'with_mark', 'approved', 'building', "
            "'shipped', 'verified', 'undone', 'escalated', 'dismissed')",
            name="ck_improvement_items_state",
        ),
        sa.CheckConstraint(
            "lane IS NULL OR lane IN ('fix_alone', 'mark', 'evidence', 'craig')",
            name="ck_improvement_items_lane",
        ),
        sa.CheckConstraint("occurrences >= 1", name="ck_improvement_items_occurrences"),
        schema="coach",
    )
    op.create_index(
        "uq_improvement_items_open_fingerprint",
        "improvement_items",
        ["fingerprint"],
        unique=True,
        schema="coach",
        postgresql_where=sa.text("closed_utc IS NULL"),
    )
    op.create_index(
        "ix_improvement_items_state_seen",
        "improvement_items",
        ["state", "last_seen_utc"],
        schema="coach",
    )
    op.create_index(
        "ix_improvement_items_closed",
        "improvement_items",
        ["closed_utc"],
        schema="coach",
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT FROM information_schema.schemata WHERE schema_name = 'auth'
            ) THEN
                ALTER TABLE coach.improvement_items ENABLE ROW LEVEL SECURITY;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_improvement_items_closed", table_name="improvement_items", schema="coach"
    )
    op.drop_index(
        "ix_improvement_items_state_seen",
        table_name="improvement_items",
        schema="coach",
    )
    op.drop_index(
        "uq_improvement_items_open_fingerprint",
        table_name="improvement_items",
        schema="coach",
    )
    op.drop_table("improvement_items", schema="coach")
