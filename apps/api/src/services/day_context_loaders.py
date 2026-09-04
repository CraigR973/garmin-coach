"""The four day-context loaders both the daily loop and the sleep projection use.

Batch 253 (CR236-12, and CR189-14 before it). ``DailyLoopService`` and
``SleepProjectionContextService`` each carried a line-level copy of these four
reads: the same SQL, the same filters, the same timezone handling, differing only
in two temporary variables. Batch 184 recorded them as "one assembly"; Batch 189
recorded them as "behaviourally holds; structurally a copy". They are now one
assembly in fact.

Why it mattered rather than merely offended: the Home card and the evening sleep
push are meant to describe the same day, and nothing compares them. Batch 235's
egress work had to be applied to each history read individually, and a sweep like
that has to *remember* there are two copies. A divergence here is invisible.

These are deliberately free functions rather than a mixin — they need a session, a
user, a date and a timezone, and nothing else, so anything may call them without
inheriting a service.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import Activity, KnowledgeBase, TemperatureReading, WeatherDaily
from src.services.activity_dates import activity_local_date


async def load_activities(
    session: AsyncSession,
    user_id: uuid.UUID,
    subject_date: date,
    timezone_name: str,
) -> list[Activity]:
    """Every activity that falls on ``subject_date`` in the profile's local zone.

    The UTC window is deliberately wider than the day (D-1 to D+2) and narrowed
    afterwards, because a local day is not a UTC day and the column is UTC.
    """
    day_start = datetime(subject_date.year, subject_date.month, subject_date.day)
    rows = (
        (
            await session.execute(
                select(Activity)
                .where(
                    Activity.user_id == user_id,
                    Activity.start_utc >= day_start - timedelta(days=1),
                    Activity.start_utc < day_start + timedelta(days=2),
                )
                .order_by(Activity.start_utc.asc())
            )
        )
        .scalars()
        .all()
    )
    return [row for row in rows if activity_local_date(row, timezone_name) == subject_date]


async def load_latest_temperature(
    session: AsyncSession, user_id: uuid.UUID
) -> TemperatureReading | None:
    return (
        (
            await session.execute(
                select(TemperatureReading)
                .where(TemperatureReading.user_id == user_id)
                .order_by(TemperatureReading.captured_at_utc.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )


async def load_knowledge_base_content(
    session: AsyncSession, user_id: uuid.UUID, section: str
) -> dict[str, Any]:
    row = await session.scalar(
        select(KnowledgeBase)
        .where(
            KnowledgeBase.user_id == user_id,
            KnowledgeBase.section == section,
            KnowledgeBase.is_active.is_(True),
        )
        .order_by(KnowledgeBase.version.desc())
        .limit(1)
    )
    return row.content if row is not None and isinstance(row.content, dict) else {}


async def load_weather(
    session: AsyncSession, user_id: uuid.UUID, subject_date: date
) -> WeatherDaily | None:
    return (
        (
            await session.execute(
                select(WeatherDaily).where(
                    WeatherDaily.user_id == user_id,
                    WeatherDaily.calendar_date == subject_date,
                )
            )
        )
        .scalars()
        .first()
    )
