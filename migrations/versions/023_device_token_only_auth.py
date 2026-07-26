"""Remove the legacy PIN/JWT fallback (Batch 160).

Revision ID: 023
Revises: 022
Create Date: 2026-07-26

The migration refuses to strand an existing active profile: each must already
have an active device credential or an unused activation code. It then revokes
all residual PIN-era refresh credentials before dropping the three dead profile
columns and the obsolete ``purpose='refresh'`` server default.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "023"
down_revision: str | None = "022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DISABLED_PIN_HASH = "$2b$12$p64EXH8uS93.kUNAAtiPOu/bjf.uxX0DTrBfIdYRwXk..SLe0p83a"


def upgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM coach.profiles AS p
                WHERE p.deleted_at IS NULL
                  AND p.is_active IS TRUE
                  AND NOT EXISTS (
                      SELECT 1
                      FROM coach.refresh_tokens AS rt
                      WHERE rt.user_id = p.id
                        AND rt.revoked_at IS NULL
                        AND rt.expires_at > NOW()
                        AND (
                            rt.purpose = 'device'
                            OR (rt.purpose = 'activation' AND rt.used_at IS NULL)
                        )
                  )
            ) THEN
                RAISE EXCEPTION
                    'Batch 160 auth cutover blocked: active profile lacks device or activation token';
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        UPDATE coach.refresh_tokens
        SET revoked_at = NOW()
        WHERE purpose = 'refresh'
          AND revoked_at IS NULL
        """
    )
    op.alter_column(
        "refresh_tokens",
        "purpose",
        server_default=None,
        schema="coach",
    )
    op.drop_column("profiles", "locked_until", schema="coach")
    op.drop_column("profiles", "failed_login_count", schema="coach")
    op.drop_column("profiles", "pin_hash", schema="coach")


def downgrade() -> None:
    op.execute("SET search_path TO coach, public")
    op.add_column(
        "profiles",
        sa.Column(
            "pin_hash",
            sa.String(length=60),
            nullable=False,
            server_default=sa.text(f"'{_DISABLED_PIN_HASH}'"),
        ),
        schema="coach",
    )
    op.alter_column("profiles", "pin_hash", server_default=None, schema="coach")
    op.add_column(
        "profiles",
        sa.Column(
            "failed_login_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        schema="coach",
    )
    op.add_column(
        "profiles",
        sa.Column("locked_until", sa.DateTime(timezone=False), nullable=True),
        schema="coach",
    )
    op.alter_column(
        "refresh_tokens",
        "purpose",
        server_default="refresh",
        schema="coach",
    )
