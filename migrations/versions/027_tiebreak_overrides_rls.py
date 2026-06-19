"""security: ENABLE RLS + deny-all on leaderboard_tiebreak_overrides.

Migration 026 introduced the ``leaderboard_tiebreak_overrides`` table but the
R11 RLS lockdown (migration 015) had already run — so the new table was never
covered.  Without RLS any holder of the Supabase anon key can read or write
tiebreak overrides via PostgREST, bypassing the backend entirely and enabling
standings tampering.

This migration:
  - Revokes INSERT/UPDATE/DELETE/TRUNCATE from ``anon`` and ``authenticated``
    (same pattern as migration 015).
  - Enables RLS with NO permissive policy → deny-all for anon/authenticated.
    The backend connects as the ``postgres`` owner which keeps owner-bypass,
    so the service role is unaffected.

Downgrade reverses both steps (disables RLS, restores the GRANT ALL).

Revision ID: 027
Revises: 026
Create Date: 2026-06-08
"""

from __future__ import annotations

from alembic import op

revision: str = "027"
down_revision: str = "026"
branch_labels = None
depends_on = None

_TABLE = "leaderboard_tiebreak_overrides"
_WRITE_PRIVS = "INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER"

# Idempotently ensure the Supabase roles exist so this migration runs on a
# bare Postgres (CI / local) as well as on Supabase.
_ENSURE_ROLES = """
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        CREATE ROLE anon NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        CREATE ROLE authenticated NOLOGIN;
    END IF;
END
$$;
"""


def upgrade() -> None:
    op.execute(_ENSURE_ROLES)
    op.execute(f"REVOKE {_WRITE_PRIVS} ON TABLE {_TABLE} FROM anon, authenticated")
    op.execute(f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute(f"ALTER TABLE {_TABLE} DISABLE ROW LEVEL SECURITY")
    op.execute(f"GRANT ALL ON TABLE {_TABLE} TO anon, authenticated")
