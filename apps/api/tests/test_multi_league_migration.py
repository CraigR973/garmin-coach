"""Phase M1 — migration 011 + backfill script coverage.

Tests run inside the ``db_conn`` fixture (auto-rolled back on exit). They
assume migration 011 has already been applied by ``alembic upgrade head``
in the test setup (matches the v1 pattern used by every other DB test).

The backfill driver is invoked through ``run_backfill`` so we can exercise
its idempotency and assertion behaviour without subprocessing.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

# Make ``scripts/`` importable so the backfill driver is in scope.
_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT))

from scripts.backfill_multi_league import (  # noqa: E402
    SidecarEntry,
    _derive_first_last,
    _slugify,
    run_backfill,
)

# ---------------------------------------------------------------------------
# Helpers — small wrappers to keep tests readable.
# ---------------------------------------------------------------------------


async def _exec(conn: AsyncConnection, sql: str, **params: Any) -> Any:
    return await conn.execute(text(sql), params)


async def _scalar(conn: AsyncConnection, sql: str, **params: Any) -> Any:
    result = await conn.execute(text(sql), params)
    return result.scalar_one()


async def _scalar_or_none(conn: AsyncConnection, sql: str, **params: Any) -> Any:
    result = await conn.execute(text(sql), params)
    return result.scalar_one_or_none()


async def _fetchall(conn: AsyncConnection, sql: str, **params: Any) -> list[Any]:
    result = await conn.execute(text(sql), params)
    return list(result.mappings().all())


async def _make_profile(conn: AsyncConnection, display_name: str, role: str = "player") -> str:
    # Pre-populate with backfill-derived values so run_backfill preserves them
    # and the test assertions still pass (email/first_name/last_name NOT NULL since 014).
    first, last = _derive_first_last(display_name)
    pending_email = f"pending+{_slugify(display_name)}@steele.invalid"
    pid = await _scalar(
        conn,
        """
        INSERT INTO profiles (
            id, display_name, pin_hash, role, email,
            first_name, last_name, site_role
        )
        VALUES (
            gen_random_uuid(),
            :n,
            '$2b$12$0000000000000000000000000000000000000000000000000000',
            CAST(:r AS player_role),
            :email,
            :first_name,
            :last_name,
            CAST('user' AS site_role)
        )
        RETURNING id
        """,
        n=display_name,
        r=role,
        email=pending_email,
        first_name=first,
        last_name=last,
    )
    return str(pid)


# ---------------------------------------------------------------------------
# Pure-Python helpers — no DB needed.
# ---------------------------------------------------------------------------


def test_slugify_strips_and_lowers() -> None:
    assert _slugify("Craig Robinson") == "craig-robinson"
    assert _slugify("  -- Foo!  ") == "foo"
    assert _slugify("") == "player"
    assert _slugify("123") == "123"


def test_derive_first_last_single_token() -> None:
    assert _derive_first_last("Craig") == ("Craig", "")


def test_derive_first_last_with_space() -> None:
    assert _derive_first_last("Alice Wong") == ("Alice", "Wong")


def test_derive_first_last_multiple_tokens() -> None:
    assert _derive_first_last("Mary Jane Watson") == ("Mary", "Jane Watson")


# ---------------------------------------------------------------------------
# Schema sanity — migration 011 must already be applied by alembic upgrade.
# ---------------------------------------------------------------------------


async def test_alembic_revision_at_least_011(db_conn: AsyncConnection) -> None:
    rev = await _scalar(db_conn, "SELECT version_num FROM alembic_version")
    assert rev >= "011"


async def test_new_tables_exist(db_conn: AsyncConnection) -> None:
    for table in ("leagues", "league_memberships", "league_join_requests"):
        row = await _scalar(
            db_conn,
            "SELECT to_regclass(:t)::text",
            t=f"public.{table}",
        )
        assert row == table, f"Table {table!r} missing after migration 011"


async def test_profiles_has_new_identity_columns(db_conn: AsyncConnection) -> None:
    cols = {
        r["column_name"]
        for r in await _fetchall(
            db_conn,
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'profiles'
            """,
        )
    }
    assert {
        "email",
        "first_name",
        "last_name",
        "email_verified_at",
        "site_role",
    }.issubset(cols)


