"""Tests for R3: rate limiting (R3.1/R3.2), login enumeration fix (R3.3), is_active (R3.4)."""

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import (
    create_access_token,
    get_current_player,
    hash_pin,
    require_admin,
)
from src.database import get_db
from src.main import app
from src.models.profile import PlayerRole, Profile
from src.routers.leagues import require_league_member

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _make_player(
    player_id: uuid.UUID | None = None,
    role: PlayerRole = PlayerRole.player,
) -> MagicMock:
    p = MagicMock(spec=Profile)
    p.avatar_url = None  # U23: prevent MagicMock default from failing Pydantic
    p.id = player_id or uuid.uuid4()
    p.display_name = "TestPlayer"
    p.pin_hash = hash_pin("1234")
    p.role = role
    p.timezone = "UTC"
    p.failed_login_count = 0
    p.locked_until = None
    p.deleted_at = None
    p.is_active = True
    return p


def _make_db() -> AsyncMock:
    mock_db = AsyncMock(spec=AsyncSession)
    r = MagicMock()
    r.scalar_one_or_none.return_value = None
    r.scalar.return_value = 0
    r.scalars.return_value.all.return_value = []
    r.mappings.return_value.all.return_value = []
    mock_db.execute = AsyncMock(return_value=r)
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    return mock_db


@asynccontextmanager
async def _override_auth(player: MagicMock) -> AsyncGenerator[None, None]:
    async def _fake() -> Profile:
        return player

    app.dependency_overrides[get_current_player] = _fake
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_current_player, None)


@asynccontextmanager
async def _override_member(player: MagicMock) -> AsyncGenerator[None, None]:
    league = MagicMock()
    league.id = uuid.uuid4()

    def _fake() -> tuple[MagicMock, MagicMock]:
        return player, league

    app.dependency_overrides[require_league_member] = _fake
    try:
        yield
    finally:
        app.dependency_overrides.pop(require_league_member, None)


@asynccontextmanager
async def _override_admin(player: MagicMock) -> AsyncGenerator[None, None]:
    async def _fake() -> Profile:
        return player

    app.dependency_overrides[require_admin] = _fake
    try:
        yield
    finally:
        app.dependency_overrides.pop(require_admin, None)


@asynccontextmanager
async def _override_db(mock_db: AsyncMock) -> AsyncGenerator[None, None]:
    async def _fake_db() -> AsyncGenerator[AsyncSession, None]:
        yield mock_db

    app.dependency_overrides[get_db] = _fake_db
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_db, None)


def _bearer(player_id: uuid.UUID, role: PlayerRole = PlayerRole.player) -> dict[str, str]:
    """Return Authorization header with a real JWT for the given player."""
    token = create_access_token(player_id, role)
    return {"Authorization": f"Bearer {token}"}


async def _exhaust_then_check(
    client: AsyncClient,
    method: str,
    url: str,
    threshold: int,
    *,
    headers: dict | None = None,
    json: dict | None = None,
) -> int:
    """Send *threshold* requests to fill the bucket, then one more; return its status code."""
    kw: dict = {}
    if headers:
        kw["headers"] = headers
    if json is not None:
        kw["json"] = json
    for _ in range(threshold):
        if method == "GET":
            await client.get(url, **kw)
        elif method == "POST":
            await client.post(url, **kw)
        else:
            await client.request(method, url, **kw)
    if method == "GET":
        resp = await client.get(url, **kw)
    elif method == "POST":
        resp = await client.post(url, **kw)
    else:
        resp = await client.request(method, url, **kw)
    return resp.status_code


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# R3.2 — One 429 test per rate-limited endpoint (parameterised by fixture)
# ---------------------------------------------------------------------------


