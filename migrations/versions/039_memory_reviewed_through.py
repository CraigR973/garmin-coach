"""Remember how far the coach-memory step has read (Batch 346).

Revision ID: 039
Revises: 038
Create Date: 2026-10-28

One nullable timestamp on ``profiles``: the moment the conversation-learning step
last finished reading a profile's chat, check-in notes and corrections. Null means
it has never run, so the first run reads back to the first chat (18 Jul). Existing
rows stay null; RLS on the table is unchanged.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "039"
down_revision: str | None = "038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "profiles",
        sa.Column(
            "memory_reviewed_through_utc", sa.DateTime(timezone=False), nullable=True
        ),
        schema="coach",
    )


def downgrade() -> None:
    op.drop_column("profiles", "memory_reviewed_through_utc", schema="coach")
