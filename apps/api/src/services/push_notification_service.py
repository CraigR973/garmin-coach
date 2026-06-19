"""Web Push delivery service.

send_notification() is the single entry point for all push delivery.
It respects preferences (global_mute, quiet hours), calls pywebpush for each
active PushSubscription, and auto-disables subscriptions that accumulate
3 consecutive send failures.
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
from src.models.notification import NotificationPreferences, PushSubscription

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
    title: str,
    body: str,
    data: dict[str, Any] | None = None,
    tag: str | None = None,
) -> int:
    """Deliver a push notification to all active subscriptions for player_id.

    Returns the count of successfully sent pushes. Skips delivery when
    preferences block it. Auto-disables subscriptions after _FAIL_THRESHOLD
    consecutive failures.
    """
    if not settings.vapid_private_key or not settings.vapid_public_key:
        log.debug("VAPID keys not configured — skipping push", player_id=str(player_id))
        return 0

    now = _utc_now()

    # ── Check preferences ─────────────────────────────────────────────────────
    prefs_result = await session.execute(
        select(NotificationPreferences).where(NotificationPreferences.player_id == player_id)
    )
    prefs = prefs_result.scalar_one_or_none()

    suppressed = False
    if prefs is not None:
        suppressed = prefs.global_mute or _is_quiet(prefs, now)

    if suppressed:
        log.debug("notification suppressed by preferences", player_id=str(player_id))
        return 0

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
        except Exception as exc:
            log.error("unexpected push error", error=str(exc))

    return sent
