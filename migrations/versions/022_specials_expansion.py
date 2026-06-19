"""specials: add player_of_tournament, young_player_of_tournament, golden_glove.

Values-only migration — no table changes needed since special_predictions
already has predicted_player_id and winner_player_id columns (migration 020).

``ALTER TYPE ... ADD VALUE`` is valid inside a transaction on PostgreSQL ≥ 12.
CI uses postgres:16, so no AUTOCOMMIT workaround is required.

Revision ID: 022
Revises: 021
Create Date: 2026-06-02
"""

from typing import Sequence, Union

from alembic import op

revision: str = "022"
down_revision: Union[str, None] = "021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_VALUES = (
    "player_of_tournament",
    "young_player_of_tournament",
    "golden_glove",
)


def upgrade() -> None:
    for value in _NEW_VALUES:
        op.execute(
            f"ALTER TYPE special_prediction_type ADD VALUE IF NOT EXISTS '{value}'"
        )


def downgrade() -> None:
    # Postgres does not support DROP VALUE — the enum values will remain.
    # To fully revert, drop and recreate the enum with only the original values,
    # which requires a full table rewrite. Since no rows can exist for these new
    # types before the downgrade, this is safe to leave as a no-op.
    pass
