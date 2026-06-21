"""Rename player_id → user_id in push_subscriptions, notification_preferences, refresh_tokens.

Revision ID: 006
Revises: 005
Create Date: 2026-06-21
"""

from collections.abc import Sequence

from alembic import op

revision: str = "006"
down_revision: str | None = "005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # push_subscriptions
    op.drop_index("ix_push_subscriptions_player_id", table_name="push_subscriptions", schema="coach")
    op.alter_column("push_subscriptions", "player_id", new_column_name="user_id", schema="coach")
    op.create_index("ix_push_subscriptions_user_id", "push_subscriptions", ["user_id"], schema="coach")

    # notification_preferences (player_id is the PK — rename only, PK constraint stays)
    op.alter_column("notification_preferences", "player_id", new_column_name="user_id", schema="coach")

    # refresh_tokens
    op.alter_column("refresh_tokens", "player_id", new_column_name="user_id", schema="coach")


def downgrade() -> None:
    # refresh_tokens
    op.alter_column("refresh_tokens", "user_id", new_column_name="player_id", schema="coach")

    # notification_preferences
    op.alter_column("notification_preferences", "user_id", new_column_name="player_id", schema="coach")

    # push_subscriptions
    op.drop_index("ix_push_subscriptions_user_id", table_name="push_subscriptions", schema="coach")
    op.alter_column("push_subscriptions", "user_id", new_column_name="player_id", schema="coach")
    op.create_index("ix_push_subscriptions_player_id", "push_subscriptions", ["player_id"], schema="coach")