async def test_rate_limit_login(client: AsyncClient) -> None:
    """POST /auth/login: 5/15 min per email:ip → 429 on 6th request."""
    email = f"rl-{uuid.uuid4().hex[:8]}@example.com"
    ip = f"10.{uuid.uuid4().int & 0xFF}.0.1"
    body = {"email": email, "pin": "1234"}
    async with _override_db(_make_db()):
        status = await _exhaust_then_check(
            client,
            "POST",
            "/api/v1/auth/login",
            5,
            headers={"X-Forwarded-For": ip},
            json=body,
        )
    assert status == 429


async def test_rate_limit_join(client: AsyncClient) -> None:
    """POST /auth/join: 3/hour per IP → 429 on 4th request."""
    ip = f"10.{uuid.uuid4().int & 0xFF}.1.1"
    body = {"token": "invalid", "display_name": "JoinUser", "pin": "1234"}
    async with _override_db(_make_db()):
        status = await _exhaust_then_check(
            client,
            "POST",
            "/api/v1/auth/join",
            3,
            headers={"X-Forwarded-For": ip},
            json=body,
        )
    assert status == 429


async def test_rate_limit_refresh(client: AsyncClient) -> None:
    """POST /auth/refresh: 60/hour per token-hash → 429 on 61st request."""
    fixed_token = f"testtoken-{uuid.uuid4().hex}"
    async with _override_db(_make_db()):
        status = await _exhaust_then_check(
            client,
            "POST",
            "/api/v1/auth/refresh",
            60,
            json={"refresh_token": fixed_token},
        )
    assert status == 429


async def test_rate_limit_pin_change(client: AsyncClient) -> None:
    """PUT /auth/me/pin: 3/hour per player → 429 on 4th request."""
    player_id = uuid.uuid4()
    player = _make_player(player_id)
    body = {"current_pin": "1234", "new_pin": "5678"}
    async with _override_auth(player), _override_db(_make_db()):
        status = await _exhaust_then_check(
            client,
            "PUT",
            "/api/v1/auth/me/pin",
            3,
            headers=_bearer(player_id),
            json=body,
        )
    assert status == 429


async def test_rate_limit_predictions(client: AsyncClient) -> None:
    """PUT /predictions/{match_id}: 60/hour per player → 429 on 61st request."""
    player_id = uuid.uuid4()
    player = _make_player(player_id)
    match_id = uuid.uuid4()
    body = {"predicted_home": 2, "predicted_away": 1}
    async with _override_auth(player), _override_db(_make_db()):
        status = await _exhaust_then_check(
            client,
            "PUT",
            f"/api/v1/predictions/{match_id}",
            60,
            headers=_bearer(player_id),
            json=body,
        )
    assert status == 429


async def test_rate_limit_knockout_predictions(client: AsyncClient) -> None:
    """PUT /knockout-predictions/{match_id}: 60/hour per player → 429 on 61st request."""
    player_id = uuid.uuid4()
    player = _make_player(player_id)
    match_id = uuid.uuid4()
    body = {"predicted_winner_id": str(uuid.uuid4())}
    async with _override_auth(player), _override_db(_make_db()):
        status = await _exhaust_then_check(
            client,
            "PUT",
            f"/api/v1/knockout-predictions/{match_id}",
            60,
            headers=_bearer(player_id),
            json=body,
        )
    assert status == 429


async def test_rate_limit_league_leaderboard(client: AsyncClient) -> None:
    """GET /leagues/{slug}/leaderboard: 120/minute per player → 429 on 121st request."""
    player_id = uuid.uuid4()
    player = _make_player(player_id)
    empty_db = AsyncMock(spec=AsyncSession)
    empty_result = MagicMock()
    empty_result.all.return_value = []
    empty_db.execute = AsyncMock(return_value=empty_result)
    async with _override_member(player), _override_db(empty_db):
        status = await _exhaust_then_check(
            client,
            "GET",
            "/api/v1/leagues/steele-spreadsheet/leaderboard",
            120,
            headers=_bearer(player_id),
        )
    assert status == 429


