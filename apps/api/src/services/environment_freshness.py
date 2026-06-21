from __future__ import annotations

from datetime import UTC, datetime, timedelta

HIVE_FRESHNESS_LIMIT = timedelta(minutes=45)


def is_hive_temperature_fresh(
    captured_at_utc: datetime | None,
    *,
    now_utc: datetime | None = None,
) -> bool:
    if captured_at_utc is None:
        return False

    captured = (
        captured_at_utc.replace(tzinfo=UTC)
        if captured_at_utc.tzinfo is None
        else captured_at_utc
    )
    now = now_utc or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return now - captured <= HIVE_FRESHNESS_LIMIT
