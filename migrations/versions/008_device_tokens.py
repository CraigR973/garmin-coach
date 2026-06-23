"""Add device-token + activation-code support to refresh_tokens.

Adds a `purpose` discriminator ('refresh' | 'device' | 'activation') and a
`used_at` timestamp (set when a single-use activation code is consumed), plus
an index on `token_hash` for the device/activation lookups. Purely additive —
existing rows backfill to purpose='refresh'.

Revision ID: 008
Revises: 007
Create Date: 2026-06-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "008"
down_revision: str | None = "007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.add_column(
        "refresh_tokens",
        sa.Column(
            "purpose", sa.String(length=20), server_default="refresh", nullable=False
        ),
        schema="coach",
    )
    op.add_column(
        "refresh_tokens",
        sa.Column("used_at", sa.DateTime(timezone=False), nullable=True),
        schema="coach",
    )
    op.create_index(
        "ix_refresh_tokens_token_hash",
        "refresh_tokens",
        ["token_hash"],
        schema="coach",
    )


def downgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.drop_index(
        "ix_refresh_tokens_token_hash",
        table_name="refresh_tokens",
        schema="coach",
        if_exists=True,
    )
    op.drop_column("refresh_tokens", "used_at", schema="coach")
    op.drop_column("refresh_tokens", "purpose", schema="coach")
