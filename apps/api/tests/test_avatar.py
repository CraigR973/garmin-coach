"""Tests for PATCH /api/v1/auth/me/avatar (U23.1).

Covers:
- Set a valid HTTPS avatar URL → 200 + url persisted
- Clear avatar (null) → 200 + null returned
- Reject non-HTTPS URL → 422
- Unauthenticated request → 401/403
- GET /me includes avatar_url field
"""

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_player, hash_pin
from src.database import get_db
from src.main import app
from src.models.profile import PlayerRole, Profile, SiteRole


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _make_player(*, avatar_url: str | None = None) -> MagicMock:
    p = MagicMock(spec=Profile)
    p.id = uuid.uuid4()
    p.display_name = "AvatarPlayer"
    p.role = PlayerRole.player
    p.site_role = SiteRole.user
    p.timezone = "UTC"
    p.pin_hash = hash_pin("1234")
    p.deleted_at = None
    p.created_at = _now()
    p.avatar_url = avatar_url
    return p


def _stub_db(execute_results: list | None = None) -> AsyncMock:
    mock_db = AsyncMock(spec=AsyncSession)
    mock_db.execute = AsyncMock(side_effect=execute_results or [])
    mock_db.commit = AsyncMock()
    # refresh() updates the player mock's avatar_url in-place via a side_effect
    # set per-test when we need it.
    mock_db.refresh = AsyncMock()
    mock_db.add = MagicMock()
    return mock_db


def _rows(value: object) -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


@asynccontextmanager
async def _override(player: MagicMock, mock_db: AsyncMock) -> AsyncGenerator[None, None]:
    async def _fake_player() -> Profile:
        return player  # type: ignore[return-value]

    async def _fake_db() -> AsyncGenerator[AsyncSession, None]:
        yield mock_db  # type: ignore[misc]

    app.dependency_overrides[get_current_player] = _fake_player
    app.dependency_overrides[get_db] = _fake_db
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_current_player, None)
        app.dependency_overrides.pop(get_db, None)


@asynccontextmanager
async def _override_player_only(player: MagicMock) -> AsyncGenerator[None, None]:
    async def _fake_player() -> Profile:
        return player  # type: ignore[return-value]

    app.dependency_overrides[get_current_player] = _fake_player
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_current_player, None)


@pytest.fixture
async def client() -> AsyncClient:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# PATCH /api/v1/auth/me/avatar
# ---------------------------------------------------------------------------