async def test_rate_limit_sync(client: AsyncClient) -> None:
    """POST /admin/sync/trigger: 10/hour per player → 429 on 11th request."""
    player_id = uuid.uuid4()
    admin = _make_player(player_id, role=PlayerRole.admin)
    async with (
        _override_admin(admin),
        _override_db(_make_db()),
    ):
        with patch("src.routers.admin.sync_results", new=AsyncMock()):
            status = await _exhaust_then_check(
                client,
                "POST",
                "/api/v1/admin/sync/trigger",
                10,
                headers=_bearer(player_id, role=PlayerRole.admin),
            )
    assert status == 429


async def test_rate_limit_backup(client: AsyncClient) -> None:
    """POST /admin/backup: 5/day per player → 429 on 6th request."""
    from datetime import datetime as dt

    from src.services.backup import BackupInfo

    player_id = uuid.uuid4()
    admin = _make_player(player_id, role=PlayerRole.admin)
    fake_info = BackupInfo(
        filename="wc2026_20260519_120000.sql",
        size_bytes=1024,
        created_at=dt.now(UTC).replace(tzinfo=None),
    )
    async with _override_admin(admin), _override_db(_make_db()):
        with patch("src.routers.admin.create_backup", new=AsyncMock(return_value=fake_info)):
            status = await _exhaust_then_check(
                client,
                "POST",
                "/api/v1/admin/backup",
                5,
                headers=_bearer(player_id, role=PlayerRole.admin),
            )
    assert status == 429


async def test_rate_limit_notifications_test(client: AsyncClient) -> None:
    """POST /push/test: 5/hour per player → 429 on 6th request."""
    player_id = uuid.uuid4()
    player = _make_player(player_id)
    async with _override_auth(player), _override_db(_make_db()):
        with patch("src.routers.notifications.send_notification", new=AsyncMock(return_value=True)):
            status = await _exhaust_then_check(
                client,
                "POST",
                "/api/v1/push/test",
                5,
                headers=_bearer(player_id),
            )
    assert status == 429


# ---------------------------------------------------------------------------
# R3.3 — Login enumeration fix
# ---------------------------------------------------------------------------


async def test_login_unknown_player_calls_dummy_bcrypt(client: AsyncClient) -> None:
    """When player is not found, verify_pin must be called to maintain constant-time response."""
    ip = f"10.{uuid.uuid4().int & 0xFF}.10.1"
    body = {"email": "nosuchuser@example.com", "pin": "9999"}

    with patch("src.routers.auth.verify_pin") as mock_vp:
        mock_vp.return_value = False
        async with _override_db(_make_db()):
            resp = await client.post(
                "/api/v1/auth/login",
                headers={"X-Forwarded-For": ip},
                json=body,
            )

    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid credentials"
    # Verify the dummy bcrypt check was called (timing parity)
    mock_vp.assert_called_once()
    pin_arg, hash_arg = mock_vp.call_args[0]
    assert pin_arg == "9999"
    assert hash_arg.startswith("$2b$")  # valid bcrypt hash format


# ---------------------------------------------------------------------------
# R3.4 — is_active enforcement
# ---------------------------------------------------------------------------


async def test_inactive_player_cannot_authenticate() -> None:
    """get_current_player WHERE clause includes is_active=True so disabled players get 401."""
    player_id = uuid.uuid4()
    token = create_access_token(player_id, PlayerRole.player)

    captured: list = []

    async def _capture_execute(stmt: object) -> MagicMock:
        captured.append(stmt)
        r = MagicMock()
        r.scalar_one_or_none.return_value = None
        return r

    mock_db = AsyncMock(spec=AsyncSession)
    mock_db.execute = _capture_execute

    creds = MagicMock(spec=HTTPAuthorizationCredentials)
    creds.credentials = token

    with pytest.raises(HTTPException) as exc_info:
        await get_current_player(creds, mock_db)

    assert exc_info.value.status_code == 401
    assert len(captured) == 1
    # Compile the statement and verify is_active appears in it
    from sqlalchemy.dialects import postgresql

    compiled = str(captured[0].compile(dialect=postgresql.dialect()))
    assert "is_active" in compiled
