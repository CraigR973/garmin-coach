"""Tests for POST /api/v1/auth/join."""

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.main import app
from src.models.invite import Invite
from src.models.profile import PlayerRole, Profile


@pytest.fixture(autouse=True)
def _no_notify_invite() -> None:
    with patch("src.routers.auth.notify_invite_accepted", new_callable=AsyncMock):
        yield


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _make_invite(
    *,
    is_active: bool = True,
    claimed_by: uuid.UUID | None = None,
    expires_at: datetime | None = None,
) -> MagicMock:
    inv = MagicMock(spec=Invite)
    inv.token = "validtoken123"
    inv.is_active = is_active
    inv.claimed_by = claimed_by
    inv.claimed_at = None
    inv.expires_at = expires_at
    inv.id = uuid.uuid4()
    # M2 — join uses invite.league_id to scope the new league_membership row.
    inv.league_id = uuid.uuid4()
    return inv


def _stub_db(execute_results: list) -> AsyncMock:
    mock_db = AsyncMock(spec=AsyncSession)
    mock_db.execute = AsyncMock(side_effect=execute_results)
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock(side_effect=_apply_profile_defaults)
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    return mock_db


def _apply_profile_defaults(obj: object) -> None:
    if isinstance(obj, Profile):
        if not hasattr(obj, "id") or obj.id is None:
            obj.id = uuid.uuid4()
        obj.role = PlayerRole.player
        obj.timezone = getattr(obj, "timezone", "UTC") or "UTC"
        obj.display_name = getattr(obj, "display_name", "Test")
        obj.created_at = _now()


def _scalar(value: object) -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


def _count(n: int) -> MagicMock:
    r = MagicMock()
    r.scalar.return_value = n
    return r


@asynccontextmanager
async def _override_db(mock_db: AsyncMock) -> AsyncGenerator[None, None]:
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


_VALID_BODY = {
    "token": "validtoken123",
    "display_name": "Alice",
    "pin": "1234",
    "timezone": "Europe/London",
}


async def test_join_success(client: AsyncClient) -> None:
    invite = _make_invite()
    mock_db = _stub_db(
        [
            _scalar(invite),  # invite lookup
            _scalar(None),  # display_name uniqueness check
            _count(5),  # active player count
        ]
    )

    with patch("src.routers.auth._issue_token_pair", AsyncMock(return_value=("acc", "ref"))):
        async with _override_db(mock_db):
            resp = await client.post("/api/v1/auth/join", json=_VALID_BODY)

    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["access_token"] == "acc"
    assert data["refresh_token"] == "ref"
    assert data["player"]["display_name"] == "Alice"
    assert data["player"]["timezone"] == "Europe/London"
    assert invite.is_active is False
    assert invite.claimed_by is not None


async def test_join_invalid_token(client: AsyncClient) -> None:
    mock_db = _stub_db([_scalar(None)])  # invite not found
    async with _override_db(mock_db):
        resp = await client.post("/api/v1/auth/join", json=_VALID_BODY)
    assert resp.status_code == 400
    assert "Invalid invite token" in resp.json()["detail"]


async def test_join_revoked_invite(client: AsyncClient) -> None:
    invite = _make_invite(is_active=False)
    mock_db = _stub_db([_scalar(invite)])
    async with _override_db(mock_db):
        resp = await client.post("/api/v1/auth/join", json=_VALID_BODY)
    assert resp.status_code == 400
    assert "revoked" in resp.json()["detail"]


async def test_join_already_claimed(client: AsyncClient) -> None:
    invite = _make_invite(claimed_by=uuid.uuid4())
    mock_db = _stub_db([_scalar(invite)])
    async with _override_db(mock_db):
        resp = await client.post("/api/v1/auth/join", json=_VALID_BODY)
    assert resp.status_code == 400
    assert "already used" in resp.json()["detail"]


async def test_join_expired_invite(client: AsyncClient) -> None:
    invite = _make_invite(expires_at=_now() - timedelta(hours=1))
    mock_db = _stub_db([_scalar(invite)])
    async with _override_db(mock_db):
        resp = await client.post("/api/v1/auth/join", json=_VALID_BODY)
    assert resp.status_code == 400
    assert "expired" in resp.json()["detail"]


async def test_join_duplicate_display_name(client: AsyncClient) -> None:
    invite = _make_invite()
    existing = MagicMock(spec=Profile)
    existing.avatar_url = None  # U23: prevent MagicMock default from failing Pydantic
    mock_db = _stub_db(
        [
            _scalar(invite),  # invite lookup
            _scalar(existing),  # display_name taken
        ]
    )
    async with _override_db(mock_db):
        resp = await client.post("/api/v1/auth/join", json=_VALID_BODY)
    assert resp.status_code == 400
    assert "Display name" in resp.json()["detail"]


async def test_join_league_full(client: AsyncClient) -> None:
    invite = _make_invite()
    mock_db = _stub_db(
        [
            _scalar(invite),  # invite lookup
            _scalar(None),  # display_name not taken
            _count(15),  # league full
        ]
    )
    async with _override_db(mock_db):
        resp = await client.post("/api/v1/auth/join", json=_VALID_BODY)
    assert resp.status_code == 400
    assert "full" in resp.json()["detail"]


async def test_join_default_timezone(client: AsyncClient) -> None:
    invite = _make_invite()
    mock_db = _stub_db(
        [
            _scalar(invite),
            _scalar(None),
            _count(0),
        ]
    )

    with patch("src.routers.auth._issue_token_pair", AsyncMock(return_value=("acc", "ref"))):
        async with _override_db(mock_db):
            resp = await client.post(
                "/api/v1/auth/join",
                json={"token": "validtoken123", "display_name": "Bob", "pin": "5678"},
            )

    assert resp.status_code == 201, resp.text
    assert resp.json()["player"]["timezone"] == "UTC"
