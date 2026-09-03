"""A profile's local clock — the one place that turns a timezone string into now.

Batch 251 (CR236-02): extracted from ``scheduler.py`` so the morning pipeline can
read a profile's local date without importing the scheduler. Pure, no session, no
IO; a profile carrying an unknown IANA name falls back to UTC rather than raising
inside a job loop.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from src.models.profile import Profile


def profile_zone(profile: Profile) -> ZoneInfo:
    try:
        return ZoneInfo(profile.timezone)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def profile_now(profile: Profile) -> datetime:
    """Timezone-aware 'now' in the profile's local zone (the wake-check clock)."""
    return datetime.now(profile_zone(profile))


def profile_today(profile: Profile) -> date:
    return profile_now(profile).date()
