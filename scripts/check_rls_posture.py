"""Read-only RLS/grant/exposed-schema posture check for the Supabase coach schema."""

from __future__ import annotations

import argparse
import asyncio
import os
from dataclasses import dataclass
from typing import Any

DATA_API_ROLES = frozenset({"anon", "authenticated", "service_role"})
EXPECTED_EXPOSED_SCHEMAS = frozenset({"public", "graphql_public"})
EXPECTED_FUNCTION_SEARCH_PATH = "coach, pg_temp"


@dataclass(frozen=True)
class PostureSnapshot:
    tables_without_rls: tuple[str, ...]
    data_api_schema_grants: tuple[str, ...]
    data_api_table_grants: tuple[str, ...]
    exposed_schemas: tuple[str, ...] | None
    policies_without_authenticated: tuple[str, ...]
    update_policies_without_check: tuple[str, ...]
    public_executable_functions: tuple[str, ...]
    functions_with_mutable_search_path: tuple[str, ...]


def evaluate_posture(snapshot: PostureSnapshot) -> list[str]:
    failures: list[str] = []
    if snapshot.tables_without_rls:
        failures.append(
            "coach tables without RLS: " + ", ".join(snapshot.tables_without_rls)
        )
    if snapshot.data_api_schema_grants:
        failures.append(
            "Data API roles with coach schema usage: "
            + ", ".join(snapshot.data_api_schema_grants)
        )
    if snapshot.data_api_table_grants:
        failures.append(
            "Data API roles with coach table DML: "
            + ", ".join(snapshot.data_api_table_grants)
        )
    if snapshot.exposed_schemas is not None:
        exposed = frozenset(snapshot.exposed_schemas)
        if exposed != EXPECTED_EXPOSED_SCHEMAS:
            failures.append(
                "unexpected exposed schemas: "
                + ", ".join(snapshot.exposed_schemas)
                + f" (expected {', '.join(sorted(EXPECTED_EXPOSED_SCHEMAS))})"
            )
    if snapshot.policies_without_authenticated:
        failures.append(
            "policies missing explicit authenticated role: "
            + ", ".join(snapshot.policies_without_authenticated)
        )
    if snapshot.update_policies_without_check:
        failures.append(
            "UPDATE policies without WITH CHECK: "
            + ", ".join(snapshot.update_policies_without_check)
        )
    if snapshot.public_executable_functions:
        failures.append(
            "coach functions executable by PUBLIC: "
            + ", ".join(snapshot.public_executable_functions)
        )
    if snapshot.functions_with_mutable_search_path:
        failures.append(
            "coach functions without fixed search_path: "
            + ", ".join(snapshot.functions_with_mutable_search_path)
        )
    return failures


async def _fetch_snapshot(database_url: str) -> PostureSnapshot:
    try:
        import asyncpg
    except ImportError as exc:  # pragma: no cover - operator environment only
        raise SystemExit("asyncpg is required to run the live posture check") from exc

    conn = await asyncpg.connect(database_url)
    try:
        tables_without_rls = await conn.fetch(
            """
            SELECT c.relname
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'coach'
              AND c.relkind IN ('r', 'p')
              AND c.relrowsecurity IS NOT TRUE
            ORDER BY c.relname
            """
        )
        schema_grants = await conn.fetch(
            """
            SELECT role_name || ':USAGE' AS grant_name
            FROM unnest($1::text[]) AS role_name
            WHERE has_schema_privilege(role_name, 'coach', 'USAGE')
            ORDER BY grant_name
            """,
            sorted(DATA_API_ROLES),
        )
        table_grants = await conn.fetch(
            """
            SELECT grantee || ':' || table_name || ':' || privilege_type AS grant_name
            FROM information_schema.role_table_grants
            WHERE table_schema = 'coach'
              AND grantee = ANY($1::text[])
              AND privilege_type IN ('SELECT', 'INSERT', 'UPDATE', 'DELETE')
            ORDER BY grant_name
            """,
            sorted(DATA_API_ROLES),
        )
        exposed_setting = await conn.fetchval(
            "SELECT current_setting('pgrst.db_schemas', true)"
        )
        exposed = (
            tuple(part.strip() for part in exposed_setting.split(",") if part.strip())
            if exposed_setting
            else None
        )
        policy_rows = await conn.fetch(
            """
            SELECT schemaname, tablename, policyname, cmd, roles, with_check
            FROM pg_policies
            WHERE schemaname = 'coach'
              AND tablename IN (
                'profiles',
                'refresh_tokens',
                'push_subscriptions',
                'notification_preferences'
              )
            ORDER BY tablename, policyname
            """
        )
        public_functions = await conn.fetch(
            """
            SELECT n.nspname || '.' || p.proname || '()' AS function_name
            FROM pg_proc p
            JOIN pg_namespace n ON n.oid = p.pronamespace
            WHERE n.nspname = 'coach'
              AND has_function_privilege('public', p.oid, 'EXECUTE')
            ORDER BY function_name
            """
        )
        mutable_functions = await conn.fetch(
            """
            SELECT n.nspname || '.' || p.proname || '()' AS function_name
            FROM pg_proc p
            JOIN pg_namespace n ON n.oid = p.pronamespace
            WHERE n.nspname = 'coach'
              AND NOT ($1 = ANY(coalesce(p.proconfig, ARRAY[]::text[])))
            ORDER BY function_name
            """,
            f"search_path={EXPECTED_FUNCTION_SEARCH_PATH}",
        )
    finally:
        await conn.close()

    return PostureSnapshot(
        tables_without_rls=tuple(row["relname"] for row in tables_without_rls),
        data_api_schema_grants=tuple(row["grant_name"] for row in schema_grants),
        data_api_table_grants=tuple(row["grant_name"] for row in table_grants),
        exposed_schemas=exposed,
        policies_without_authenticated=tuple(
            _policy_name(row)
            for row in policy_rows
            if "authenticated" not in _roles(row["roles"])
        ),
        update_policies_without_check=tuple(
            _policy_name(row)
            for row in policy_rows
            if row["cmd"] == "UPDATE" and not row["with_check"]
        ),
        public_executable_functions=tuple(
            row["function_name"] for row in public_functions
        ),
        functions_with_mutable_search_path=tuple(
            row["function_name"] for row in mutable_functions
        ),
    )


def _roles(raw_roles: Any) -> set[str]:
    if raw_roles is None:
        return set()
    return {str(role) for role in raw_roles}


def _policy_name(row: Any) -> str:
    return f"{row['tablename']}.{row['policyname']}"


async def _amain() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.getenv("RLS_POSTURE_DATABASE_URL"))
    parser.add_argument(
        "--allow-missing-url",
        action="store_true",
        help="Exit cleanly when no live posture database URL is configured.",
    )
    args = parser.parse_args()
    if not args.database_url:
        if args.allow_missing_url:
            print(
                "RLS posture check skipped: RLS_POSTURE_DATABASE_URL is not configured"
            )
            return
        raise SystemExit("RLS_POSTURE_DATABASE_URL is required")

    failures = evaluate_posture(await _fetch_snapshot(args.database_url))
    if failures:
        for failure in failures:
            print(f"RLS posture failure: {failure}")
        raise SystemExit(1)
    print("RLS posture check passed")


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
