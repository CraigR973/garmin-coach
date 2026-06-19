"""M8: mark email, first_name, last_name, site_role NOT NULL on profiles.

These columns were added as nullable in migration 011 to allow the M1 backfill
to run before enforcement. The backfill is complete; this migration enforces the
constraints and converts the partial unique index on email to a full unique index.

Revision ID: 014
Revises: 013
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Fail fast if any profiles have NULL values that would violate the constraints.
    conn = op.get_bind()
    null_check = conn.execute(
        sa.text(
            "SELECT count(*) FROM profiles WHERE deleted_at IS NULL AND ("
            "  email IS NULL OR first_name IS NULL OR last_name IS NULL OR site_role IS NULL"
            ")"
        )
    ).scalar()
    if null_check and null_check > 0:
        raise RuntimeError(
            f"Migration 014 aborted: {null_check} active profile(s) have NULL identity fields. "
            "Run the M1 backfill script against this environment first."
        )

    op.alter_column("profiles", "email", existing_type=sa.String(255), nullable=False)
    op.alter_column("profiles", "first_name", existing_type=sa.String(100), nullable=False)
    op.alter_column("profiles", "last_name", existing_type=sa.String(100), nullable=False)
    op.alter_column(
        "profiles",
        "site_role",
        existing_type=sa.Enum(name="site_role"),
        nullable=False,
    )

    # Replace the partial unique index (WHERE email IS NOT NULL) with a full unique index.
    op.execute("DROP INDEX IF EXISTS ix_profiles_email_unique_lower")
    op.execute(
        "CREATE UNIQUE INDEX ix_profiles_email_unique_lower ON profiles (LOWER(email))"
    )


def downgrade() -> None:
    op.alter_column("profiles", "site_role", existing_type=sa.Enum(name="site_role"), nullable=True)
    op.alter_column("profiles", "last_name", existing_type=sa.String(100), nullable=True)
    op.alter_column("profiles", "first_name", existing_type=sa.String(100), nullable=True)
    op.alter_column("profiles", "email", existing_type=sa.String(255), nullable=True)

    # Restore partial index — safe to recreate even if some rows now have NULL email.
    op.execute("DROP INDEX IF EXISTS ix_profiles_email_unique_lower")
    op.execute(
        "CREATE UNIQUE INDEX ix_profiles_email_unique_lower ON profiles (LOWER(email))"
        " WHERE email IS NOT NULL"
    )
