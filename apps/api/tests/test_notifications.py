"""Tests for Phase 10.2 — push subscription endpoints and push_notification_service."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.auth import get_current_player
from src.config import settings
from src.database import get_db
from src.main import app
from src.models.notification import DeliveryStatus, NotificationType
from src.models.prediction import NotificationPreferences, PushSubscription
from src.models.profile import Profile
from src.services.push_notification_service import (
    _is_quiet,
    _pref_enabled,
    send_notification,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _player(display_name: str = "Alice") -> MagicMock:
    p = MagicMock(spec=Profile)
    p.avatar_url = None  # U23: prevent MagicMock default from failing Pydantic
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


def _sub(player_id: uuid.UUID, endpoint: str = "https://fcm.example/push/abc") -> MagicMock:
    s = MagicMock(spec=PushSubscription)
    s.id = uuid.uuid4()
    s.player_id = player_id
    s.subscription = {"endpoint": endpoint, "keys": {"auth": "x", "p256dh": "y"}}
    s.is_active = True
    s.failed_send_count = 0
    s.last_used_at = None
    return s


def _prefs(player_id: uuid.UUID, **overrides: Any) -> MagicMock:
    p = MagicMock(spec=NotificationPreferences)
    p.player_id = player_id
    p.deadline_warning = True
    p.predict_reminder = True
    p.pick_confirmation = False
    p.match_locked = True
    p.result_detected = True
    p.leaderboard_shift = True
    p.round_complete = True
    p.match_postponed = True
    p.special_results = True
    p.global_mute = False
    p.quiet_hours_start = None
    p.quiet_hours_end = None
    for k, v in overrides.items():
        setattr(p, k, v)
    return p


# ── Unit tests: preference helpers ────────────────────────────────────────────


class TestIsQuiet:
    def test_no_quiet_hours_never_quiet(self) -> None:
        prefs = _prefs(uuid.uuid4())
        prefs.quiet_hours_start = None
        prefs.quiet_hours_end = None
        assert _is_quiet(prefs, datetime(2026, 6, 1, 23, 0)) is False

    def test_quiet_within_range(self) -> None:
        prefs = _prefs(uuid.uuid4())
        prefs.quiet_hours_start = datetime(2000, 1, 1, 23, 0)
        prefs.quiet_hours_end = datetime(2000, 1, 1, 7, 0)
        # 23:30 is in 23:00–07:00 overnight window
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


class TestPrefEnabled:
    def test_returns_false_when_category_disabled(self) -> None:
        prefs = _prefs(uuid.uuid4(), result_detected=False)
        assert _pref_enabled(prefs, NotificationType.result_detected) is False

    def test_invite_accepted_always_true(self) -> None:
        prefs = _prefs(uuid.uuid4())
        assert _pref_enabled(prefs, NotificationType.invite_accepted) is True

    def test_auto_sync_failed_always_true(self) -> None:
        prefs = _prefs(uuid.uuid4())
        assert _pref_enabled(prefs, NotificationType.auto_sync_failed) is True

    def test_predict_reminder_defaults_to_enabled(self) -> None:
        prefs = _prefs(uuid.uuid4(), predict_reminder=True)
        assert _pref_enabled(prefs, NotificationType.predict_reminder) is True

    def test_pick_confirmation_defaults_to_disabled(self) -> None:
        prefs = _prefs(uuid.uuid4(), pick_confirmation=False)
        assert _pref_enabled(prefs, NotificationType.pick_confirmation) is False


# ── Unit tests: send_notification ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_notification_skips_when_no_vapid() -> None:
    session = AsyncMock()
    with (
        patch.object(settings, "vapid_private_key", ""),
        patch.object(settings, "vapid_public_key", ""),
    ):
        sent = await send_notification(
            session, uuid.uuid4(), NotificationType.result_detected, "T", "B"
        )
    assert sent == 0


@pytest.mark.asyncio
async def test_send_notification_suppressed_when_global_mute() -> None:
    player_id = uuid.uuid4()
    sub = _sub(player_id)
    prefs = _prefs(player_id, global_mute=True)

    session = AsyncMock()
    session.execute.side_effect = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=prefs)),
        MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[sub])))),
    ]

    with (
        patch.object(settings, "vapid_private_key", "private"),
        patch.object(settings, "vapid_public_key", "public"),
    ):
        sent = await send_notification(
            session, player_id, NotificationType.result_detected, "T", "B"
        )
    assert sent == 0
    session.add.assert_called()
    log_call = session.add.call_args[0][0]
    assert log_call.delivery_status == DeliveryStatus.suppressed


@pytest.mark.asyncio
async def test_send_notification_suppressed_when_predict_reminder_disabled() -> None:
    player_id = uuid.uuid4()
    sub = _sub(player_id)
    prefs = _prefs(player_id, predict_reminder=False)

    session = AsyncMock()
    session.execute.side_effect = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=prefs)),
        MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[sub])))),
    ]

    with (
        patch.object(settings, "vapid_private_key", "private"),
        patch.object(settings, "vapid_public_key", "public"),
    ):
        sent = await send_notification(
            session, player_id, NotificationType.predict_reminder, "T", "B"
        )
    assert sent == 0
    log_call = session.add.call_args[0][0]
    assert log_call.notification_type == NotificationType.predict_reminder
    assert log_call.delivery_status == DeliveryStatus.suppressed


@pytest.mark.asyncio
async def test_send_notification_suppressed_when_pick_confirmation_default_off() -> None:
    player_id = uuid.uuid4()
    sub = _sub(player_id)
    prefs = _prefs(player_id, pick_confirmation=False)

    session = AsyncMock()
    session.execute.side_effect = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=prefs)),
        MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[sub])))),
    ]

    with (
        patch.object(settings, "vapid_private_key", "private"),
        patch.object(settings, "vapid_public_key", "public"),
    ):
        sent = await send_notification(
            session, player_id, NotificationType.pick_confirmation, "T", "B"
        )
    assert sent == 0
    log_call = session.add.call_args[0][0]
    assert log_call.notification_type == NotificationType.pick_confirmation
    assert log_call.delivery_status == DeliveryStatus.suppressed


@pytest.mark.asyncio
async def test_send_notification_delivers_pick_confirmation_when_enabled() -> None:
    player_id = uuid.uuid4()
    sub = _sub(player_id)
    prefs = _prefs(player_id, pick_confirmation=True)

    session = AsyncMock()
    session.execute.side_effect = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=prefs)),
        MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[sub])))),
    ]

    with (
        patch.object(settings, "vapid_private_key", "priv"),
        patch.object(settings, "vapid_public_key", "pub"),
        patch("src.services.push_notification_service._send_push_sync"),
    ):
        sent = await send_notification(
            session, player_id, NotificationType.pick_confirmation, "Title", "Body"
        )

    assert sent == 1
    log_call = session.add.call_args[0][0]
    assert log_call.notification_type == NotificationType.pick_confirmation
    assert log_call.delivery_status == DeliveryStatus.sent


@pytest.mark.asyncio
async def test_send_notification_suppressed_during_quiet_hours_for_predict_reminder() -> None:
    player_id = uuid.uuid4()
    sub = _sub(player_id)
    prefs = _prefs(
        player_id,
        quiet_hours_start=datetime(2000, 1, 1, 9, 0),
        quiet_hours_end=datetime(2000, 1, 1, 17, 0),
    )

    session = AsyncMock()
    session.execute.side_effect = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=prefs)),
        MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[sub])))),
    ]

    with (
        patch.object(settings, "vapid_private_key", "private"),
        patch.object(settings, "vapid_public_key", "public"),
        patch(
            "src.services.push_notification_service._utc_now",
            return_value=datetime(2026, 6, 1, 10, 0),
        ),
    ):
        sent = await send_notification(
            session, player_id, NotificationType.predict_reminder, "T", "B"
        )
    assert sent == 0
    log_call = session.add.call_args[0][0]
    assert log_call.delivery_status == DeliveryStatus.suppressed


@pytest.mark.asyncio
async def test_send_notification_delivers_and_logs() -> None:
    player_id = uuid.uuid4()
    sub = _sub(player_id)
    prefs = _prefs(player_id)

    session = AsyncMock()
    session.execute.side_effect = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=prefs)),
        MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[sub])))),
    ]

    with (
        patch.object(settings, "vapid_private_key", "priv"),
        patch.object(settings, "vapid_public_key", "pub"),
        patch("src.services.push_notification_service._send_push_sync"),
    ):  # no-op push
        sent = await send_notification(
            session, player_id, NotificationType.result_detected, "Title", "Body"
        )

    assert sent == 1
    log_call = session.add.call_args[0][0]
    assert log_call.delivery_status == DeliveryStatus.sent


@pytest.mark.asyncio
async def test_send_notification_auto_disables_after_3_failures() -> None:
    from pywebpush import WebPushException

    player_id = uuid.uuid4()
    sub = _sub(player_id)
    sub.failed_send_count = 2  # one more failure should disable
    prefs = _prefs(player_id)

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
        sent = await send_notification(
            session, player_id, NotificationType.result_detected, "T", "B"
        )

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
    player = _player()
    mock_db = AsyncMock()
    mock_db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=None))

    app.dependency_overrides[get_current_player] = lambda: player
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
    player = _player()
    sub = _sub(player.id)
    mock_db = AsyncMock()
    mock_db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=sub))

    app.dependency_overrides[get_current_player] = lambda: player
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
    player = _player()
    mock_db = AsyncMock()
    mock_db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=None))

    created_prefs: list[NotificationPreferences] = []

    async def _refresh(obj: Any) -> None:
        if isinstance(obj, NotificationPreferences):
            # Simulate the DB setting defaults
            obj.deadline_warning = True
            obj.predict_reminder = True
            obj.pick_confirmation = False
            obj.match_locked = True
            obj.result_detected = True
            obj.leaderboard_shift = True
            obj.round_complete = True
            obj.match_postponed = True
            obj.special_results = True
            obj.global_mute = False
            obj.quiet_hours_start = None
            obj.quiet_hours_end = None
            created_prefs.append(obj)

    mock_db.refresh = _refresh

    app.dependency_overrides[get_current_player] = lambda: player
    app.dependency_overrides[get_db] = _db_with(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/v1/notifications/preferences")
        assert r.status_code == 200
        data = r.json()
        assert data["global_mute"] is False
        assert data["deadline_warning"] is True
        assert data["predict_reminder"] is True
        assert data["pick_confirmation"] is False
        mock_db.add.assert_called_once()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_patch_preferences() -> None:
    player = _player()
    prefs = MagicMock(spec=NotificationPreferences)
    prefs.player_id = player.id
    prefs.deadline_warning = True
    prefs.predict_reminder = True
    prefs.pick_confirmation = False
    prefs.match_locked = True
    prefs.result_detected = True
    prefs.leaderboard_shift = True
    prefs.round_complete = True
    prefs.match_postponed = True
    prefs.special_results = True
    prefs.global_mute = False
    prefs.quiet_hours_start = None
    prefs.quiet_hours_end = None

    mock_db = AsyncMock()
    mock_db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=prefs))

    async def _refresh(obj: Any) -> None:
        pass

    mock_db.refresh = _refresh

    app.dependency_overrides[get_current_player] = lambda: player
    app.dependency_overrides[get_db] = _db_with(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.patch(
                "/api/v1/notifications/preferences",
                json={
                    "global_mute": True,
                    "predict_reminder": False,
                    "pick_confirmation": True,
                    "result_detected": False,
                    "quiet_hours_start": "22:00",
                    "quiet_hours_end": "07:00",
                },
            )
        assert r.status_code == 200
        assert prefs.global_mute is True
        assert prefs.predict_reminder is False
        assert prefs.pick_confirmation is True
        assert prefs.result_detected is False
    finally:
        app.dependency_overrides.clear()
