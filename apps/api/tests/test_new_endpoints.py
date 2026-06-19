"""Tests for new endpoints in phases 2.5–2.6:
- GET /api/v1/auth/invite/{token}  (public invite preview)
- GET /api/v1/admin/players         (admin player list, with include_deleted)
"""

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import require_admin
from src.database import get_db
from src.main import app
from src.models.invite import Invite
from src.models.profile import PlayerRole, Profile

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _make_profile(*, role: PlayerRole = PlayerRole.player, deleted: bool = False) -> MagicMock:
    p = MagicMock(spec=Profile)
    p.avatar_url = None  # U23: prevent MagicMock default from failing Pydantic
    p.id = uuid.uuid4()
    p.display_name = "TestPlayer"
    p.first_name = "Test"
    p.last_name = "Player"
    p.email = "test@example.com"
    p.failed_login_count = 0
    p.locked_until = None
    p.role = role
    p.timezone = "UTC"
    p.deleted_at = _now() if deleted else None
    p.created_at = _now()
    return p


def _make_invite(
    *,
    is_active: bool = True,
    claimed_by: uuid.UUID | None = None,
    expires_at: datetime | None = None,
    display_name_hint: str | None = None,
) -> MagicMock:
    inv = MagicMock(spec=Invite)
    inv.token = "testtoken"
    inv.is_active = is_active
    inv.claimed_by = claimed_by
    inv.claimed_at = None
    inv.expires_at = expires_at
    inv.display_name_hint = display_name_hint
    return inv


def _stub_db(execute_results: list) -> AsyncMock:
    mock_db = AsyncMock(spec=AsyncSession)
    mock_db.execute = AsyncMock(side_effect=execute_results)
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()
    mock_db.add = MagicMock()
    return mock_db


@asynccontextmanager
async def _override_db(mock_db: AsyncMock) -> AsyncGenerator[None, None]:
    async def _get_db() -> AsyncGenerator[AsyncMock, None]:
        yield mock_db

    app.dependency_overrides[get_db] = _get_db
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_db, None)


def _scalar(value: object) -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


def _scalars(values: list) -> MagicMock:
    r = MagicMock()
    r.scalars.return_value.all.return_value = values
    return r


# ---------------------------------------------------------------------------
# GET /api/v1/auth/invite/{token}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invite_preview_valid() -> None:
    invite = _make_invite(display_name_hint="Craig")
    mock_db = _stub_db([_scalar(invite)])

    async with _override_db(mock_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/auth/invite/testtoken")

    assert resp.status_code == 200
    assert resp.json()["display_name_hint"] == "Craig"


@pytest.mark.asyncio
async def test_invite_preview_not_found() -> None:
    mock_db = _stub_db([_scalar(None)])

    async with _override_db(mock_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/auth/invite/badtoken")

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_invite_preview_revoked() -> None:
    invite = _make_invite(is_active=False)
    mock_db = _stub_db([_scalar(invite)])

    async with _override_db(mock_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/auth/invite/testtoken")

    assert resp.status_code == 400
    assert "revoked" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_invite_preview_claimed() -> None:
    invite = _make_invite(claimed_by=uuid.uuid4())
    mock_db = _stub_db([_scalar(invite)])

    async with _override_db(mock_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/auth/invite/testtoken")

    assert resp.status_code == 400
    assert "already used" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_invite_preview_expired() -> None:
    invite = _make_invite(expires_at=_now() - timedelta(hours=1))
    mock_db = _stub_db([_scalar(invite)])

    async with _override_db(mock_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/auth/invite/testtoken")

    assert resp.status_code == 400
    assert "expired" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# GET /api/v1/admin/players
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_list_players() -> None:
    admin = _make_profile(role=PlayerRole.admin)
    p1 = _make_profile()
    p1.display_name = "Alice"

    mock_db = _stub_db([_scalars([p1])])

    app.dependency_overrides[require_admin] = lambda: admin
    try:
        async with _override_db(mock_db):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/v1/admin/players")
    finally:
        app.dependency_overrides.pop(require_admin, None)

    assert resp.status_code == 200
    assert resp.json()[0]["display_name"] == "Alice"


@pytest.mark.asyncio
async def test_admin_list_players_include_deleted() -> None:
    admin = _make_profile(role=PlayerRole.admin)
    p1 = _make_profile(deleted=True)
    p1.display_name = "DeletedPlayer"

    mock_db = _stub_db([_scalars([p1])])

    app.dependency_overrides[require_admin] = lambda: admin
    try:
        async with _override_db(mock_db):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/v1/admin/players?include_deleted=true")
    finally:
        app.dependency_overrides.pop(require_admin, None)

    assert resp.status_code == 200
    assert resp.json()[0]["is_deleted"] is True


@pytest.mark.asyncio
async def test_admin_list_players_requires_auth() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/admin/players")

    assert resp.status_code == 401
