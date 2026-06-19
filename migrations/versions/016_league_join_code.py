"""Add join_code to leagues; add league_join_code_rotated ActionType.

U12.1 — each league gets a reusable 6-char human-typable join code drawn from
an unambiguous alphabet (no I / O / 0 / 1).  Existing leagues are backfilled.
New leagues receive a code at creation time (see create_league endpoint).

``ALTER TYPE action_type ADD VALUE`` is valid inside a transaction on
PostgreSQL ≥ 12; CI uses postgres:16 so this is safe.

Revision ID: 016
Revises: 015
"""

from __future__ import annotations

import secrets

import sqlalchemy as sa
from alembic import op

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None

_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no I, O, 0, 1


def _gen_code(used: set[str]) -> str:
    while True:
        code = "".join(secrets.choice(_ALPHABET) for _ in range(6))
        if code not in used:
            used.add(code)
            return code


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Add nullable column so existing rows aren't immediately rejected.
    op.add_column("leagues", sa.Column("join_code", sa.String(8), nullable=True))

    # 2. Backfill all rows (including soft-deleted — NOT NULL requires every row).
    rows = conn.execute(sa.text("SELECT id FROM leagues")).fetchall()
    used: set[str] = set()
    for (league_id,) in rows:
        code = _gen_code(used)
        conn.execute(
            sa.text("UPDATE leagues SET join_code = :c WHERE id = :id"),
            {"c": code, "id": str(league_id)},
        )

    # 3. Enforce NOT NULL now that every row has a value.
    op.alter_column("leagues", "join_code", existing_type=sa.String(8), nullable=False)

    # 4. Unique constraint + index for fast by-code lookup.
    op.create_unique_constraint("uq_leagues_join_code", "leagues", ["join_code"])
    op.create_index("ix_leagues_join_code", "leagues", ["join_code"])

    # 5. New audit action type.
    op.execute("ALTER TYPE action_type ADD VALUE IF NOT EXISTS 'league_join_code_rotated'")


def downgrade() -> None:
    op.drop_index("ix_leagues_join_code", table_name="leagues")
    op.drop_constraint("uq_leagues_join_code", "leagues", type_="unique")
    op.drop_column("leagues", "join_code")
