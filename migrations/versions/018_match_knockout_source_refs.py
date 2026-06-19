"""Add positional source refs to matches for the seeded knockout skeleton.

U13.1 — the 32 knockout matches are seeded up front with positional
placeholder *source refs* that describe where each team comes from
(``winner_group_a``, ``runner_up_group_b``, ``best_third_1``,
``winner_match_73``, ``loser_match_101``). The pure resolver in
``src.services.knockout_progression`` reads these to fill the real teams in
as the tournament progresses. The human-readable display label continues to
live in the existing ``home_team_placeholder`` / ``away_team_placeholder``
columns.

Both columns are nullable — group-stage rows leave them NULL, and raw-SQL
test fixtures that omit them are unaffected (no server_default needed).

Revision ID: 018
Revises: 017
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("matches", sa.Column("home_source", sa.String(32), nullable=True))
    op.add_column("matches", sa.Column("away_source", sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column("matches", "away_source")
    op.drop_column("matches", "home_source")
