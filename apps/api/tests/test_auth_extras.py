"""Tests for GET /auth/me, PATCH /auth/me, PUT /auth/me/pin, POST /admin/players/{id}/reset-pin."""

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_player, hash_pin, require_admin
from src.database import get_db
from src.main import app
from src.models.profile import PlayerRole, Profile


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _make_player(*, role: PlayerRole = PlayerRole.player) -> MagicMock:
    p = MagicMock(spec=Profile)
    p.id = uuid.uuid4()
    p.display_name = "TestPlayer"
    p.role = role
    p.timezone = "Europe/London"
    p.pin_hash = hash_pin("1234")
    p.deleted_at = None
    p.created_at = _now()
    p.avatar_url = None  # U23: prevent MagicMock default from failing Pydantic
    return p


def _stub_db(execute_results: list) -> AsyncMock:
    mock_db = AsyncMock(spec=AsyncSession)
    mock_db.execute = AsyncMock(side_effect=execute_results)
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock(side_effect=lambda obj: None)
    mock_db.add = MagicMock()
    return mock_db


def _scalar(value: object) -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


@asynccontextmanager
async def _override_player(player: Profile) -> AsyncGenerator[None, None]:
    async def _fake_player() -> Profile:
        return player

    app.dependency_overrides[get_current_player] = _fake_player
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_current_player, None)


@asynccontextmanager
async def _override_db_and_admin(mock_db: AsyncMock, admin: Profile) -> AsyncGenerator[None, None]:
    async def _fake_db() -> AsyncGenerator[AsyncSession, None]:
        yield mock_db

    async def _fake_admin() -> Profile:
        return admin

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[require_admin] = _fake_admin
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(require_admin, None)


@pytest.fixture
async def client() -> AsyncClient:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# GET /api/v1/auth/me
# ---------------------------------------------------------------------------


async def test_me_returns_player_info(client: AsyncClient) -> None:
    player = _make_player()
    async with _override_player(player):
        resp = await client.get("/api/v1/auth/me")

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["id"] == str(player.id)
    assert data["display_name"] == "TestPlayer"
    assert data["role"] == "player"
    assert data["timezone"] == "Europe/London"


async def test_me_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# PUT /api/v1/auth/me/pin
# ---------------------------------------------------------------------------


async def test_change_pin_success(client: AsyncClient) -> None:
    player = _make_player()
    mock_db = _stub_db([])

    async def _fake_db() -> AsyncGenerator[AsyncSession, None]:
        yield mock_db

    async def _fake_player() -> Profile:
        return player

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_current_player] = _fake_player
    try:
        resp = await client.put(
            "/api/v1/auth/me/pin",
            json={"current_pin": "1234", "new_pin": "5678"},
        )
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_player, None)

    assert resp.status_code == 204, resp.text
    mock_db.commit.assert_called_once()


async def test_change_pin_wrong_current(client: AsyncClient) -> None:
    player = _make_player()
    mock_db = _stub_db([])

    async def _fake_db() -> AsyncGenerator[AsyncSession, None]:
        yield mock_db

    async def _fake_player() -> Profile:
        return player

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_current_player] = _fake_player
    try:
        resp = await client.put(
            "/api/v1/auth/me/pin",
            json={"current_pin": "9999", "new_pin": "5678"},
        )
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_player, None)

    assert resp.status_code == 401
    mock_db.commit.assert_not_called()


# ---------------------------------------------------------------------------
# POST /api/v1/admin/players/{id}/reset-pin
# ---------------------------------------------------------------------------


async def test_reset_pin_returns_temp_pin(client: AsyncClient) -> None:
    admin = _make_player(role=PlayerRole.admin)
    player = _make_player()
    mock_db = _stub_db([_scalar(player)])

    async with _override_db_and_admin(mock_db, admin):
        resp = await client.post(f"/api/v1/admin/players/{player.id}/reset-pin")

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "temp_pin" in data
    assert len(data["temp_pin"]) == 6
    assert data["temp_pin"].isdigit()
    mock_db.commit.assert_called_once()


async def test_reset_pin_player_not_found(client: AsyncClient) -> None:
    admin = _make_player(role=PlayerRole.admin)
    mock_db = _stub_db([_scalar(None)])

    async with _override_db_and_admin(mock_db, admin):
        resp = await client.post(f"/api/v1/admin/players/{uuid.uuid4()}/reset-pin")

    assert resp.status_code == 404


async def test_reset_pin_requires_admin(client: AsyncClient) -> None:
    resp = await client.post(f"/api/v1/admin/players/{uuid.uuid4()}/reset-pin")
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# PATCH /api/v1/auth/me — update profile (GAP-06: timezone)
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _override_db_and_player(
    mock_db: AsyncMock, player: Profile
) -> AsyncGenerator[None, None]:
    async def _fake_db() -> AsyncGenerator[AsyncSession, None]:
        yield mock_db

    async def _fake_player() -> Profile:
        return player

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_current_player] = _fake_player
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_player, None)


async def test_update_profile_timezone_success(client: AsyncClient) -> None:
    player = _make_player()
    mock_db = _stub_db([MagicMock()])  # execute() for the UPDATE

    async with _override_db_and_player(mock_db, player):
        resp = await client.patch("/api/v1/auth/me", json={"timezone": "America/New_York"})

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["timezone"] == "America/New_York"
    mock_db.commit.assert_called_once()


async def test_update_profile_invalid_timezone_returns_422(client: AsyncClient) -> None:
    player = _make_player()
    mock_db = _stub_db([])

    async with _override_db_and_player(mock_db, player):
        resp = await client.patch("/api/v1/auth/me", json={"timezone": "Not/ATimezone"})

    assert resp.status_code == 422


async def test_update_profile_requires_auth(client: AsyncClient) -> None:
    resp = await client.patch("/api/v1/auth/me", json={"timezone": "UTC"})
    assert resp.status_code in (401, 403)