async def test_profiles_display_name_unique_dropped(db_conn: AsyncConnection) -> None:
    rows = await _fetchall(
        db_conn,
        """
        SELECT conname FROM pg_constraint
        WHERE conrelid = 'profiles'::regclass AND contype = 'u'
        """,
    )
    names = {r["conname"] for r in rows}
    assert "uq_profiles_display_name" not in names


async def test_league_privacy_enum_values(db_conn: AsyncConnection) -> None:
    rows = await _fetchall(
        db_conn,
        """
        SELECT enumlabel FROM pg_enum
        WHERE enumtypid = 'league_privacy'::regtype
        ORDER BY enumsortorder
        """,
    )
    values = [r["enumlabel"] for r in rows]
    assert values == ["private", "public_request", "public_open"]


async def test_site_role_enum_values(db_conn: AsyncConnection) -> None:
    rows = await _fetchall(
        db_conn,
        """
        SELECT enumlabel FROM pg_enum
        WHERE enumtypid = 'site_role'::regtype
        ORDER BY enumsortorder
        """,
    )
    values = [r["enumlabel"] for r in rows]
    assert values == ["superadmin", "user"]


async def test_leagues_default_privacy_is_private(db_conn: AsyncConnection) -> None:
    craig = await _make_profile(db_conn, "Craig", role="admin")
    lid = await _scalar(
        db_conn,
        """
        INSERT INTO leagues (id, slug, name, created_by)
        VALUES (gen_random_uuid(), 'test-default', 'Test Default', :cb)
        RETURNING id
        """,
        cb=craig,
    )
    privacy = await _scalar(db_conn, "SELECT privacy FROM leagues WHERE id = :id", id=lid)
    assert privacy == "private"


async def test_league_memberships_unique_pair(db_conn: AsyncConnection) -> None:
    craig = await _make_profile(db_conn, "Craig", role="admin")
    lid = await _scalar(
        db_conn,
        """
        INSERT INTO leagues (id, slug, name, created_by)
        VALUES (gen_random_uuid(), 'test-unique', 'Test Unique', :cb)
        RETURNING id
        """,
        cb=craig,
    )
    await _exec(
        db_conn,
        """
        INSERT INTO league_memberships (id, league_id, player_id, role)
        VALUES (gen_random_uuid(), :lid, :pid, CAST('admin' AS league_member_role))
        """,
        lid=lid,
        pid=craig,
    )
    with pytest.raises(Exception):  # IntegrityError surfaces wrapped
        await _exec(
            db_conn,
            """
            INSERT INTO league_memberships (id, league_id, player_id, role)
            VALUES (gen_random_uuid(), :lid, :pid,
                    CAST('player' AS league_member_role))
            """,
            lid=lid,
            pid=craig,
        )


async def test_join_requests_only_one_pending(db_conn: AsyncConnection) -> None:
    craig = await _make_profile(db_conn, "Craig", role="admin")
    alice = await _make_profile(db_conn, "Alice")
    lid = await _scalar(
        db_conn,
        """
        INSERT INTO leagues (id, slug, name, created_by)
        VALUES (gen_random_uuid(), 'test-jr', 'Test JR', :cb)
        RETURNING id
        """,
        cb=craig,
    )
    await _exec(
        db_conn,
        """
        INSERT INTO league_join_requests (id, league_id, player_id)
        VALUES (gen_random_uuid(), :lid, :pid)
        """,
        lid=lid,
        pid=alice,
    )
    with pytest.raises(Exception):
        await _exec(
            db_conn,
            """
            INSERT INTO league_join_requests (id, league_id, player_id)
            VALUES (gen_random_uuid(), :lid, :pid)
            """,
            lid=lid,
            pid=alice,
        )


