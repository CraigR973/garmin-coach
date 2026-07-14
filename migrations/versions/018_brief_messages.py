"""Add brief_messages: follow-up chat on a brief (Batch 119).

Revision ID: 018
Revises: 017
Create Date: 2026-07-14

Every AI summary is one ``analyses`` row, so a follow-up conversation about a
brief is keyed to ``analysis_id`` (same referential pattern as ``feedback``).
Each row is one turn — ``role`` is ``user`` or ``assistant`` — so history reads
as an ordered thread via ``created_utc``. An assistant turn can optionally
carry ``proposed_planned_workout_id`` when the deterministic keyword check
(Batch 119 kickoff decision) flags the question as wanting a plan adjustment
and today's planned workout is deliverable; the frontend then offers a button
that calls the existing propose endpoint, never a new mutation path.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "018"
down_revision: str | None = "017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.create_table(
        "brief_messages",
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
            "analysis_id",
            UUID(as_uuid=True),
            sa.ForeignKey("analyses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "proposed_planned_workout_id",
            UUID(as_uuid=True),
            sa.ForeignKey("planned_workouts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_utc", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")
        ),
        schema="coach",
    )
    op.create_index(
        "ix_brief_messages_analysis_created",
        "brief_messages",
        ["analysis_id", "created_utc"],
        schema="coach",
    )


def downgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.drop_index(
        "ix_brief_messages_analysis_created",
        table_name="brief_messages",
        schema="coach",
        if_exists=True,
    )
    op.drop_table("brief_messages", schema="coach")
