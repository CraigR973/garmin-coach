"""R11 — Supabase RLS lockdown (C1): revoke anon/authenticated writes + enable RLS.

Closes critical finding C1 (docs/soak-review/code-audit-2026-05-30.md). The
Supabase ``anon`` / ``authenticated`` Postgres roles held the default
``GRANT ALL`` on every PostgREST-exposed ``public`` table and RLS was off, so
anyone holding the publicly-shipped anon key could read pre-kickoff picks,
tamper with results/leaderboards/memberships, or truncate ``alembic_version``
to wedge migrations — all bypassing FastAPI, the kickoff lock, and scoring.

On all 13 exposed tables this migration:
  R11.1 — REVOKEs INSERT/UPDATE/DELETE/TRUNCATE/REFERENCES/TRIGGER from
          ``anon`` and ``authenticated`` (kills the tamper/destroy vector).
          SELECT is deliberately NOT revoked; reads are gated by RLS instead.
  R11.2 — ENABLEs ROW LEVEL SECURITY (plain ENABLE, *not* FORCE: the backend
          connects as the ``postgres`` table owner, which keeps owner-bypass —
          see apps/api/.env.example — so the service role is unaffected). The
          two realtime-streamed, non-secret tables (``matches`` +
          ``leaderboard_snapshots``) get a permissive SELECT policy plus an
          explicit SELECT grant so the frontend realtime channels keep
          flowing. The other 11 tables get RLS with NO policy -> deny-all for
          anon/authenticated, which closes the pre-kickoff pick-leak on
          ``predictions`` / ``knockout_predictions``.

Already-locked tables (RLS enabled in an earlier manual Supabase change) are
left untouched: profiles, refresh_tokens, invites, groups, teams.

``anon`` / ``authenticated`` are Supabase-managed roles that do not exist on a
bare Postgres (CI's postgres:16, local pgserver). They are created NOLOGIN if
absent so the REVOKE / CREATE POLICY statements are portable; on Supabase the
guard is a no-op because the roles already exist.

The whole upgrade runs in one transaction, so anon never observes an
intermediate "RLS on, policy not yet created" state on the two readable
tables. env.py applies lock_timeout=5s (R8): ENABLE RLS takes ACCESS EXCLUSIVE
per table, so on a busy DB this fails fast rather than hanging — apply during
low traffic or expect a retry.

Revision ID: 015
Revises: 014
"""

from __future__ import annotations

from alembic import op

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None

# The 13 PostgREST-exposed public tables with RLS off + anon GRANT ALL, per
# the C1 audit (pg_class + information_schema.role_table_grants on staging).
EXPOSED_TABLES = (
    "matches",
    "predictions",
    "knockout_predictions",
    "special_predictions",
    "leaderboard_snapshots",
    "leagues",
    "league_memberships",
    "league_join_requests",
    "push_subscriptions",
    "notification_preferences",
    "notification_log",
    "audit_log",
    "alembic_version",
)

# The only tables the frontend subscribes to over Supabase realtime. Both are
# non-secret (fixtures + standings), so they keep an anon/authenticated SELECT
# path. Every other exposed table is deny-all.
READABLE_TABLES = ("matches", "leaderboard_snapshots")

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

    # R11.1 — revoke write grants. REVOKE of an absent grant is a silent no-op,
    # so this is safe on both Supabase (GRANT ALL present) and bare Postgres.
    for table in EXPOSED_TABLES:
        op.execute(f"REVOKE {_WRITE_PRIVS} ON TABLE {table} FROM anon, authenticated")

    # R11.2 — enable RLS on every exposed table. Plain ENABLE (not FORCE) so the
    # postgres owner the backend connects as keeps owner-bypass. Idempotent.
    for table in EXPOSED_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")

    # Realtime-safe SELECT path on the two non-secret tables only. The explicit
    # GRANT SELECT keeps the read path self-contained rather than relying on
    # Supabase's pre-existing default grant. DROP-before-CREATE keeps the
    # upgrade re-runnable after a partial failure.
    for table in READABLE_TABLES:
        op.execute(f"GRANT SELECT ON TABLE {table} TO anon, authenticated")
        op.execute(f'DROP POLICY IF EXISTS "{table}_anon_read" ON {table}')
        op.execute(
            f'CREATE POLICY "{table}_anon_read" ON {table} '
            "FOR SELECT TO anon, authenticated USING (true)"
        )


def downgrade() -> None:
    # Drop the two SELECT policies.
    for table in READABLE_TABLES:
        op.execute(f'DROP POLICY IF EXISTS "{table}_anon_read" ON {table}')

    # Disable RLS on every exposed table.
    for table in EXPOSED_TABLES:
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    # Restore the default Supabase GRANT ALL to anon + authenticated. Roles are
    # left in place (never drop the Supabase-managed roles on downgrade).
    for table in EXPOSED_TABLES:
        op.execute(f"GRANT ALL ON TABLE {table} TO anon, authenticated")
