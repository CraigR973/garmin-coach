"""Add bedroom-fan auto-control preference to profiles.

Revision ID: 010
Revises: 009
Create Date: 2026-06-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "010"
down_revision: str | None = "009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.add_column(
        "profiles",
        sa.Column(
            "fan_auto_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        schema="coach",
    )


def downgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.drop_column("profiles", "fan_auto_enabled", schema="coach")
