"""Add member_joined to notification_type enum

Revision ID: 031
Revises: 030
Create Date: 2026-06-09
"""

from alembic import op

revision = "031"
down_revision = "030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'member_joined'")


def downgrade() -> None:
    # Postgres does not support removing enum values; downgrade is a no-op.
    pass
