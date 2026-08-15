"""Shared activity date helpers."""

from __future__ import annotations

from datetime import UTC, date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from src.models.coaching import Activity


def timezone_or_utc(timezone_name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name or "UTC")
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def activity_local_date(activity: Activity, timezone_name: str | None) -> date:
    return activity.start_utc.replace(tzinfo=UTC).astimezone(timezone_or_utc(timezone_name)).date()
