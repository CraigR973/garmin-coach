"""A switch for each kind of push (Batch 366).

Revision ID: 044
Revises: 043
Create Date: 2026-11-02

Settings offered only "on" or "off" for every push: 161 in 25 days, with nothing that
let him keep the brief and the ride read and drop the bedroom pair (UX362-02). Three
switches, each on by default: the morning brief and his workout reads, the bedroom and
the evening sleep read, and the weekly review. Alerts about missing data stay on.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "044"
down_revision: str | None = "043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS: tuple[str, ...] = ("push_reads", "push_bedroom", "push_reviews")


def upgrade() -> None:
    for column in COLUMNS:
        op.add_column(
            "notification_preferences",
            sa.Column(column, sa.Boolean(), nullable=False, server_default=sa.true()),
            schema="coach",
        )


def downgrade() -> None:
    for column in reversed(COLUMNS):
        op.drop_column("notification_preferences", column, schema="coach")
