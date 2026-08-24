"""Durable current-day input presence for the morning sync/read boundary."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import DAILY_METRIC_PHASE_MORNING, DailyMetric, Sleep


@dataclass(frozen=True, slots=True)
class MorningInputPresence:
    """What the app can prove it has for one wake date.

    A morning ``DailyMetric`` row is written on every successful full Garmin pull,
    even when Garmin returns no sleep session. Before the 11:00 backstop we still
    require ``Sleep`` so a lagging but real night keeps the wake poll alive. At the
    backstop, a daily row without sleep is an honest successful pull from a
    watch-not-worn/no-session day rather than an unsynced day.
    """

    daily_metrics: bool
    sleep: bool

    @property
    def version(self) -> str:
        """Low-cardinality generation input: presence, never health values."""

        return f"daily_metrics:{int(self.daily_metrics)}|sleep:{int(self.sleep)}"

    def ready_for_read(self, *, allow_missing_sleep: bool) -> bool:
        return self.daily_metrics and (self.sleep or allow_missing_sleep)


async def morning_input_presence(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    subject_date: date,
) -> MorningInputPresence:
    daily_exists = (
        select(DailyMetric.id)
        .where(
            DailyMetric.user_id == user_id,
            DailyMetric.calendar_date == subject_date,
            DailyMetric.phase == DAILY_METRIC_PHASE_MORNING,
        )
        .exists()
    )
    sleep_exists = (
        select(Sleep.id)
        .where(Sleep.user_id == user_id, Sleep.calendar_date == subject_date)
        .exists()
    )
    row = (await session.execute(select(daily_exists, sleep_exists))).one()
    return MorningInputPresence(daily_metrics=bool(row[0]), sleep=bool(row[1]))


def morning_packet_input_presence(packet: Mapping[str, Any]) -> MorningInputPresence:
    """Read presence from a stored packet, including packets from before Batch 222."""

    return MorningInputPresence(
        daily_metrics=packet.get("dailyMetrics") is not None,
        sleep=packet.get("sleep") is not None,
    )
