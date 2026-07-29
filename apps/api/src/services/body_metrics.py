"""Effective live-Garmin body metrics, resolved at packet-build (Batch 176).

``weight_kg`` on ``daily_metrics`` is only ever set on an exact same-day
weigh-in, so it is null on most days. Rather than persist a carried-forward
copy, resolve the most recent value within a lookback window at read time and
carry its calendar date forward as an explicit as-of date, so a stale weight
is never presented as today's.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import DailyMetric

DEFAULT_WEIGHT_LOOKBACK_DAYS = 7


async def resolve_effective_weight_kg(
    session: AsyncSession,
    user_id: uuid.UUID,
    as_of_date: date,
    *,
    lookback_days: int = DEFAULT_WEIGHT_LOOKBACK_DAYS,
) -> tuple[float | None, date | None]:
    """Most recent non-null ``weight_kg`` within ``lookback_days`` of ``as_of_date``.

    Returns ``(weight_kg, calendar_date)`` for the row it came from, or
    ``(None, None)`` when no weigh-in falls inside the window.
    """

    window_start = as_of_date - timedelta(days=lookback_days)
    rows = (
        (
            await session.execute(
                select(DailyMetric.weight_kg, DailyMetric.calendar_date)
                .where(
                    DailyMetric.user_id == user_id,
                    DailyMetric.calendar_date >= window_start,
                    DailyMetric.calendar_date <= as_of_date,
                    DailyMetric.weight_kg.is_not(None),
                )
                .order_by(DailyMetric.calendar_date.desc())
                .limit(1)
            )
        )
        .tuples()
        .first()
    )
    if rows is None:
        return None, None
    weight_kg, calendar_date = rows
    return weight_kg, calendar_date