async def test_max_members_check_constraint(db_conn: AsyncConnection) -> None:
    craig = await _make_profile(db_conn, "Craig", role="admin")
    with pytest.raises(Exception):
        await _exec(
            db_conn,
            """
            INSERT INTO leagues (id, slug, name, created_by, max_members)
            VALUES (gen_random_uuid(), 'too-big', 'Too Big', :cb, 51)
            """,
            cb=craig,
        )
    with pytest.raises(Exception):
        await _exec(
            db_conn,
            """
            INSERT INTO leagues (id, slug, name, created_by, max_members)
            VALUES (gen_random_uuid(), 'too-small', 'Too Small', :cb, 1)
            """,
            cb=craig,
        )


# ---------------------------------------------------------------------------
# Backfill behaviour — uses the run_backfill driver directly.
# ---------------------------------------------------------------------------


async def test_backfill_creates_steele_with_craig_admin(
    db_conn: AsyncConnection,
) -> None:
    craig = await _make_profile(db_conn, "Craig", role="admin")
    lewis = await _make_profile(db_conn, "Lewis", role="player")
    await _make_profile(db_conn, "Alice Wong", role="player")

    sidecar = {
        craig: SidecarEntry(email="craigr973@sky.com", first_name="Craig", last_name="R"),
        lewis: SidecarEntry(email="lewis@example.com", first_name="Lewis", last_name="S"),
    }
    summary = await run_backfill(db_conn, sidecar)

    assert summary.league_created is True
    assert summary.admin_membership_count == 1
    assert summary.memberships_created == 3
    assert summary.profiles_updated == 3
    assert summary.warnings == []

    # Steele league materialises with the expected shape.
    league = await _scalar_or_none(
        db_conn,
        "SELECT row_to_json(l) FROM leagues l WHERE slug = 'steele-spreadsheet'",
    )
    assert league is not None
    assert league["name"] == "The Steele Spreadsheet"
    assert league["privacy"] == "private"
    assert league["max_members"] == 15

    # Craig is the only admin; Lewis and Alice are players.
    members = await _fetchall(
        db_conn,
        """
        SELECT p.display_name, m.role
        FROM league_memberships m
        JOIN profiles p ON p.id = m.player_id
        JOIN leagues l ON l.id = m.league_id
        WHERE l.slug = 'steele-spreadsheet'
        ORDER BY p.display_name
        """,
    )
    assert [(m["display_name"], m["role"]) for m in members] == [
        ("Alice Wong", "player"),
        ("Craig", "admin"),
        ("Lewis", "player"),
    ]

    # Profiles got first/last/email + Craig is verified, others are not.
    profiles = await _fetchall(
        db_conn,
        """
        SELECT display_name, email, first_name, last_name, site_role,
               email_verified_at IS NOT NULL AS verified
        FROM profiles
        WHERE display_name IN ('Craig', 'Lewis', 'Alice Wong')
        ORDER BY display_name
        """,
    )
    by_name = {p["display_name"]: p for p in profiles}
    assert by_name["Craig"]["email"] == "craigr973@sky.com"
    assert by_name["Craig"]["site_role"] == "superadmin"
    assert by_name["Craig"]["verified"] is True
    assert by_name["Lewis"]["email"] == "lewis@example.com"
    assert by_name["Lewis"]["site_role"] == "user"
    assert by_name["Lewis"]["verified"] is False
    # Alice was not in the sidecar — derived from display_name.
    assert by_name["Alice Wong"]["email"] == "pending+alice-wong@steele.invalid"
    assert by_name["Alice Wong"]["first_name"] == "Alice"
    assert by_name["Alice Wong"]["last_name"] == "Wong"
    assert by_name["Alice Wong"]["site_role"] == "user"


