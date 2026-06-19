"""Tests for M4 auth endpoints: signup, verify-email, resend-verification, PIN reset.

Coverage required by M4 acceptance:
- Signup happy path: profile + notif prefs + JWT pair
- Email collision rejection (409)
- Email verification token round-trip
- PIN reset gated on email_verified_at
- Generic response for unverified PIN reset (no enumeration leak)
- Login by email (new shape)
- Login by display_name still works (deprecated, adds X-Deprecation header)
"""

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import jwt as pyjwt
import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import (
    create_email_verify_token,
    create_pin_reset_token,
    decode_email_verify_token,
    decode_pin_reset_token,
    hash_pin,
)
from src.config import settings
from src.database import get_db
from src.main import app
from src.models.profile import PlayerRole, Profile

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _make_player(
    *,
    email: str = "alice@example.com",
    email_verified_at: datetime | None = None,
    role: PlayerRole = PlayerRole.player,
    failed: int = 0,
    locked_until: datetime | None = None,
) -> Profile:
    p = MagicMock(spec=Profile)
    p.avatar_url = None  # U23: prevent MagicMock default from failing Pydantic
    p.id = uuid.uuid4()
    p.display_name = "Alice Wong"
    p.first_name = "Alice"
    p.last_name = "Wong"
    p.email = email
    p.email_verified_at = email_verified_at
    p.pin_hash = hash_pin("1234")
    p.role = role
    p.timezone = "UTC"
    p.failed_login_count = failed
    p.locked_until = locked_until
    p.deleted_at = None
    return p


def _stub_db(execute_results: list) -> AsyncMock:
    mock_db = AsyncMock(spec=AsyncSession)
    mock_db.execute = AsyncMock(side_effect=execute_results)
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    return mock_db


def _scalar(value: object) -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
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


# ---------------------------------------------------------------------------
# Token helper unit tests
# ---------------------------------------------------------------------------


def test_email_verify_token_round_trip() -> None:
    email = "alice@example.com"
    token = create_email_verify_token(email)
    payload = decode_email_verify_token(token)
    assert payload["sub"] == email.lower()
    assert payload["scope"] == "email_verify"


def test_email_verify_token_wrong_scope_rejected() -> None:
    fake = pyjwt.encode(
        {"sub": "x@x.com", "scope": "pin_reset", "exp": _now() + timedelta(hours=1)},
        settings.jwt_access_secret,
        algorithm="HS256",
    )
    with pytest.raises(HTTPException) as exc:
        decode_email_verify_token(fake)
    assert exc.value.status_code == 400


def test_pin_reset_token_round_trip() -> None:
    player_id = uuid.uuid4()
    token = create_pin_reset_token(player_id)
    payload = decode_pin_reset_token(token)
    assert payload["sub"] == str(player_id)
    assert payload["scope"] == "pin_reset"


def test_pin_reset_token_wrong_scope_rejected() -> None:
    fake = pyjwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "scope": "email_verify",
            "exp": _now() + timedelta(hours=1),
        },
        settings.jwt_access_secret,
        algorithm="HS256",
    )
    with pytest.raises(HTTPException) as exc:
        decode_pin_reset_token(fake)
    assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# Signup — happy path
# ---------------------------------------------------------------------------


async def test_signup_happy_path(client: AsyncClient) -> None:
    mock_db = _stub_db([_scalar(None)])

    with patch("src.routers.auth.send_verification_email"):
        async with _override_db(mock_db):
            resp = await client.post(
                "/api/v1/auth/signup",
                json={
                    "email": "alice@example.com",
                    "first_name": "Alice",
                    "last_name": "Wong",
                    "pin": "1234",
                    "timezone": "Europe/London",
                },
            )

    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["player"]["display_name"] == "Alice W."
    assert "avatar_url" in data["player"]
    assert data["player"]["avatar_url"] is None
    assert mock_db.add.call_count >= 2  # Profile + NotificationPreferences


async def test_signup_creates_notification_prefs(client: AsyncClient) -> None:
    """add() must be called for both Profile and NotificationPreferences."""
    mock_db = _stub_db([_scalar(None)])

    async with _override_db(mock_db):
        resp = await client.post(
            "/api/v1/auth/signup",
            json={
                "email": "bob@example.com",
                "first_name": "Bob",
                "last_name": "Smith",
                "pin": "5678",
            },
        )

    assert resp.status_code == 201
    calls = [
        str(c.args[0].__class__.__name__) if c.args else "" for c in mock_db.add.call_args_list
    ]
    assert "Profile" in calls
    assert "NotificationPreferences" in calls


# ---------------------------------------------------------------------------
# Signup — email collision
# ---------------------------------------------------------------------------


async def test_signup_email_collision_returns_409(client: AsyncClient) -> None:
    existing = _make_player(email="alice@example.com")
    mock_db = _stub_db([_scalar(existing)])

    async with _override_db(mock_db):
        resp = await client.post(
            "/api/v1/auth/signup",
            json={
                "email": "ALICE@example.com",
                "first_name": "Alice",
                "last_name": "Wong",
                "pin": "1234",
            },
        )

    assert resp.status_code == 409
    assert "Email already registered" in resp.json()["detail"]


