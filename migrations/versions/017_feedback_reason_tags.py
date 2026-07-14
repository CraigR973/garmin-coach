"""Add feedback.reason_tags: one-tap "what's off" reasons (Batch 118).

Revision ID: 017
Revises: 016
Create Date: 2026-07-14

The existing rating axis says how off a summary/suggestion is; this adds a
small kind-scoped set of one-tap reason tags for *what* is off, stored
alongside the existing free-text ``correction_text`` (Decision assigned at
Batch 118 kickoff). Nullable-free JSONB array, defaulting to ``[]`` so every
existing row reads as "no reasons given" rather than null.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "017"
down_revision: str | None = "016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.add_column(
        "feedback",
        sa.Column(
            "reason_tags", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        schema="coach",
    )


def downgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.drop_column("feedback", "reason_tags", schema="coach")
