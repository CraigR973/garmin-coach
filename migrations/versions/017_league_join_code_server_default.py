"""Add server_default to leagues.join_code for test fixtures.

Integration tests INSERT into leagues with raw SQL and omit join_code,
hitting the NOT NULL constraint added in 016. Adding a server_default
satisfies those inserts; new API-created leagues already set join_code
explicitly in create_league (Python-side generate_join_code()).

The default ``upper(substr(md5(random()::text), 1, 6))`` produces a 6-char
uppercase hex string.  It is different from our preferred alphabet (hex only,
may include 0/1) but guarantees uniqueness well enough for any raw-SQL path.
Production-facing league creation always goes through the API which sets the
Python-generated code, so the server default is only a safety net.

Revision ID: 017
Revises: 016
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "leagues",
        "join_code",
        existing_type=sa.String(8),
        server_default=sa.text("upper(substr(md5(random()::text), 1, 6))"),
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "leagues",
        "join_code",
        existing_type=sa.String(8),
        server_default=None,
        nullable=False,
    )