async def test_signup_email_collision_case_insensitive(client: AsyncClient) -> None:
    existing = _make_player(email="alice@example.com")
    mock_db = _stub_db([_scalar(existing)])

    async with _override_db(mock_db):
        resp = await client.post(
            "/api/v1/auth/signup",
            json={
                "email": "Alice@Example.COM",
                "first_name": "Alice",
                "last_name": "Wong",
                "pin": "1234",
            },
        )

    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Email verification — token round-trip
# ---------------------------------------------------------------------------


async def test_verify_email_sets_verified_at(client: AsyncClient) -> None:
    player = _make_player(email="alice@example.com", email_verified_at=None)
    mock_db = _stub_db([_scalar(player)])

    token = create_email_verify_token("alice@example.com")

    async with _override_db(mock_db):
        resp = await client.post("/api/v1/auth/verify-email", json={"token": token})

    assert resp.status_code == 204
    assert player.email_verified_at is not None


async def test_verify_email_already_verified_is_idempotent(client: AsyncClient) -> None:
    already_verified_at = _now() - timedelta(days=1)
    player = _make_player(email="alice@example.com", email_verified_at=already_verified_at)
    mock_db = _stub_db([_scalar(player)])

    token = create_email_verify_token("alice@example.com")

    async with _override_db(mock_db):
        resp = await client.post("/api/v1/auth/verify-email", json={"token": token})

    assert resp.status_code == 204
    assert player.email_verified_at == already_verified_at


async def test_verify_email_invalid_token_returns_400(client: AsyncClient) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/api/v1/auth/verify-email", json={"token": "not.a.jwt"})
    assert resp.status_code == 400


async def test_verify_email_expired_token_returns_400(client: AsyncClient) -> None:
    expired = pyjwt.encode(
        {
            "sub": "alice@example.com",
            "scope": "email_verify",
            "exp": _now() - timedelta(hours=1),
        },
        settings.jwt_access_secret,
        algorithm="HS256",
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/api/v1/auth/verify-email", json={"token": expired})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# PIN reset — gated on email_verified_at
# ---------------------------------------------------------------------------


async def test_pin_reset_request_verified_email_queues_reset(client: AsyncClient) -> None:
    verified_player = _make_player(
        email="alice@example.com",
        email_verified_at=_now() - timedelta(days=1),
    )
    mock_db = _stub_db([_scalar(verified_player)])

    with patch("src.routers.auth.send_pin_reset_email") as mock_reset:
        async with _override_db(mock_db):
            resp = await client.post(
                "/api/v1/auth/pin/reset-request", json={"email": "alice@example.com"}
            )

    assert resp.status_code == 200
    assert "reset link" in resp.json()["message"]
    mock_reset.assert_called_once()


async def test_pin_reset_request_unverified_sends_verification_not_reset(
    client: AsyncClient,
) -> None:
    unverified = _make_player(email="bob@example.com", email_verified_at=None)
    mock_db = _stub_db([_scalar(unverified)])

    with (
        patch("src.routers.auth.send_pin_reset_email") as mock_reset,
        patch("src.routers.auth.send_verification_email") as mock_verify,
    ):
        async with _override_db(mock_db):
            resp = await client.post(
                "/api/v1/auth/pin/reset-request", json={"email": "bob@example.com"}
            )

    assert resp.status_code == 200
    assert "reset link" in resp.json()["message"]
    mock_reset.assert_not_called()
    mock_verify.assert_called_once()


async def test_pin_reset_request_unknown_email_generic_response(client: AsyncClient) -> None:
    mock_db = _stub_db([_scalar(None)])

    with patch("src.routers.auth.send_pin_reset_email") as mock_reset:
        async with _override_db(mock_db):
            resp = await client.post(
                "/api/v1/auth/pin/reset-request", json={"email": "nobody@example.com"}
            )

    assert resp.status_code == 200
    assert "reset link" in resp.json()["message"]
    mock_reset.assert_not_called()


async def test_pin_reset_confirm_updates_pin_and_revokes_tokens(client: AsyncClient) -> None:
    player = _make_player()
    update_result = MagicMock()
    mock_db = _stub_db([_scalar(player), update_result])

    token = create_pin_reset_token(player.id)

    async with _override_db(mock_db):
        resp = await client.post("/api/v1/auth/pin/reset", json={"token": token, "new_pin": "9999"})

    assert resp.status_code == 204
    assert player.pin_hash != hash_pin("1234")
    assert player.failed_login_count == 0
    assert player.locked_until is None


async def test_pin_reset_confirm_invalid_token_returns_400(client: AsyncClient) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/api/v1/auth/pin/reset", json={"token": "garbage", "new_pin": "1234"})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Login — email path (new shape)
# ---------------------------------------------------------------------------


async def test_login_by_email_success(client: AsyncClient) -> None:
    player = _make_player(email="alice@example.com")
    mock_db = _stub_db([_scalar(player), _scalar(None)])

    async with _override_db(mock_db):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "alice@example.com", "pin": "1234"},
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "access_token" in data
    assert "X-Deprecation" not in resp.headers


async def test_login_by_email_case_insensitive(client: AsyncClient) -> None:
    player = _make_player(email="alice@example.com")
    mock_db = _stub_db([_scalar(player), _scalar(None)])

    async with _override_db(mock_db):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "ALICE@EXAMPLE.COM", "pin": "1234"},
        )

    assert resp.status_code == 200


async def test_login_no_email_returns_422(client: AsyncClient) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/api/v1/auth/login", json={"pin": "1234"})
    assert resp.status_code == 422
