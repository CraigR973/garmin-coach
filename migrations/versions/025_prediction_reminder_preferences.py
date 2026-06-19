"""prediction reminders: notification types and preference toggles.

Revision ID: 025
Revises: 024
Create Date: 2026-06-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "025"
down_revision: Union[str, None] = "024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'predict_reminder'")
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'pick_confirmation'")
    op.add_column(
        "notification_preferences",
        sa.Column("predict_reminder", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.add_column(
        "notification_preferences",
        sa.Column("pick_confirmation", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("notification_preferences", "pick_confirmation")
    op.drop_column("notification_preferences", "predict_reminder")
