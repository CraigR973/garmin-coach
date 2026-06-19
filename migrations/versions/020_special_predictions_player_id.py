"""020 — add predicted_player_id + winner_player_id to special_predictions (U14.4/5).

Adds:
  • special_predictions.predicted_player_id  — nullable FK → squad_players (id-based pick)
  • special_predictions.winner_player_id     — nullable FK → squad_players (id-based award)

Both are nullable so existing rows are unaffected and raw-SQL tests that INSERT
without naming these columns continue to work (server_default pattern from U12).

Revision ID: 020
Revises: 019
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "special_predictions",
        sa.Column(
            "predicted_player_id",
            UUID(as_uuid=True),
            sa.ForeignKey("squad_players.id", ondelete="SET NULL"),
            nullable=True,
            server_default=None,
        ),
    )
    op.add_column(
        "special_predictions",
        sa.Column(
            "winner_player_id",
            UUID(as_uuid=True),
            sa.ForeignKey("squad_players.id", ondelete="SET NULL"),
            nullable=True,
            server_default=None,
        ),
    )
    op.create_index(
        "ix_special_predictions_predicted_player_id",
        "special_predictions",
        ["predicted_player_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_special_predictions_predicted_player_id",
        table_name="special_predictions",
    )
    op.drop_column("special_predictions", "winner_player_id")
    op.drop_column("special_predictions", "predicted_player_id")
