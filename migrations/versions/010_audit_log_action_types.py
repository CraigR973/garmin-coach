"""Add backup_failed and backup_downloaded to audit_log.action_type enum.

Revision ID: 010
Revises: 009
"""

from __future__ import annotations

from alembic import op

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE action_type ADD VALUE IF NOT EXISTS 'backup_failed'")
    op.execute("ALTER TYPE action_type ADD VALUE IF NOT EXISTS 'backup_downloaded'")


def downgrade() -> None:
    # Postgres does not support removing enum values; downgrade is a no-op.
    pass
