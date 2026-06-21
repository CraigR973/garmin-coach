"""Tests for push subscription endpoints and push_notification_service."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.auth import get_current_user
from src.config import settings
from src.database import get_db
from src.main import app
from src.models.notification import NotificationPreferences, PushSubscription
from src.models.profile import Profile
from src.services.push_notification_service import (
    _is_quiet,
    send_notification,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _user(display_name: str = "Alice") -> MagicMock:
    p = MagicMock(spec=Profile)
    p.id = uuid.uuid4()
    p.display_name = display_name
    p.is_active = True
    p.deleted_at = None
    p.role = "player"
    return p


def _db_with(mock_db: AsyncMock):  # type: ignore[no-untyped-def]
    async def _override():  # type: ignore[no-untyped-def]
        yield mock_db

    return _override


def _sub(user_id: uuid.UUID, endpoint: str = "https://fcm.example/push/abc") -> MagicMock:
    s = MagicMock(spec=PushSubscription)
    s.id = uuid.uuid4()
    s.user_id = user_id
    s.subscription = {"endpoint": endpoint, "keys": {"auth": "x", "p256dh": "y"}}
    s.is_active = True
    s.failed_send_count = 0
    s.last_used_at = None
    return s


def _prefs(user_id: uuid.UUID, **overrides: Any) -> MagicMock:
    p = MagicMock(spec=NotificationPreferences)
    p.user_id = user_id
    p.global_mute = False
    p.quiet_hours_start = None
    p.quiet_hours_end = None
    for k, v in overrides.items():
        setattr(p, k, v)
    return p


# ── Unit tests: _is_quiet ─────────────────────────────────────────────────────


class TestIsQuiet:
    def test_no_quiet_hours_never_quiet(self) -> None:
        prefs = _prefs(uuid.uuid4())
        assert _is_quiet(prefs, datetime(2026, 6, 1, 23, 0)) is False

    def test_quiet_within_overnight_range(self) -> None:
        prefs = _prefs(uuid.uuid4())
        prefs.quiet_hours_start = datetime(2000, 1, 1, 23, 0)
        prefs.quiet_hours_end = datetime(2000, 1, 1, 7, 0)
        assert _is_quiet(prefs, datetime(2026, 6, 1, 23, 30)) is True

    def test_not_quiet_outside_range(self) -> None:
        prefs = _prefs(uuid.uuid4())
        prefs.quiet_hours_start = datetime(2000, 1, 1, 23, 0)
        prefs.quiet_hours_end = datetime(2000, 1, 1, 7, 0)
        assert _is_quiet(prefs, datetime(2026, 6, 1, 12, 0)) is False

    def test_daytime_window(self) -> None:
        prefs = _prefs(uuid.uuid4())
        prefs.quiet_hours_start = datetime(2000, 1, 1, 9, 0)
        prefs.quiet_hours_end = datetime(2000, 1, 1, 17, 0)
        assert _is_quiet(prefs, datetime(2026, 6, 1, 10, 0)) is True
        assert _is_quiet(prefs, datetime(2026, 6, 1, 8, 0)) is False


# ── Unit tests: send_notification ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_notification_skips_when_no_vapid() -> None:
    session = AsyncMock()
    with (
        patch.object(settings, "vapid_private_key", ""),
        patch.object(settings, "vapid_public_key", ""),
    ):
        sent = await send_notification(session, uuid.uuid4(), title="T", body="B")
    assert sent == 0


@pytest.mark.asyncio
async def test_send_notification_suppressed_when_global_mute() -> None:
    user_id = uuid.uuid4()
    prefs = _prefs(user_id, global_mute=True)

    session = AsyncMock()
    session.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=prefs))

    with (
        patch.object(settings, "vapid_private_key", "private"),
        patch.object(settings, "vapid_public_key", "public"),
    ):
        sent = await send_notification(session, user_id, title="T", body="B")
    assert sent == 0


@pytest.mark.asyncio
async def test_send_notification_delivers_when_no_prefs() -> None:
    """No preferences row → defaults (not muted), should attempt delivery."""
    user_id = uuid.uuid4()
    sub = _sub(user_id)

    session = AsyncMock()
    session.execute.side_effect = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=None)),  # prefs
        MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[sub])))),
    ]

    with (
        patch.object(settings, "vapid_private_key", "priv"),
        patch.object(settings, "vapid_public_key", "pub"),
        patch("src.services.push_notification_service._send_push_sync"),
    ):
        sent = await send_notification(session, user_id, title="Title", body="Body")

    assert sent == 1


@pytest.mark.asyncio
async def test_send_notification_suppressed_during_quiet_hours() -> None:
    user_id = uuid.uuid4()
    prefs = _prefs(
        user_id,
        quiet_hours_start=datetime(2000, 1, 1, 9, 0),
        quiet_hours_end=datetime(2000, 1, 1, 17, 0),
    )

    session = AsyncMock()
    session.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=prefs))

    with (
        patch.object(settings, "vapid_private_key", "private"),
        patch.object(settings, "vapid_public_key", "public"),
        patch(
            "src.services.push_notification_service._utc_now",
            return_value=datetime(2026, 6, 1, 10, 0),
        ),
    ):
        sent = await send_notification(session, user_id, title="T", body="B")
    assert sent == 0


@pytest.mark.asyncio
async def test_send_notification_quiet_hours_use_user_timezone() -> None:
    user_id = uuid.uuid4()
    prefs = _prefs(
        user_id,
        quiet_hours_start=datetime(2000, 1, 1, 23, 0),
        quiet_hours_end=datetime(2000, 1, 1, 7, 0),
    )

    session = AsyncMock()
    session.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=prefs))

    with (
        patch.object(settings, "vapid_private_key", "private"),
        patch.object(settings, "vapid_public_key", "public"),
    ):
        sent = await send_notification(
            session,
            user_id,
            title="T",
            body="B",
            timezone_name="Europe/London",
            now_utc=datetime(2026, 6, 20, 22, 30),
        )
    assert sent == 0


@pytest.mark.asyncio
async def test_send_notification_auto_disables_after_3_failures() -> None:
    from pywebpush import WebPushException

    user_id = uuid.uuid4()
    sub = _sub(user_id)
    sub.failed_send_count = 2
    prefs = _prefs(user_id)

    session = AsyncMock()
    session.execute.side_effect = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=prefs)),
        MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[sub])))),
    ]

    def _fail(*_: Any, **__: Any) -> None:
        raise WebPushException("410 Gone")

    with (
        patch.object(settings, "vapid_private_key", "priv"),
        patch.object(settings, "vapid_public_key", "pub"),
        patch("src.services.push_notification_service._send_push_sync", side_effect=_fail),
    ):
        sent = await send_notification(session, user_id, title="T", body="B")

    assert sent == 0
    assert sub.is_active is False
    assert sub.failed_send_count == 3


# ── HTTP endpoint tests ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_vapid_public_key() -> None:
    with patch.object(settings, "vapid_public_key", "test-vapid-key"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/v1/push/vapid-public-key")
    assert r.status_code == 200
    assert r.json()["vapid_public_key"] == "test-vapid-key"


@pytest.mark.asyncio
async def test_get_vapid_public_key_503_when_not_configured() -> None:
    with patch.object(settings, "vapid_public_key", ""):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/v1/push/vapid-public-key")
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_subscribe_push() -> None:
    user = _user()
    mock_db = AsyncMock()
    mock_db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=None))

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _db_with(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                "/api/v1/push/subscribe",
                json={
                    "endpoint": "https://fcm.example/push/abc",
                    "keys": {"auth": "aaa", "p256dh": "bbb"},
                    "device_hint": "Chrome/120",
                },
            )
        assert r.status_code == 201
        assert r.json()["status"] == "subscribed"
        mock_db.add.assert_called_once()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_unsubscribe_push_deactivates() -> None:
    user = _user()
    sub = _sub(user.id)
    mock_db = AsyncMock()
    mock_db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=sub))

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _db_with(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.request(
                "DELETE",
                "/api/v1/push/unsubscribe",
                json={"endpoint": "https://fcm.example/push/abc"},
            )
        assert r.status_code == 200
        assert sub.is_active is False
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_preferences_creates_defaults() -> None:
    user = _user()
    mock_db = AsyncMock()
    mock_db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=None))

    async def _refresh(obj: Any) -> None:
        if isinstance(obj, NotificationPreferences):
            obj.global_mute = False
            obj.quiet_hours_start = None
            obj.quiet_hours_end = None

    mock_db.refresh = _refresh

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _db_with(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/v1/notifications/preferences")
        assert r.status_code == 200
        data = r.json()
        assert data["global_mute"] is False
        mock_db.add.assert_called_once()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_patch_preferences() -> None:
    user = _user()
    prefs = MagicMock(spec=NotificationPreferences)
    prefs.user_id = user.id
    prefs.global_mute = False
    prefs.quiet_hours_start = None
    prefs.quiet_hours_end = None

    mock_db = AsyncMock()
    mock_db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=prefs))

    async def _refresh(obj: Any) -> None:
        pass

    mock_db.refresh = _refresh

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _db_with(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.patch(
                "/api/v1/notifications/preferences",
                json={
                    "global_mute": True,
                    "quiet_hours_start": "22:00",
                    "quiet_hours_end": "07:00",
                },
            )
        assert r.status_code == 200
        assert prefs.global_mute is True
    finally:
        app.dependency_overrides.clear()
