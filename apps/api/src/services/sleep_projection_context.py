from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import (
    Activity,
    KnowledgeBase,
    TemperatureReading,
    WeatherDaily,
)
from src.models.profile import Profile
from src.services.activity_dates import activity_local_date as _activity_local_date
from src.services.environment_freshness import is_hive_temperature_fresh
from src.services.insights import OUTCOME_SLEEP_SCORE, DriversReport, InsightsService
from src.services.sleep_projection import (
    SleepDriverEvidence,
    SleepProjectionInputs,
    SleepProjectionResult,
    TrainingSignal,
    project_sleep,
)

if TYPE_CHECKING:
    from src.services.daily_loop import DailyLoopSnapshot


@dataclass(frozen=True)
class SleepProjectionSource:
    activities: Sequence[Activity]
    sleep_protocol: dict[str, Any]
    latest_temperature: TemperatureReading | None
    weather: WeatherDaily | None


@dataclass(frozen=True)
class SleepProjectionBuild:
    projection: SleepProjectionResult
    drivers_report: DriversReport


class SleepProjectionContextService:
    """Assemble the one projection shared by the app and evening push."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def build(
        self,
        profile: Profile,
        *,
        subject_date: date,
        now_utc: datetime | None = None,
    ) -> SleepProjectionBuild:
        """Load the projection's focused inputs for a non-daily-loop caller."""
        source = SleepProjectionSource(
            activities=await self._activities(profile.id, subject_date, profile.timezone),
            sleep_protocol=await self._knowledge_base_content(profile.id, "sleep_protocol"),
            latest_temperature=await self._latest_temperature(profile.id),
            weather=await self._weather(profile.id, subject_date),
        )
        return await self._project(profile, subject_date, source, now_utc=now_utc)

    async def build_from_snapshot(
        self,
        profile: Profile,
        snapshot: DailyLoopSnapshot,
        *,
        now_utc: datetime | None = None,
    ) -> SleepProjectionBuild:
        """Reuse rows the daily-loop already loaded without re-querying them."""
        source = SleepProjectionSource(
            activities=snapshot.activities,
            sleep_protocol=snapshot.sleep_protocol,
            latest_temperature=snapshot.latest_temperature,
            weather=snapshot.weather,
        )
        return await self._project(profile, snapshot.subject_date, source, now_utc=now_utc)

    async def _project(
        self,
        profile: Profile,
        subject_date: date,
        source: SleepProjectionSource,
        *,
        now_utc: datetime | None,
    ) -> SleepProjectionBuild:
        drivers_report = await InsightsService(self.session).cached_drivers(
            profile,
            as_of=subject_date,
        )
        sleep_drivers = [
            SleepDriverEvidence(
                driver=driver.driver,
                coefficient=driver.coefficient,
                sample_count=driver.sample_count,
                summary=driver.summary,
            )
            for driver in drivers_report.outcomes.get(OUTCOME_SLEEP_SCORE, [])
        ]
        fresh_temperature = (
            source.latest_temperature
            if is_hive_temperature_fresh(
                source.latest_temperature.captured_at_utc if source.latest_temperature else None,
                now_utc=now_utc,
            )
            else None
        )
        result = project_sleep(
            SleepProjectionInputs(
                training=_activity_training_signals(source.activities, profile.timezone),
                sleep_drivers=sleep_drivers,
                sleep_protocol=source.sleep_protocol,
                latest_bedroom_temperature_c=(
                    round(float(fresh_temperature.temperature_c), 1)
                    if fresh_temperature is not None
                    else None
                ),
                overnight_low_c=(
                    source.weather.overnight_low_c if source.weather is not None else None
                ),
                overnight_wind_max_mph=(
                    source.weather.overnight_wind_max_mph if source.weather is not None else None
                ),
                fan_auto_enabled=profile.fan_auto_enabled,
            )
        )
        return SleepProjectionBuild(projection=result, drivers_report=drivers_report)

    async def _activities(
        self,
        user_id: uuid.UUID,
        subject_date: date,
        timezone_name: str,
    ) -> list[Activity]:
        day_start = datetime(subject_date.year, subject_date.month, subject_date.day)
        rows = (
            (
                await self.session.execute(
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
        return [row for row in rows if _activity_local_date(row, timezone_name) == subject_date]

    async def _latest_temperature(self, user_id: uuid.UUID) -> TemperatureReading | None:
        return (
            (
                await self.session.execute(
                    select(TemperatureReading)
                    .where(TemperatureReading.user_id == user_id)
                    .order_by(TemperatureReading.captured_at_utc.desc())
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )

    async def _knowledge_base_content(self, user_id: uuid.UUID, section: str) -> dict[str, Any]:
        row = await self.session.scalar(
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

    async def _weather(self, user_id: uuid.UUID, subject_date: date) -> WeatherDaily | None:
        return (
            (
                await self.session.execute(
                    select(WeatherDaily).where(
                        WeatherDaily.user_id == user_id,
                        WeatherDaily.calendar_date == subject_date,
                    )
                )
            )
            .scalars()
            .first()
        )


def _activity_training_signals(
    activities: Sequence[Activity],
    timezone_name: str,
) -> list[TrainingSignal]:
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        zone = ZoneInfo("UTC")
    return [
        TrainingSignal(
            name=activity.activity_name,
            activity_type=activity.activity_type,
            local_start=activity.start_utc.replace(tzinfo=UTC).astimezone(zone).time(),
            duration_min=(
                round(float(activity.duration_sec) / 60, 1)
                if activity.duration_sec is not None
                else None
            ),
            training_load=(
                float(activity.training_load) if activity.training_load is not None else None
            ),
            aerobic_training_effect=(
                float(activity.aerobic_training_effect)
                if activity.aerobic_training_effect is not None
                else None
            ),
            anaerobic_training_effect=(
                float(activity.anaerobic_training_effect)
                if activity.anaerobic_training_effect is not None
                else None
            ),
        )
        for activity in activities
    ]
