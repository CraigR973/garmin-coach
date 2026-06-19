"""Tests for admin invite endpoints: create, list, revoke."""

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
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


def _make_admin() -> Profile:
    p = MagicMock(spec=Profile)
    p.avatar_url = None  # U23: prevent MagicMock default from failing Pydantic
    p.id = uuid.uuid4()
    p.display_name = "Admin"
    p.role = PlayerRole.admin
    p.deleted_at = None
    return p


def _make_invite(
    admin_id: uuid.UUID,
    *,
    is_active: bool = True,
    claimed_by: uuid.UUID | None = None,
    expires_at: datetime | None = None,
    display_name_hint: str | None = None,
) -> MagicMock:
    inv = MagicMock(spec=Invite)
    inv.id = uuid.uuid4()
    inv.token = "tok_" + uuid.uuid4().hex
    inv.display_name_hint = display_name_hint
    inv.created_by = admin_id
    inv.claimed_by = claimed_by
    inv.claimed_at = _now() if claimed_by else None
    inv.expires_at = expires_at
    inv.is_active = is_active
    inv.created_at = _now()
    return inv


def _stub_db(execute_results: list) -> AsyncMock:
    mock_db = AsyncMock(spec=AsyncSession)
    mock_db.execute = AsyncMock(side_effect=execute_results)
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock(side_effect=lambda obj: None)
    mock_db.add = MagicMock()
    return mock_db


def _scalars(items: list) -> MagicMock:
    r = MagicMock()
    r.scalars.return_value.all.return_value = items
    return r


def _scalar(value: object) -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


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
# POST /api/v1/admin/invites — removed in M8 (per-league invites only)
# ---------------------------------------------------------------------------


async def test_create_invite_removed(client: AsyncClient) -> None:
    """The global admin POST /invites route was removed; use per-league invites."""
    resp = await client.post(
        "/api/v1/admin/invites",
        json={"display_name_hint": "Alice", "expires_in_days": 7},
    )
    assert resp.status_code in (404, 405)


# ---------------------------------------------------------------------------
# GET /api/v1/admin/invites
# ---------------------------------------------------------------------------


async def test_list_invites_returns_all(client: AsyncClient) -> None:
    admin = _make_admin()
    invites = [
        _make_invite(admin.id, display_name_hint="Alice"),
        _make_invite(admin.id, is_active=False),
    ]

    mock_db = _stub_db([_scalars(invites)])

    async with _override_db_and_admin(mock_db, admin):
        resp = await client.get("/api/v1/admin/invites")

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data) == 2


async def test_list_invites_empty(client: AsyncClient) -> None:
    admin = _make_admin()
    mock_db = _stub_db([_scalars([])])

    async with _override_db_and_admin(mock_db, admin):
        resp = await client.get("/api/v1/admin/invites")

    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# DELETE /api/v1/admin/invites/{id}
# ---------------------------------------------------------------------------


async def test_revoke_invite_success(client: AsyncClient) -> None:
    admin = _make_admin()
    invite = _make_invite(admin.id)
    mock_db = _stub_db([_scalar(invite)])

    async with _override_db_and_admin(mock_db, admin):
        resp = await client.delete(f"/api/v1/admin/invites/{invite.id}")

    assert resp.status_code == 204
    assert invite.is_active is False


async def test_revoke_invite_not_found(client: AsyncClient) -> None:
    admin = _make_admin()
    mock_db = _stub_db([_scalar(None)])

    async with _override_db_and_admin(mock_db, admin):
        resp = await client.delete(f"/api/v1/admin/invites/{uuid.uuid4()}")

    assert resp.status_code == 404


async def test_revoke_already_revoked_invite(client: AsyncClient) -> None:
    """Revoking an already-inactive invite still succeeds (idempotent)."""
    admin = _make_admin()
    invite = _make_invite(admin.id, is_active=False)
    mock_db = _stub_db([_scalar(invite)])

    async with _override_db_and_admin(mock_db, admin):
        resp = await client.delete(f"/api/v1/admin/invites/{invite.id}")

    assert resp.status_code == 204
    assert invite.is_active is False


# ---------------------------------------------------------------------------
# Auth guard — non-admin cannot reach admin endpoints
# ---------------------------------------------------------------------------


async def test_admin_endpoints_require_auth(client: AsyncClient) -> None:
    """Without auth, all admin endpoints return 403 (require_admin not overridden)."""
    resp = await client.get("/api/v1/admin/invites")
    assert resp.status_code in (401, 403)
