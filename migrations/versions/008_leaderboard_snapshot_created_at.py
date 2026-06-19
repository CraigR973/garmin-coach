"""leaderboard_snapshots: add missing created_at column

Revision ID: 008
Revises: 007
Create Date: 2026-05-17

"""

from alembic import op
import sqlalchemy as sa

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "leaderboard_snapshots",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("leaderboard_snapshots", "created_at")
