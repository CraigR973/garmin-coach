"""Web Push delivery service.

send_notification() is the single entry point for all push delivery.
It respects preferences (global_mute, per-category toggles, quiet hours),
calls pywebpush for each active PushSubscription, auto-disables subscriptions
that accumulate 3 consecutive send failures, and writes a NotificationLog row
for every attempt.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from functools import partial
from typing import Any
from uuid import UUID

import structlog
from pywebpush import WebPushException, webpush  # type: ignore[import-untyped,unused-ignore]
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models.notification import (
    DeliveryStatus,
    NotificationLog,
    NotificationType,
)
from src.models.prediction import NotificationPreferences, PushSubscription

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

_FAIL_THRESHOLD = 3


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _is_quiet(prefs: NotificationPreferences, now: datetime) -> bool:
    """Return True if now falls within the player's configured quiet hours."""
    if prefs.quiet_hours_start is None or prefs.quiet_hours_end is None:
        return False
    start = prefs.quiet_hours_start.time()
    end = prefs.quiet_hours_end.time()
    t = now.time()
    if start <= end:
        return start <= t < end
    # Overnight window (e.g. 23:00 – 07:00)
    return t >= start or t < end


def _pref_enabled(prefs: NotificationPreferences, ntype: NotificationType) -> bool:
    mapping: dict[NotificationType, bool] = {
        NotificationType.deadline_warning: prefs.deadline_warning,
        NotificationType.predict_reminder: prefs.predict_reminder,
        NotificationType.pick_confirmation: prefs.pick_confirmation,
        NotificationType.match_locked: prefs.match_locked,
        NotificationType.result_detected: prefs.result_detected,
        NotificationType.leaderboard_shift: prefs.leaderboard_shift,
        NotificationType.round_complete: prefs.round_complete,
        NotificationType.match_postponed: prefs.match_postponed,
        NotificationType.special_results: prefs.special_results,
        # These types are always delivered regardless of per-category toggles
        NotificationType.kickoff_changed: True,
        NotificationType.invite_accepted: True,
        NotificationType.auto_sync_failed: True,
        NotificationType.specials_revealed: True,
    }
    return mapping.get(ntype, True)


def _default_pref_enabled(ntype: NotificationType) -> bool:
    defaults: dict[NotificationType, bool] = {
        NotificationType.pick_confirmation: False,
    }
    return defaults.get(ntype, True)


def _send_push_sync(subscription_data: dict[str, Any], payload: str) -> None:
    """Blocking push send — run in a thread executor."""
    webpush(
        subscription_info=subscription_data,
        data=payload,
        vapid_private_key=settings.vapid_private_key,
        vapid_claims={"sub": f"mailto:{settings.vapid_contact_email}"},
        content_encoding="aes128gcm",
    )


async def send_notification(
    session: AsyncSession,
    player_id: UUID,
    notification_type: NotificationType,
    title: str,
    body: str,
    data: dict[str, Any] | None = None,
    match_id: UUID | None = None,
    tag: str | None = None,
) -> int:
    """Deliver a push notification to all active subscriptions for player_id.

    Returns the count of successfully sent pushes. Skips delivery (and logs
    as suppressed) when preferences block it. Auto-disables subscriptions
    after _FAIL_THRESHOLD consecutive failures.

    `tag`, when set, is forwarded to the service worker's showNotification so a
    newer notification with the same tag replaces an older one in the tray
    (e.g. successive reminders for one match, or the daily digest) instead of
    stacking.
    """
    if not settings.vapid_private_key or not settings.vapid_public_key:
        log.debug("VAPID keys not configured — skipping push", player_id=str(player_id))
        return 0

    now = _utc_now()

    # ── Fetch or create preferences ──────────────────────────────────────────
    prefs_result = await session.execute(
        select(NotificationPreferences).where(NotificationPreferences.player_id == player_id)
    )
    prefs = prefs_result.scalar_one_or_none()

    if prefs is None:
        # Player hasn't customised preferences — respect model defaults.
        suppressed = not _default_pref_enabled(notification_type)
    else:
        suppressed = (
            prefs.global_mute
            or not _pref_enabled(prefs, notification_type)
            or _is_quiet(prefs, now)
        )

    # ── Fetch active subscriptions ────────────────────────────────────────────
    subs_result = await session.execute(
        select(PushSubscription).where(
            PushSubscription.player_id == player_id,
            PushSubscription.is_active.is_(True),
        )
    )
    subscriptions = list(subs_result.scalars().all())

    if not subscriptions:
        return 0

    if suppressed:
        for sub in subscriptions:
            session.add(
                NotificationLog(
                    player_id=player_id,
                    notification_type=notification_type,
                    title=title,
                    body=body,
                    match_id=match_id,
                    sent_at=now,
                    delivery_status=DeliveryStatus.suppressed,
                )
            )
        log.debug("notification suppressed", player_id=str(player_id), type=notification_type)
        return 0

    payload_obj: dict[str, Any] = {"title": title, "body": body, "data": data or {}}
    if tag is not None:
        payload_obj["tag"] = tag
    payload = json.dumps(payload_obj)
    sent = 0

    loop = asyncio.get_event_loop()
    for sub in subscriptions:
        sub_info: dict[str, Any] = {
            "endpoint": sub.subscription.get("endpoint", ""),
            "keys": sub.subscription.get("keys", {}),
        }
        try:
            await loop.run_in_executor(None, partial(_send_push_sync, sub_info, payload))
            sub.failed_send_count = 0
            sub.last_used_at = now
            status = DeliveryStatus.sent
            sent += 1
        except WebPushException as exc:
            log.warning(
                "push send failed",
                player_id=str(player_id),
                subscription_id=str(sub.id),
                error=str(exc),
            )
            sub.failed_send_count = (sub.failed_send_count or 0) + 1
            if sub.failed_send_count >= _FAIL_THRESHOLD:
                sub.is_active = False
                log.info(
                    "push subscription auto-disabled",
                    subscription_id=str(sub.id),
                    fail_count=sub.failed_send_count,
                )
            status = DeliveryStatus.failed
        except Exception as exc:
            log.error("unexpected push error", error=str(exc))
            status = DeliveryStatus.failed

        session.add(
            NotificationLog(
                player_id=player_id,
                notification_type=notification_type,
                title=title,
                body=body,
                match_id=match_id,
                sent_at=now,
                delivery_status=status,
            )
        )

    return sent
