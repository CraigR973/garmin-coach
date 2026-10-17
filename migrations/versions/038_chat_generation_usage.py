"""Store each coach answer's paid usage and wait (Batch 345).

Revision ID: 038
Revises: 037
Create Date: 2026-10-13

The new nullable JSONB column leaves historic turns untouched. It records provider
counts, duration and an estimate for each new assistant answer. RLS on the table
is unchanged.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "038"
down_revision: str | None = "037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "brief_messages",
        sa.Column("generation_usage", postgresql.JSONB(), nullable=True),
        schema="coach",
    )


def downgrade() -> None:
    op.drop_column("brief_messages", "generation_usage", schema="coach")