async def test_backfill_is_idempotent(db_conn: AsyncConnection) -> None:
    craig = await _make_profile(db_conn, "Craig", role="admin")
    lewis = await _make_profile(db_conn, "Lewis", role="player")
    sidecar = {
        craig: SidecarEntry(email="craigr973@sky.com"),
        lewis: SidecarEntry(email="lewis@example.com"),
    }
    s1 = await run_backfill(db_conn, sidecar)
    s2 = await run_backfill(db_conn, sidecar)

    # Second run finds the league already there; no new memberships.
    assert s2.league_created is False
    assert s2.memberships_created == 0
    assert s2.memberships_existing == s1.memberships_created
    assert s2.admin_membership_count == 1

    # Exactly one Steele row, two memberships.
    league_count = await _scalar(
        db_conn, "SELECT count(*) FROM leagues WHERE slug = 'steele-spreadsheet'"
    )
    member_count = await _scalar(
        db_conn,
        """
        SELECT count(*) FROM league_memberships m
        JOIN leagues l ON l.id = m.league_id
        WHERE l.slug = 'steele-spreadsheet'
        """,
    )
    assert league_count == 1
    assert member_count == 2


async def test_backfill_restores_soft_deleted_membership(
    db_conn: AsyncConnection,
) -> None:
    craig = await _make_profile(db_conn, "Craig", role="admin")
    lewis = await _make_profile(db_conn, "Lewis", role="player")
    sidecar = {
        craig: SidecarEntry(email="craigr973@sky.com"),
        lewis: SidecarEntry(email="lewis@example.com"),
    }
    await run_backfill(db_conn, sidecar)

    # Soft-delete Lewis's membership and re-run; the script should restore it.
    await _exec(
        db_conn,
        """
        UPDATE league_memberships SET deleted_at = NOW()
        WHERE player_id = :pid
        """,
        pid=lewis,
    )
    summary = await run_backfill(db_conn, sidecar)
    assert summary.memberships_existing == 2

    deleted_at = await _scalar(
        db_conn,
        """
        SELECT deleted_at FROM league_memberships
        WHERE player_id = :pid
        """,
        pid=lewis,
    )
    assert deleted_at is None


async def test_backfill_aborts_if_no_admin(db_conn: AsyncConnection) -> None:
    await _make_profile(db_conn, "Lewis", role="player")
    with pytest.raises(RuntimeError, match="No active profile with display_name = 'Craig'"):
        await run_backfill(db_conn, {})


async def test_backfill_aborts_if_privacy_not_private(
    db_conn: AsyncConnection,
) -> None:
    craig = await _make_profile(db_conn, "Craig", role="admin")
    await _make_profile(db_conn, "Lewis", role="player")
    # Pre-create the league with wrong privacy — backfill should refuse to commit.
    await _exec(
        db_conn,
        """
        INSERT INTO leagues (id, slug, name, privacy, created_by)
        VALUES (gen_random_uuid(), 'steele-spreadsheet', 'The Steele Spreadsheet',
                CAST('public_open' AS league_privacy), :cb)
        """,
        cb=craig,
    )
    with pytest.raises(RuntimeError, match="privacy is 'public_open'"):
        await run_backfill(db_conn, {})


async def test_backfill_skips_soft_deleted_profiles(
    db_conn: AsyncConnection,
) -> None:
    craig = await _make_profile(db_conn, "Craig", role="admin")
    ghost = await _make_profile(db_conn, "Ghost", role="player")
    await _exec(
        db_conn,
        "UPDATE profiles SET deleted_at = NOW() WHERE id = :id",
        id=ghost,
    )
    summary = await run_backfill(db_conn, {craig: SidecarEntry(email="craigr973@sky.com")})
    assert summary.profiles_total == 1
    assert summary.memberships_created == 1
    # Ghost did not get a membership.
    member_for_ghost = await _scalar(
        db_conn,
        "SELECT count(*) FROM league_memberships WHERE player_id = :pid",
        pid=ghost,
    )
    assert member_for_ghost == 0
