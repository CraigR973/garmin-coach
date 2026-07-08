"""Add the feedback table: rate & correct any AI summary (Batch 64).

Revision ID: 013
Revises: 012
Create Date: 2026-07-08

Every AI summary is one ``analyses`` row, so feedback is keyed to
``analysis_id`` (real referential integrity), one row per ``(user, analysis)``
via the unique constraint so the endpoint can upsert. ``correction_text`` is the
free-text payload that feeds the next read forward (Decision #137).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "013"
down_revision: str | None = "012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.create_table(
        "feedback",
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
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("rating", sa.String(40), nullable=False),
        sa.Column("correction_text", sa.Text(), nullable=True),
        sa.Column(
            "created_utc", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")
        ),
        sa.UniqueConstraint("user_id", "analysis_id", name="uq_feedback_user_analysis"),
        schema="coach",
    )
    op.create_index(
        "ix_feedback_user_analysis",
        "feedback",
        ["user_id", "analysis_id"],
        schema="coach",
    )


def downgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.drop_index(
        "ix_feedback_user_analysis",
        table_name="feedback",
        schema="coach",
        if_exists=True,
    )
    op.drop_table("feedback", schema="coach")
