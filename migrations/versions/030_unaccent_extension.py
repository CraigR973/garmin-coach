"""Enable unaccent extension for accent-insensitive player search.

Revision ID: 030
Revises: 029
Create Date: 2026-06-08
"""

from alembic import op

revision = "030"
down_revision = "029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")


def downgrade() -> None:
    # Dropping unaccent could break other things; leave it installed.
    pass
