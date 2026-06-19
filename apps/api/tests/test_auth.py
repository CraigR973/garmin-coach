"""Tests for auth endpoints: login, refresh, logout, and FastAPI dependencies."""

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import jwt as pyjwt
import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import (
    create_access_token,
    create_refresh_token,
    hash_pin,
    hash_token,
    require_admin,
    verify_pin,
)
from src.config import settings
from src.database import get_db
from src.main import app
from src.models.profile import PlayerRole, Profile, SiteRole
from src.models.refresh_token import RefreshToken

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _make_player(
    role: PlayerRole = PlayerRole.player,
    failed: int = 0,
    locked_until: datetime | None = None,
    avatar_url: str | None = None,
) -> Profile:
    p = MagicMock(spec=Profile)
    p.avatar_url = avatar_url
    p.id = uuid.uuid4()
    p.display_name = "Test Player"
    p.email = "testplayer@example.com"
    p.pin_hash = hash_pin("1234")
    p.role = role
    # Keep site_role consistent with role: admin ↔ superadmin, player ↔ user.
    p.site_role = SiteRole.superadmin if role == PlayerRole.admin else SiteRole.user
    p.timezone = "UTC"
    p.failed_login_count = failed
    p.locked_until = locked_until
    p.deleted_at = None
    return p


def _make_refresh_record(player_id: uuid.UUID, refresh_jwt: str) -> MagicMock:
    r = MagicMock(spec=RefreshToken)
    r.id = uuid.uuid4()
    r.player_id = player_id
    r.token_hash = hash_token(refresh_jwt)
    r.device_hint = "TestAgent"
    r.expires_at = _now() + timedelta(days=30)
    r.revoked_at = None
    return r


def _stub_db(execute_results: list) -> AsyncMock:
    """Build a mock AsyncSession with sequential execute() return values."""
    mock_db = AsyncMock(spec=AsyncSession)
    mock_db.execute = AsyncMock(side_effect=execute_results)
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()
    mock_db.add = MagicMock()
    return mock_db


def _scalar(value: object) -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


@asynccontextmanager
async def _override_db(mock_db: AsyncMock) -> AsyncGenerator[None, None]:
    """Temporarily override the get_db dependency."""

    async def _fake_db() -> AsyncGenerator[AsyncSession, None]:
        yield mock_db

    app.dependency_overrides[get_db] = _fake_db
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture
async def client() -> AsyncClient:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# Unit tests — bcrypt / JWT helpers
# ---------------------------------------------------------------------------


def test_hash_and_verify_pin() -> None:
    h = hash_pin("9876")
    assert verify_pin("9876", h)
    assert not verify_pin("0000", h)


def test_access_token_roundtrip() -> None:
    player_id = uuid.uuid4()
    token = create_access_token(player_id, PlayerRole.admin)
    payload = pyjwt.decode(token, settings.jwt_access_secret, algorithms=["HS256"])
    assert payload["sub"] == str(player_id)
    assert payload["role"] == "admin"


def test_refresh_token_roundtrip() -> None:
    player_id = uuid.uuid4()
    record_id = uuid.uuid4()
    token = create_refresh_token(player_id, record_id)
    payload = pyjwt.decode(token, settings.jwt_refresh_secret, algorithms=["HS256"])
    assert payload["sub"] == str(player_id)
    assert payload["jti"] == str(record_id)


# ---------------------------------------------------------------------------
# Login endpoint
# ---------------------------------------------------------------------------


async def test_login_success(client: AsyncClient) -> None:
    avatar_url = "https://example.supabase.co/storage/v1/object/public/avatars/p1/face.jpg"
    player = _make_player(role=PlayerRole.admin, avatar_url=avatar_url)
    mock_db = _stub_db([_scalar(player), _scalar(None)])  # login lookup + any extra
    # add() + commit() will be called for the refresh token record

    async with _override_db(mock_db):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "testplayer@example.com", "pin": "1234"},
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["player"]["role"] == "admin"
    assert data["player"]["display_name"] == "Test Player"
    assert data["player"]["avatar_url"] == avatar_url


async def test_login_wrong_pin(client: AsyncClient) -> None:
    player = _make_player()
    mock_db = _stub_db([_scalar(player)])

    async with _override_db(mock_db):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "testplayer@example.com", "pin": "0000"},
        )

    assert resp.status_code == 401


async def test_login_player_not_found(client: AsyncClient) -> None:
    mock_db = _stub_db([_scalar(None)])

    async with _override_db(mock_db):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@example.com", "pin": "1234"},
        )

    assert resp.status_code == 401


async def test_login_wrong_pin_no_lockout(client: AsyncClient) -> None:
    """Wrong PIN always returns 401 — no lockout, no counter increment."""
    player = _make_player(failed=99)  # even with high count, no lockout
    mock_db = _stub_db([_scalar(player)])

    async with _override_db(mock_db):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "testplayer@example.com", "pin": "9999"},
        )

    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid credentials"


# ---------------------------------------------------------------------------
# Refresh endpoint
# ---------------------------------------------------------------------------


async def test_refresh_success(client: AsyncClient) -> None:
    player = _make_player()
    record_id = uuid.uuid4()
    refresh_jwt = create_refresh_token(player.id, record_id)
    token_record = _make_refresh_record(player.id, refresh_jwt)
    token_record.id = record_id

    mock_db = _stub_db([_scalar(token_record), _scalar(player)])

    async with _override_db(mock_db):
        resp = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_jwt},
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["refresh_token"] != refresh_jwt  # rotation happened
    assert token_record.revoked_at is not None


async def test_refresh_invalid_token(client: AsyncClient) -> None:
    mock_db = _stub_db([])

    async with _override_db(mock_db):
        resp = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": "not.a.jwt"},
        )

    assert resp.status_code == 401


async def test_refresh_revoked_token(client: AsyncClient) -> None:
    player = _make_player()
    record_id = uuid.uuid4()
    refresh_jwt = create_refresh_token(player.id, record_id)

    mock_db = _stub_db([_scalar(None)])  # token not found / revoked

    async with _override_db(mock_db):
        resp = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_jwt},
        )

    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Logout endpoint
# ---------------------------------------------------------------------------


async def test_logout_success(client: AsyncClient) -> None:
    player = _make_player()
    record_id = uuid.uuid4()
    refresh_jwt = create_refresh_token(player.id, record_id)
    token_record = _make_refresh_record(player.id, refresh_jwt)

    mock_db = _stub_db([_scalar(token_record)])

    async with _override_db(mock_db):
        resp = await client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": refresh_jwt},
        )

    assert resp.status_code == 204
    assert token_record.revoked_at is not None


async def test_logout_bad_token_still_204(client: AsyncClient) -> None:
    """Logout must always return 204 — even with a garbage token."""
    mock_db = _stub_db([])

    async with _override_db(mock_db):
        resp = await client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": "garbage"},
        )

    assert resp.status_code == 204


# ---------------------------------------------------------------------------
# Auth dependency — require_admin
# ---------------------------------------------------------------------------


async def test_require_admin_rejects_player_role() -> None:
    """require_admin raises 403 for a player-role token."""
    player = _make_player(role=PlayerRole.player)

    with pytest.raises(HTTPException) as exc_info:
        await require_admin(player)

    assert exc_info.value.status_code == 403


async def test_require_admin_passes_admin_role() -> None:
    """require_admin returns the player when site_role is superadmin."""
    from src.auth import require_admin

    player = _make_player(role=PlayerRole.admin)  # sets site_role=superadmin via _make_player
    result = await require_admin(player)
    assert result is player
