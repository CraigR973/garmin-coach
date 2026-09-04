from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import (
    Activity,
    TemperatureReading,
    WeatherDaily,
)
from src.models.profile import Profile
from src.services.day_context_loaders import (
    load_activities,
    load_knowledge_base_content,
    load_latest_temperature,
    load_weather,
)
from src.services.driver_levers import describe_evidence, select_levers
from src.services.environment_freshness import is_hive_temperature_fresh
from src.services.insights import DriversReport, InsightsService
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
        # Batch 249 (HS240-11): one gate, applied here, so the projection reports
        # what ``driver_levers`` allows rather than re-deciding it more loosely.
        # ``"sleep_score"`` is not in ``FLAG_OUTCOMES``, so it resolves through
        # ``DEFAULT_FLAG_OUTCOME`` to the sleep-score correlations this surface has
        # always been about — via the same mapping the chronic card uses, so the
        # two can never drift apart again.
        sleep_drivers = [
            SleepDriverEvidence(
                driver=lever.correlation.driver,
                coefficient=lever.correlation.coefficient,
                sample_count=lever.correlation.sample_count,
                summary=lever.correlation.summary,
                evidence_sentence=describe_evidence(lever.correlation),
                confounds=lever.confounds,
            )
            for lever in select_levers("sleep_score", drivers_report.outcomes)
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

    # Batch 253 (CR236-12): these four were a line-level copy of
    # ``DailyLoopService``'s. The app card and the evening push describe the same
    # day, and nothing compares them — so they now read through one assembly.
    async def _activities(
        self,
        user_id: uuid.UUID,
        subject_date: date,
        timezone_name: str,
    ) -> list[Activity]:
        return await load_activities(self.session, user_id, subject_date, timezone_name)

    async def _latest_temperature(self, user_id: uuid.UUID) -> TemperatureReading | None:
        return await load_latest_temperature(self.session, user_id)

    async def _knowledge_base_content(self, user_id: uuid.UUID, section: str) -> dict[str, Any]:
        return await load_knowledge_base_content(self.session, user_id, section)

    async def _weather(self, user_id: uuid.UUID, subject_date: date) -> WeatherDaily | None:
        return await load_weather(self.session, user_id, subject_date)


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
