"""DB-backed guards for the profile-creating write paths.

The mock-based suites (test_join, test_bootstrap_admin, test_auth_m4) stub
``session.add`` with a MagicMock, so a migration that adds a NOT NULL / enum
column the code forgets to populate passes those tests but fails the real
INSERT in staging. That exact drift produced the run of reactive fixes
(``fix(bootstrap)`` NOT NULL, ``fix(auth)`` site_role, ``fix(invite)`` join
fields).

These tests run the *actual* INSERT statements — bootstrap ``create_admin``,
``POST /auth/signup``, ``POST /auth/join`` — against a live Postgres migrated to
head, so the same drift fails CI instead. They skip automatically when
DATABASE_URL is unset (see conftest ``db_engine``); CI provides Postgres and
runs ``alembic upgrade head`` first.

The endpoints call ``session.commit()``; binding the session with
``join_transaction_mode="create_savepoint"`` keeps those commits inside the
``db_conn`` transaction so the fixture's rollback still cleans up.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.auth import create_access_token
from src.bootstrap_admin import create_admin
from src.database import get_db
from src.main import app
from src.models.profile import PlayerRole

pytestmark = pytest.mark.asyncio

# A throwaway bcrypt-shaped hash; pin_hash is an unvalidated String column.
_FAKE_PIN_HASH = "$2b$12$0000000000000000000000000000000000000000000000000000"


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


def _savepoint_session(conn: AsyncConnection) -> AsyncSession:
    """A session whose commits release a savepoint instead of the outer tx."""
    return AsyncSession(
        bind=conn,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )


def _override_db(session: AsyncSession):  # type: ignore[no-untyped-def]
    async def _gen() -> AsyncIterator[AsyncSession]:
        yield session

    return _gen


async def _insert_profile(
    conn: AsyncConnection,
    *,
    display_name: str,
    email: str,
    role: str = "player",
    site_role: str = "user",
) -> uuid.UUID:
    return (
        await conn.execute(
            text(
                """
                INSERT INTO profiles (
                    id, display_name, pin_hash, role, email,
                    first_name, last_name, site_role
                )
                VALUES (
                    gen_random_uuid(), :dn, :h, CAST(:role AS player_role),
                    :email, 'WG', 'User', CAST(:sr AS site_role)
                )
                RETURNING id
                """
            ),
            {
                "dn": display_name,
                "h": _FAKE_PIN_HASH,
                "role": role,
                "email": email,
                "sr": site_role,
            },
        )
    ).scalar_one()


# ---------------------------------------------------------------------------
# Bootstrap admin (service-level; uses flush(), already hermetic)
# ---------------------------------------------------------------------------


async def test_bootstrap_create_admin_inserts_real_row(db_conn: AsyncConnection) -> None:
    sfx = _suffix()
    session = _savepoint_session(db_conn)
    try:
        profile = await create_admin(
            session,
            display_name=f"WG Admin {sfx}",
            pin="1234",
            timezone="Europe/London",
            email=f"wg-admin-{sfx}@writeguard.invalid",
        )
        # The INSERT really hit Postgres (flush), so all NOT NULL / enum columns
        # were satisfied. Confirm the row + its FK-dependent prefs row exist.
        row = (
            await db_conn.execute(
                text("SELECT email, first_name, last_name, site_role FROM profiles WHERE id = :id"),
                {"id": str(profile.id)},
            )
        ).first()
        assert row is not None and row.email == f"wg-admin-{sfx}@writeguard.invalid"
        prefs = (
            await db_conn.execute(
                text("SELECT 1 FROM notification_preferences WHERE player_id = :id"),
                {"id": str(profile.id)},
            )
        ).first()
        assert prefs is not None
    finally:
        await session.close()


# ---------------------------------------------------------------------------
# Signup endpoint (commits; savepoint-bound)
# ---------------------------------------------------------------------------


async def test_signup_endpoint_inserts_real_profile(db_conn: AsyncConnection) -> None:
    sfx = _suffix()
    email = f"wg-signup-{sfx}@writeguard.invalid"
    session = _savepoint_session(db_conn)
    app.dependency_overrides[get_db] = _override_db(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/auth/signup",
                json={
                    "email": email,
                    "first_name": "Write",
                    "last_name": "Guard",
                    "pin": "4321",
                    "timezone": "Europe/London",
                },
            )
    finally:
        app.dependency_overrides.clear()
        await session.close()

    assert resp.status_code == 201, resp.text
    row = (
        await db_conn.execute(
            text("SELECT site_role, first_name, last_name FROM profiles WHERE email = :e"),
            {"e": email},
        )
    ).first()
    assert row is not None, "signup did not persist a profile row"


# ---------------------------------------------------------------------------
# Join endpoint (commits; needs a real invite + league; savepoint-bound)
# ---------------------------------------------------------------------------


@patch("src.routers.auth.notify_invite_accepted", new_callable=AsyncMock)
async def test_join_endpoint_inserts_profile_and_membership(
    _notify: AsyncMock, db_conn: AsyncConnection
) -> None:
    sfx = _suffix()
    creator = await _insert_profile(
        db_conn,
        display_name=f"WG Creator {sfx}",
        email=f"wg-creator-{sfx}@writeguard.invalid",
        role="admin",
        site_role="superadmin",
    )
    league_id = (
        await db_conn.execute(
            text(
                """
                INSERT INTO leagues (id, slug, name, created_by)
                VALUES (gen_random_uuid(), :slug, :name, :c)
                RETURNING id
                """
            ),
            {"slug": f"wg-{sfx}", "name": f"WG League {sfx}", "c": str(creator)},
        )
    ).scalar_one()
    token = f"wgtok{sfx}"
    await db_conn.execute(
        text(
            """
            INSERT INTO invites (id, token, league_id, created_by, is_active)
            VALUES (gen_random_uuid(), :t, :l, :c, true)
            """
        ),
        {"t": token, "l": str(league_id), "c": str(creator)},
    )

    display_name = f"WG Joiner {sfx}"
    session = _savepoint_session(db_conn)
    app.dependency_overrides[get_db] = _override_db(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/auth/join",
                json={
                    "token": token,
                    "display_name": display_name,
                    "pin": "5678",
                    "timezone": "Europe/London",
                },
            )
    finally:
        app.dependency_overrides.clear()
        await session.close()

    assert resp.status_code == 201, resp.text
    membership = (
        await db_conn.execute(
            text(
                """
                SELECT 1
                FROM league_memberships lm
                JOIN profiles p ON p.id = lm.player_id
                WHERE lm.league_id = :l AND p.display_name = :dn
                """
            ),
            {"l": str(league_id), "dn": display_name},
        )
    ).first()
    assert membership is not None, "join did not create profile + membership rows"


# ---------------------------------------------------------------------------
# Dup-join guard: ALREADY_MEMBER + re-join after leave
# ---------------------------------------------------------------------------


async def _insert_open_league(
    conn: AsyncConnection, *, creator_id: uuid.UUID
) -> tuple[uuid.UUID, str]:
    """Insert a public_open league and return (league_id, slug)."""
    sfx = _suffix()
    slug = f"dj-{sfx}"
    code = sfx[:6].upper()  # VARCHAR(8) limit; _suffix() is hex, 6 chars safe
    league_id = (
        await conn.execute(
            text(
                """
                INSERT INTO leagues (id, slug, name, created_by, privacy, join_code)
                VALUES (gen_random_uuid(), :slug, :name, :c,
                        CAST('public_open' AS league_privacy), :code)
                RETURNING id
                """
            ),
            {"slug": slug, "name": f"DJ League {sfx}", "c": str(creator_id), "code": code},
        )
    ).scalar_one()
    return league_id, slug


async def test_dup_join_guard_already_member(db_conn: AsyncConnection) -> None:
    """Second join attempt on the same open league returns 409 ALREADY_MEMBER."""
    sfx = _suffix()
    # Create a player profile
    player_id = await _insert_profile(
        db_conn,
        display_name=f"DJ Player {sfx}",
        email=f"dj-player-{sfx}@writeguard.invalid",
    )
    creator_id = await _insert_profile(
        db_conn,
        display_name=f"DJ Creator {sfx}",
        email=f"dj-creator-{sfx}@writeguard.invalid",
        role="admin",
        site_role="superadmin",
    )
    league_id, slug = await _insert_open_league(db_conn, creator_id=creator_id)

    token = create_access_token(player_id, PlayerRole.player)
    headers = {"Authorization": f"Bearer {token}"}

    session = _savepoint_session(db_conn)
    app.dependency_overrides[get_db] = _override_db(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # First join — should succeed
            resp1 = await client.post(f"/api/v1/leagues/{slug}/join", headers=headers)
            assert resp1.status_code == 200, resp1.text

            # Second join — must be rejected
            resp2 = await client.post(f"/api/v1/leagues/{slug}/join", headers=headers)
            assert resp2.status_code == 409
            assert "ALREADY_MEMBER" in resp2.json()["detail"]
    finally:
        app.dependency_overrides.clear()
        await session.close()

    # Confirm only one membership row exists (no duplicate)
    count = (
        await db_conn.execute(
            text("SELECT COUNT(*) FROM league_memberships WHERE league_id = :l AND player_id = :p"),
            {"l": str(league_id), "p": str(player_id)},
        )
    ).scalar_one()
    assert count == 1, "duplicate league_membership row was inserted"


async def test_rejoin_after_leave_restores_soft_deleted_row(db_conn: AsyncConnection) -> None:
    """Leaving and re-joining the same league reactivates the soft-deleted row (upsert)."""
    sfx = _suffix()
    player_id = await _insert_profile(
        db_conn,
        display_name=f"RJ Player {sfx}",
        email=f"rj-player-{sfx}@writeguard.invalid",
    )
    creator_id = await _insert_profile(
        db_conn,
        display_name=f"RJ Creator {sfx}",
        email=f"rj-creator-{sfx}@writeguard.invalid",
        role="admin",
        site_role="superadmin",
    )
    league_id, slug = await _insert_open_league(db_conn, creator_id=creator_id)

    token = create_access_token(player_id, PlayerRole.player)
    headers = {"Authorization": f"Bearer {token}"}

    session = _savepoint_session(db_conn)
    app.dependency_overrides[get_db] = _override_db(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # Join
            resp = await client.post(f"/api/v1/leagues/{slug}/join", headers=headers)
            assert resp.status_code == 200, resp.text

            # Leave
            resp = await client.delete(f"/api/v1/leagues/{slug}/membership", headers=headers)
            assert resp.status_code == 204, resp.text

            # Re-join — must succeed, not 409
            resp = await client.post(f"/api/v1/leagues/{slug}/join", headers=headers)
            assert resp.status_code == 200, resp.text
    finally:
        app.dependency_overrides.clear()
        await session.close()

    # Still only one row (upsert restored it, no second insert)
    count = (
        await db_conn.execute(
            text("SELECT COUNT(*) FROM league_memberships WHERE league_id = :l AND player_id = :p"),
            {"l": str(league_id), "p": str(player_id)},
        )
    ).scalar_one()
    assert count == 1, "upsert created a second row instead of restoring the soft-deleted one"

    # Row must be active (deleted_at NULL)
    deleted_at = (
        await db_conn.execute(
            text(
                "SELECT deleted_at FROM league_memberships WHERE league_id = :l AND player_id = :p"
            ),
            {"l": str(league_id), "p": str(player_id)},
        )
    ).scalar_one()
    assert deleted_at is None, "re-joined membership was not reactivated (deleted_at still set)"
