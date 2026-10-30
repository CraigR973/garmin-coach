"""Keep what each notes reading cost (Batch 341).

Revision ID: 041
Revises: 040
Create Date: 2026-10-29

One nullable JSONB column on ``check_in_readings``: the provider's token usage for the
call that wrote the reading (``{"input_tokens": 812, "output_tokens": 240, ...}``), so the
notes reader's cost is visible past Railway's seven-day log window, as the chat answer's
is since Batch 345. Null for readings written before it, and when no paid call was made.
Additive and nullable; RLS on the table is unchanged.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "041"
down_revision: str | None = "040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "check_in_readings",
        sa.Column("generation_usage", postgresql.JSONB(), nullable=True),
        schema="coach",
    )


def downgrade() -> None:
    op.drop_column("check_in_readings", "generation_usage", schema="coach")
