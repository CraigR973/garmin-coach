"""Push subscription and notification preference endpoints."""

from __future__ import annotations

from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import CurrentPlayer
from src.config import settings
from src.database import get_db
from src.models.notification import NotificationPreferences, PushSubscription
from src.rate_limit import limiter, per_player_key
from src.services.push_notification_service import send_notification

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["notifications"])

Db = Annotated[AsyncSession, Depends(get_db)]


# ── Schemas ───────────────────────────────────────────────────────────────────


class SubscribeRequest(BaseModel):
    endpoint: str
    keys: dict[str, str]
    device_hint: str | None = None


class UnsubscribeRequest(BaseModel):
    endpoint: str


class PreferencesOut(BaseModel):
    global_mute: bool
    quiet_hours_start: str | None  # "HH:MM"
    quiet_hours_end: str | None  # "HH:MM"


class PreferencesPatch(BaseModel):
    global_mute: bool | None = None
    quiet_hours_start: str | None = None  # "HH:MM" or empty string to clear
    quiet_hours_end: str | None = None


# ── VAPID public key ──────────────────────────────────────────────────────────


@router.get("/push/vapid-public-key")
async def get_vapid_public_key() -> dict[str, str]:
    """Return the VAPID public key for client-side push subscription."""
    if not settings.vapid_public_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Push not configured",
        )
    return {"vapid_public_key": settings.vapid_public_key}


# ── Push subscription management ──────────────────────────────────────────────


@router.post("/push/subscribe", status_code=status.HTTP_201_CREATED)
async def subscribe_push(
    body: SubscribeRequest,
    player: CurrentPlayer,
    db: Db,
) -> dict[str, str]:
    """Store a new push subscription for the authenticated player."""
    subscription_data: dict[str, Any] = {"endpoint": body.endpoint, "keys": body.keys}

    result = await db.execute(
        select(PushSubscription).where(
            PushSubscription.player_id == player.id,
            PushSubscription.subscription["endpoint"].astext == body.endpoint,
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        existing.subscription = subscription_data
        existing.is_active = True
        existing.failed_send_count = 0
        if body.device_hint:
            existing.device_hint = body.device_hint
    else:
        db.add(
            PushSubscription(
                player_id=player.id,
                subscription=subscription_data,
                device_hint=body.device_hint,
            )
        )

    await db.commit()
    log.info("push subscription stored", player_id=str(player.id))
    return {"status": "subscribed"}


@router.delete("/push/unsubscribe", status_code=status.HTTP_200_OK)
async def unsubscribe_push(
    body: UnsubscribeRequest,
    player: CurrentPlayer,
    db: Db,
) -> dict[str, str]:
    """Deactivate a push subscription by endpoint."""
    result = await db.execute(
        select(PushSubscription).where(
            PushSubscription.player_id == player.id,
            PushSubscription.subscription["endpoint"].astext == body.endpoint,
        )
    )
    sub = result.scalar_one_or_none()
    if sub:
        sub.is_active = False
        await db.commit()
    return {"status": "unsubscribed"}


# ── Test push ────────────────────────────────────────────────────────────────


@router.post("/push/test", status_code=status.HTTP_200_OK)
@limiter.limit("5/hour", key_func=per_player_key)
async def test_push(request: Request, player: CurrentPlayer, db: Db) -> dict[str, Any]:
    """Send a test push notification to the authenticated player."""
    sent = await send_notification(
        session=db,
        player_id=player.id,
        title="Garmin Coach — test",
        body="Push notifications are working!",
        data={"url": "/"},
    )
    await db.commit()
    return {"sent": sent}


# ── Notification preferences ──────────────────────────────────────────────────


def _time_str(dt_field: object) -> str | None:
    """Format a datetime column (time-only sentinel) as HH:MM string."""
    from datetime import datetime as _dt

    if dt_field is None:
        return None
    if isinstance(dt_field, _dt):
        return dt_field.strftime("%H:%M")
    return None


@router.get("/notifications/preferences", response_model=PreferencesOut)
async def get_preferences(player: CurrentPlayer, db: Db) -> PreferencesOut:
    """Return the player's notification preferences (creates defaults on first access)."""
    result = await db.execute(
        select(NotificationPreferences).where(NotificationPreferences.player_id == player.id)
    )
    prefs = result.scalar_one_or_none()

    if prefs is None:
        prefs = NotificationPreferences(player_id=player.id)
        db.add(prefs)
        await db.commit()
        await db.refresh(prefs)

    return PreferencesOut(
        global_mute=prefs.global_mute,
        quiet_hours_start=_time_str(prefs.quiet_hours_start),
        quiet_hours_end=_time_str(prefs.quiet_hours_end),
    )


@router.patch("/notifications/preferences", response_model=PreferencesOut)
async def patch_preferences(
    body: PreferencesPatch,
    player: CurrentPlayer,
    db: Db,
) -> PreferencesOut:
    """Partially update the player's notification preferences."""
    from datetime import datetime as _dt

    result = await db.execute(
        select(NotificationPreferences).where(NotificationPreferences.player_id == player.id)
    )
    prefs = result.scalar_one_or_none()
    if prefs is None:
        prefs = NotificationPreferences(player_id=player.id)
        db.add(prefs)

    if body.global_mute is not None:
        prefs.global_mute = body.global_mute

    def _parse_time(val: str | None) -> _dt | None:
        if val is None:
            return None
        if val == "":
            return None
        try:
            h, m = map(int, val.split(":"))
            return _dt(2000, 1, 1, h, m)
        except (ValueError, AttributeError):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid time format: {val!r}",
            )

    if body.quiet_hours_start is not None:
        prefs.quiet_hours_start = _parse_time(body.quiet_hours_start)
    if body.quiet_hours_end is not None:
        prefs.quiet_hours_end = _parse_time(body.quiet_hours_end)

    await db.commit()
    await db.refresh(prefs)

    return PreferencesOut(
        global_mute=prefs.global_mute,
        quiet_hours_start=_time_str(prefs.quiet_hours_start),
        quiet_hours_end=_time_str(prefs.quiet_hours_end),
    )
