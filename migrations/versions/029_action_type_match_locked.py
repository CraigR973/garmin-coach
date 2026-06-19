"""Add match_locked to action_type enum.

Needed for the GAP-07 manual early-lock endpoint
(POST /admin/matches/{id}/lock).

Revision ID: 029
Revises: 028
Create Date: 2026-06-08
"""

from __future__ import annotations

from alembic import op

revision: str = "029"
down_revision: str = "028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE action_type ADD VALUE IF NOT EXISTS 'match_locked'")


def downgrade() -> None:
    # Postgres does not support removing enum values; this is a no-op downgrade.
    # The extra value is harmless if the column is never populated with it.
    pass