async def test_set_avatar_url(client: AsyncClient) -> None:
    """PATCH with a valid HTTPS URL returns 200 and the URL in the response."""
    player = _make_player()
    avatar_url = "https://example.supabase.co/storage/v1/object/public/avatars/abc/photo.jpg"

    # The endpoint calls db.execute() once (for the UPDATE statement).
    execute_result = MagicMock()
    mock_db = _stub_db([execute_result])

    # After refresh() the player mock should return the new avatar_url.
    async def _refresh(obj: object) -> None:
        player.avatar_url = avatar_url

    mock_db.refresh = AsyncMock(side_effect=_refresh)

    async with _override(player, mock_db):
        resp = await client.patch(
            "/api/v1/auth/me/avatar",
            json={"avatar_url": avatar_url},
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["avatar_url"] == avatar_url
    assert data["display_name"] == "AvatarPlayer"


async def test_clear_avatar_url(client: AsyncClient) -> None:
    """PATCH with null removes the avatar URL."""
    player = _make_player(
        avatar_url="https://example.supabase.co/storage/v1/object/public/avatars/abc/old.jpg"
    )

    execute_result = MagicMock()
    mock_db = _stub_db([execute_result])

    async def _refresh(obj: object) -> None:
        player.avatar_url = None

    mock_db.refresh = AsyncMock(side_effect=_refresh)

    async with _override(player, mock_db):
        resp = await client.patch(
            "/api/v1/auth/me/avatar",
            json={"avatar_url": None},
        )

    assert resp.status_code == 200, resp.text
    assert resp.json()["avatar_url"] is None


async def test_avatar_url_must_be_https(client: AsyncClient) -> None:
    """PATCH with a non-HTTPS URL is rejected with 422."""
    player = _make_player()
    mock_db = _stub_db()

    async with _override(player, mock_db):
        resp = await client.patch(
            "/api/v1/auth/me/avatar",
            json={"avatar_url": "http://insecure.example.com/photo.jpg"},
        )

    assert resp.status_code == 422, resp.text


async def test_avatar_unauthenticated(client: AsyncClient) -> None:
    """Unauthenticated request is rejected."""
    resp = await client.patch(
        "/api/v1/auth/me/avatar",
        json={"avatar_url": "https://example.supabase.co/avatars/x.jpg"},
    )
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# GET /api/v1/auth/me — avatar_url included
# ---------------------------------------------------------------------------


async def test_me_includes_avatar_url(client: AsyncClient) -> None:
    """GET /me exposes the avatar_url field (may be null)."""
    player = _make_player(
        avatar_url="https://example.supabase.co/storage/v1/object/public/avatars/abc/face.png"
    )
    async with _override_player_only(player):
        resp = await client.get("/api/v1/auth/me")

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "avatar_url" in data
    assert data["avatar_url"] == player.avatar_url


async def test_me_avatar_url_null_when_unset(client: AsyncClient) -> None:
    """GET /me returns avatar_url: null when no avatar is configured."""
    player = _make_player(avatar_url=None)
    async with _override_player_only(player):
        resp = await client.get("/api/v1/auth/me")

    assert resp.status_code == 200, resp.text
    assert resp.json()["avatar_url"] is None


# ---------------------------------------------------------------------------
# POST /api/v1/auth/me/avatar — server-side upload (service-role, bypasses RLS)
# ---------------------------------------------------------------------------


async def test_upload_avatar_success(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """POST image bytes uploads via storage and persists the returned URL."""
    player = _make_player()
    public_url = "https://example.supabase.co/storage/v1/object/public/avatars/abc/1.jpg"

    upload_mock = AsyncMock(return_value=public_url)
    monkeypatch.setattr("src.routers.auth.upload_avatar", upload_mock)

    mock_db = _stub_db([MagicMock()])

    async def _refresh(obj: object) -> None:
        player.avatar_url = public_url

    mock_db.refresh = AsyncMock(side_effect=_refresh)

    async with _override(player, mock_db):
        resp = await client.post(
            "/api/v1/auth/me/avatar",
            content=b"\xff\xd8\xff\xe0jpegbytes",
            headers={"Content-Type": "image/jpeg"},
        )

    assert resp.status_code == 200, resp.text
    assert resp.json()["avatar_url"] == public_url
    upload_mock.assert_awaited_once()
    # Uploaded under the caller's id, with the declared content type.
    assert upload_mock.await_args.args[0] == str(player.id)
    assert upload_mock.await_args.args[2] == "image/jpeg"


async def test_upload_avatar_rejects_unsupported_type(client: AsyncClient) -> None:
    """A non-image content type is rejected with 415."""
    player = _make_player()
    async with _override(player, _stub_db()):
        resp = await client.post(
            "/api/v1/auth/me/avatar",
            content=b"hello",
            headers={"Content-Type": "text/plain"},
        )
    assert resp.status_code == 415, resp.text


async def test_upload_avatar_rejects_empty_body(client: AsyncClient) -> None:
    """An empty image body is rejected with 422."""
    player = _make_player()
    async with _override(player, _stub_db()):
        resp = await client.post(
            "/api/v1/auth/me/avatar",
            content=b"",
            headers={"Content-Type": "image/jpeg"},
        )
    assert resp.status_code == 422, resp.text


async def test_upload_avatar_rejects_too_large(client: AsyncClient) -> None:
    """A body over the 5 MB cap is rejected with 413."""
    player = _make_player()
    big = b"\x00" * (5 * 1024 * 1024 + 1)
    async with _override(player, _stub_db()):
        resp = await client.post(
            "/api/v1/auth/me/avatar",
            content=big,
            headers={"Content-Type": "image/jpeg"},
        )
    assert resp.status_code == 413, resp.text


async def test_upload_avatar_unauthenticated(client: AsyncClient) -> None:
    """Unauthenticated upload is rejected."""
    resp = await client.post(
        "/api/v1/auth/me/avatar",
        content=b"\xff\xd8\xff",
        headers={"Content-Type": "image/jpeg"},
    )
    assert resp.status_code in (401, 403)
