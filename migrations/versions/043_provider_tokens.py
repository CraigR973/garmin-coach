"""Keep the newest login a provider renewed, encrypted (Batch 365).

Revision ID: 043
Revises: 042
Create Date: 2026-11-02

garminconnect refreshes Garmin's token on its own, and the app threw each new one away,
logging in from the deployed ``GARMIN_TOKENSTORE_B64`` on every poll. Decision #462
approved keeping each renewed token. One row per provider: Fernet ciphertext keyed from
the deployed variable, and that variable's fingerprint, so a re-minted variable wins.
RLS is enabled where Supabase's ``auth`` schema exists, with no policy: only the service
reads it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "043"
down_revision: str | None = "042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RLS_TABLES: tuple[str, ...] = ("provider_tokens",)


def upgrade() -> None:
    op.create_table(
        "provider_tokens",
        sa.Column("provider", sa.String(32), primary_key=True),
        sa.Column("ciphertext", sa.String(), nullable=False),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
        sa.Column("updated_at_utc", sa.DateTime(), nullable=False),
        schema="coach",
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT FROM information_schema.schemata WHERE schema_name = 'auth'
            ) THEN
                ALTER TABLE coach.provider_tokens ENABLE ROW LEVEL SECURITY;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.drop_table("provider_tokens", schema="coach")
