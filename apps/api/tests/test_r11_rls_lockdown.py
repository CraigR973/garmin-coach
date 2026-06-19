"""R11 — Supabase RLS lockdown (C1).

Behavioural assertions on the live catalog after migration 015 has been
applied (CI runs ``alembic upgrade head`` against postgres:16 before pytest;
locally the same against pgserver). They prove the migration actually:

  * enabled (plain, not FORCEd) RLS on all 13 exposed tables,
  * revoked anon/authenticated write grants on all 13,
  * created exactly the two realtime SELECT policies (matches +
    leaderboard_snapshots) and left the other 11 deny-all.

The anon-REST / realtime / advisor checks are Supabase-specific and run on
staging after deploy (R11.4) — not reproducible against bare Postgres.

The table lists are restated here on purpose (not imported from the migration)
so a wrong edit to the migration's tuple is caught by a divergence here rather
than shared between the two.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

pytestmark = pytest.mark.asyncio

# The 13 PostgREST-exposed tables locked down by migration 015.
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

# The two non-secret realtime tables that keep an anon/authenticated SELECT
# path; every other exposed table is deny-all.
READABLE_TABLES = ("matches", "leaderboard_snapshots")
DENY_ALL_TABLES = tuple(t for t in EXPOSED_TABLES if t not in READABLE_TABLES)

WRITE_PRIVS = {"INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"}


async def test_exposed_tables_have_rls_enabled_not_forced(
    db_conn: AsyncConnection,
) -> None:
    rows = (
        await db_conn.execute(
            sa.text(
                "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity "
                "FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND c.relkind = 'r'"
            )
        )
    ).all()
    state = {r.relname: (r.relrowsecurity, r.relforcerowsecurity) for r in rows}

    for table in EXPOSED_TABLES:
        assert table in state, f"{table} not found in public schema"
        rls_on, forced = state[table]
        assert rls_on, f"RLS not enabled on {table}"
        # FORCE would break the postgres-owner bypass the backend relies on.
        assert not forced, f"RLS is FORCEd on {table} (must be plain ENABLE)"


async def test_anon_authenticated_have_no_write_grants(
    db_conn: AsyncConnection,
) -> None:
    # has_table_privilege() reports the *effective* privilege of any role and
    # works as superuser regardless of role membership — unlike
    # information_schema.role_table_grants, which only shows grants visible to
    # the current role (postgres is not a member of anon/authenticated on a
    # bare local Postgres, so that view would hide the truth there).
    leaked: list[tuple[str, str, str]] = []
    for role in ("anon", "authenticated"):
        for table in EXPOSED_TABLES:
            held = (
                (
                    await db_conn.execute(
                        sa.text(
                            "SELECT priv FROM unnest(CAST(:privs AS text[])) AS priv "
                            "WHERE has_table_privilege(:role, :tbl, priv)"
                        ),
                        {
                            "privs": list(WRITE_PRIVS),
                            "role": role,
                            "tbl": f"public.{table}",
                        },
                    )
                )
                .scalars()
                .all()
            )
            leaked += [(role, table, p) for p in held]
    assert leaked == [], f"anon/authenticated retain write grants: {leaked}"


async def test_readable_tables_keep_anon_select_grant(
    db_conn: AsyncConnection,
) -> None:
    rows = (
        await db_conn.execute(
            sa.text(
                "SELECT grantee, table_name "
                "FROM information_schema.role_table_grants "
                "WHERE table_schema = 'public' "
                "AND privilege_type = 'SELECT' "
                "AND grantee IN ('anon', 'authenticated')"
            )
        )
    ).all()
    granted = {(r.grantee, r.table_name) for r in rows}

    for table in READABLE_TABLES:
        assert ("anon", table) in granted, f"anon lost SELECT on {table}"
        assert ("authenticated", table) in granted, f"authenticated lost SELECT on {table}"


async def test_only_realtime_tables_have_select_policies(
    db_conn: AsyncConnection,
) -> None:
    # Query the pg_policy catalog directly rather than the pg_policies view:
    # the view resolves roles via the superuser-only pg_authid and was observed
    # to return zero rows under pgserver even with policies present. pg_policy +
    # pg_roles is portable and readable by any role. polcmd 'r' == SELECT.
    rows = (
        await db_conn.execute(
            sa.text(
                "SELECT c.relname AS tablename, pol.polname AS policyname, "
                "CASE pol.polcmd WHEN 'r' THEN 'SELECT' WHEN 'a' THEN 'INSERT' "
                "WHEN 'w' THEN 'UPDATE' WHEN 'd' THEN 'DELETE' WHEN '*' THEN 'ALL' "
                "END AS cmd, "
                "ARRAY(SELECT r.rolname FROM pg_roles r "
                "WHERE r.oid = ANY(pol.polroles)) AS roles "
                "FROM pg_policy pol "
                "JOIN pg_class c ON c.oid = pol.polrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public'"
            )
        )
    ).all()

    policies: dict[str, list[tuple[str, str, list[str]]]] = {}
    for r in rows:
        policies.setdefault(r.tablename, []).append((r.policyname, r.cmd, list(r.roles)))

    # Each readable table has exactly one permissive SELECT policy for
    # anon + authenticated.
    for table in READABLE_TABLES:
        table_policies = policies.get(table, [])
        assert len(table_policies) == 1, (
            f"{table} should have exactly one policy, found {table_policies}"
        )
        name, cmd, roles = table_policies[0]
        assert name == f"{table}_anon_read"
        assert cmd == "SELECT"
        assert "anon" in roles
        assert "authenticated" in roles

    # The other 11 exposed tables are deny-all: RLS on, no policy at all.
    for table in DENY_ALL_TABLES:
        assert policies.get(table, []) == [], (
            f"{table} must be deny-all but has policies: {policies.get(table)}"
        )
