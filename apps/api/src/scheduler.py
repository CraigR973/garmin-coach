"""Background scheduler — APScheduler harness for garmin-coach.

Current jobs:
  - daily_backup: runs at 03:00 UTC
  - hive_temperature_poll: polls Hive indoor temperature every 15 minutes
  - morning_weather_sync: at 06:30 Europe/London, syncs Kilmarnock weather, then
    today's Garmin daily metrics + sleep, triggers the morning analysis, then
    regenerates an adjusted workout proposal on an Amber verdict (Batch 13)
  - garmin_activity_poll: polls Garmin hourly for new rides and triggers analysis
  - workout_autopush: pushes approved workout proposals due a couple of days ahead
  - evening_sleep_nudge: sends the 20:00 sleep-protocol push
  - evening_monitoring_alerts: checks thermal and source freshness before bed
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog
from apscheduler.schedulers.asyncio import (  # type: ignore[import-untyped,unused-ignore]
    AsyncIOScheduler,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database import AsyncSessionLocal
from src.models.notification import ActionType, ActorType, AuditLog
from src.models.profile import Profile
from src.services.backup import create_backup
from src.services.environment_sync import (
    EnvironmentSyncService,
    HiveClient,
    OpenMeteoClient,
    WeatherRequest,
)
from src.services.executable_coaching import ExecutableCoachingService
from src.services.garmin_sync import (
    GarminConnectClient,
    GarminDailyPayloads,
    GarminSyncService,
)
from src.services.morning_analysis import MorningAnalysisService
from src.services.nudge_alerts import NudgeAlertService
from src.services.post_workout_analysis import PostWorkoutAnalysisService

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


async def run_scheduled_backup() -> None:
    """Daily backup job — runs at 03:00 UTC."""
    try:
        info = await create_backup(settings.backup_dir, settings.database_url)
        log.info("scheduled backup complete", filename=info.filename, size_bytes=info.size_bytes)
    except Exception as exc:
        reason = str(exc)
        log.exception("scheduled backup failed")
        async with AsyncSessionLocal() as session:
            session.add(
                AuditLog(
                    actor_id=None,
                    actor_type=ActorType.system,
                    action_type=ActionType.backup_failed,
                    target_table="",
                    target_id=None,
                    changes={"error": reason},
                )
            )
            await session.commit()


async def run_hive_temperature_poll() -> None:
    """Poll Hive indoor temperature for active Hive-linked profiles."""
    try:
        async with AsyncSessionLocal() as session:
            profiles = (
                (
                    await session.execute(
                        select(Profile).where(
                            Profile.is_active.is_(True),
                            Profile.deleted_at.is_(None),
                            Profile.hive_home_id.is_not(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
            if not profiles:
                log.info("hive temperature poll skipped", reason="no_hive_profiles")
                return

            client = HiveClient()
            payloads = await _retry_sync(client.fetch_payloads)
            service = EnvironmentSyncService(session)
            poll_started_utc = datetime.now(UTC).replace(tzinfo=None)
            synced = 0
            for profile in profiles:
                result = await service.sync_hive_temperatures(
                    profile.id,
                    payloads,
                    captured_at_utc=poll_started_utc,
                    commit=False,
                )
                synced += result.temperature_readings_synced
            await session.commit()
        log.info("hive temperature poll complete", profiles=len(profiles), readings=synced)
    except Exception:
        log.exception("hive temperature poll failed")


async def run_evening_sleep_nudge() -> None:
    """Send the daily sleep-protocol nudge in each active profile's timezone."""
    try:
        async with AsyncSessionLocal() as session:
            profiles = await _active_profiles(session)
            if not profiles:
                log.info("evening sleep nudge skipped", reason="no_active_profiles")
                return

            service = NudgeAlertService(session)
            nudges_recorded = 0
            for profile in profiles:
                if await service.run_evening_nudge(profile, commit=False):
                    nudges_recorded += 1
            await session.commit()
        log.info("evening sleep nudge complete", profiles=len(profiles), nudges=nudges_recorded)
    except Exception:
        log.exception("evening sleep nudge failed")


async def run_evening_monitoring_alerts() -> None:
    """Check bedtime thermal state and source freshness for active profiles."""
    try:
        async with AsyncSessionLocal() as session:
            profiles = await _active_profiles(session)
            if not profiles:
                log.info("evening monitoring alerts skipped", reason="no_active_profiles")
                return

            service = NudgeAlertService(session)
            alerts_recorded = 0
            for profile in profiles:
                alerts_recorded += await service.run_monitoring_alerts(profile, commit=False)
            await session.commit()
        log.info(
            "evening monitoring alerts complete",
            profiles=len(profiles),
            alerts=alerts_recorded,
        )
    except Exception:
        log.exception("evening monitoring alerts failed")


async def _sync_garmin_daily(
    session: AsyncSession,
    profiles: list[Profile],
    *,
    client: GarminConnectClient | None = None,
) -> tuple[int, int]:
    """Sync today's Garmin daily metrics + sleep for each profile (429-safe).

    Returns ``(daily_metrics_synced, sleep_synced)``. The fetch is wrapped in an
    exponential-backoff retry so a transient Garmin 429 is survived, and each
    profile's sync is isolated: one profile's Garmin failure is logged and
    skipped so it cannot block the others or the downstream morning analysis.
    The caller commits.
    """
    if not profiles:
        return (0, 0)

    client = client or GarminConnectClient()
    sync_service = GarminSyncService(session)
    daily_synced = 0
    sleep_synced = 0
    for profile in profiles:
        subject_date = _profile_today(profile)
        try:
            payloads: GarminDailyPayloads = await _retry_sync(
                lambda: client.fetch_daily_payloads(subject_date),
                backoff=2.0,
            )
            result = await sync_service.sync_daily(
                profile.id,
                subject_date,
                payloads,
                commit=False,
            )
            daily_synced += result.daily_metrics_synced
            sleep_synced += result.sleep_synced
        except Exception:
            log.exception(
                "garmin daily sync failed",
                profile_id=str(profile.id),
                subject_date=subject_date.isoformat(),
            )
    return (daily_synced, sleep_synced)


async def run_morning_weather_sync() -> None:
    """Sync weather + today's Garmin daily metrics/sleep, then run morning analysis.

    The Garmin daily sync runs *before* the analysis loop so the morning verdict
    reads today's real readiness + sleep instead of empty inputs (Batch 18).
    """
    try:
        async with AsyncSessionLocal() as session:
            profiles = (
                (
                    await session.execute(
                        select(Profile).where(
                            Profile.is_active.is_(True),
                            Profile.deleted_at.is_(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
            service = EnvironmentSyncService(session)
            synced = 0
            analyses_generated = 0
            analyses_existing = 0
            client = OpenMeteoClient()
            for profile in profiles:
                request = WeatherRequest(
                    latitude=profile.latitude or settings.weather_latitude,
                    longitude=profile.longitude or settings.weather_longitude,
                    timezone=profile.timezone or settings.weather_timezone,
                )
                payload = await _retry_async(lambda: client.fetch_daily_payload(request))
                result = await service.sync_weather_daily(
                    profile.id,
                    payload,
                    timezone=request.timezone,
                    commit=False,
                )
                synced += result.weather_days_synced
            await session.commit()

            daily_metrics_synced, sleep_synced = await _sync_garmin_daily(session, list(profiles))
            await session.commit()

            analysis_service = MorningAnalysisService(session)
            coaching_service = ExecutableCoachingService(session)
            proposals_regenerated = 0
            for profile in profiles:
                subject_date = _profile_today(profile)
                try:
                    analysis_result = await analysis_service.generate_and_store(
                        profile,
                        subject_date,
                    )
                    if analysis_result.generated:
                        analyses_generated += 1
                    else:
                        analyses_existing += 1
                except Exception:
                    log.exception(
                        "morning analysis failed",
                        profile_id=str(profile.id),
                        subject_date=subject_date.isoformat(),
                    )
                    continue
                try:
                    proposals = await coaching_service.regenerate_for_verdict(
                        profile,
                        subject_date,
                        analysis=analysis_result.analysis,
                    )
                    proposals_regenerated += len(proposals)
                except Exception:
                    log.exception(
                        "amber regeneration failed",
                        profile_id=str(profile.id),
                        subject_date=subject_date.isoformat(),
                    )
        log.info(
            "morning weather sync complete",
            profiles=len(profiles),
            days=synced,
            daily_metrics=daily_metrics_synced,
            sleep=sleep_synced,
            analyses_generated=analyses_generated,
            analyses_existing=analyses_existing,
            proposals_regenerated=proposals_regenerated,
        )
    except Exception:
        log.exception("morning weather sync failed")


async def run_garmin_activity_poll() -> None:
    """Poll Garmin for recent activities, then trigger post-workout ride analysis."""
    try:
        async with AsyncSessionLocal() as session:
            profiles = (
                (
                    await session.execute(
                        select(Profile).where(
                            Profile.is_active.is_(True),
                            Profile.deleted_at.is_(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
            if not profiles:
                log.info("garmin activity poll skipped", reason="no_active_profiles")
                return

            client = GarminConnectClient()
            sync_service = GarminSyncService(session)
            analysis_service = PostWorkoutAnalysisService(session)
            activities_synced = 0
            timeseries_synced = 0
            analyses_generated = 0
            analyses_existing = 0

            for profile in profiles:
                today = _profile_today(profile)
                start_date = today - timedelta(days=3)
                payloads = await _retry_sync(
                    lambda: client.fetch_activity_payloads(start_date, today)
                )
                sync_result = await sync_service.sync_activities(
                    profile.id,
                    payloads,
                    commit=False,
                )
                activities_synced += sync_result.activities_synced
                timeseries_synced += sync_result.timeseries_samples_synced

                since = datetime.combine(start_date, datetime.min.time()).replace(tzinfo=None)
                try:
                    analysis_results = await analysis_service.generate_for_pending_rides(
                        profile,
                        since=since,
                        commit=False,
                    )
                    analyses_generated += sum(1 for item in analysis_results if item.generated)
                    analyses_existing += sum(1 for item in analysis_results if not item.generated)
                except Exception:
                    log.exception(
                        "post-workout analysis failed",
                        profile_id=str(profile.id),
                    )

            await session.commit()
        log.info(
            "garmin activity poll complete",
            profiles=len(profiles),
            activities=activities_synced,
            timeseries_samples=timeseries_synced,
            analyses_generated=analyses_generated,
            analyses_existing=analyses_existing,
        )
    except Exception:
        log.exception("garmin activity poll failed")


async def run_workout_autopush() -> None:
    """Push approved-but-unpushed workout proposals due a couple of days ahead.

    Only proposals the user already approved are eligible (Decision #29), so this
    delivers the week-ahead automatically (Decision #31) without ever pushing
    something unapproved. Each profile and each push is isolated so one failure
    (e.g. a missing intervals.icu key) cannot block the rest.
    """
    try:
        async with AsyncSessionLocal() as session:
            profiles = await _active_profiles(session)
            if not profiles:
                log.info("workout autopush skipped", reason="no_active_profiles")
                return

            service = ExecutableCoachingService(session)
            pushed = 0
            for profile in profiles:
                try:
                    results = await service.auto_push_due(profile)
                    pushed += len(results)
                except Exception:
                    log.exception(
                        "workout autopush failed for profile",
                        profile_id=str(profile.id),
                    )
        log.info("workout autopush complete", profiles=len(profiles), pushed=pushed)
    except Exception:
        log.exception("workout autopush failed")


async def _active_profiles(session: AsyncSession) -> list[Profile]:
    return list(
        (
            await session.execute(
                select(Profile).where(
                    Profile.is_active.is_(True),
                    Profile.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )


def _profile_today(profile: Profile) -> date:
    try:
        timezone = ZoneInfo(profile.timezone)
    except ZoneInfoNotFoundError:
        timezone = ZoneInfo("UTC")
    return datetime.now(timezone).date()


async def _retry_sync[T](
    operation: Callable[[], T],
    *,
    attempts: int = 3,
    delay_sec: float = 1.0,
    backoff: float = 1.0,
) -> T:
    """Retry a sync operation, sleeping ``delay_sec`` (× ``backoff`` each retry).

    ``backoff > 1.0`` gives exponential backoff, which keeps the Garmin daily
    sync 429-safe without hammering the API on the rate-limit window.
    """
    delay = delay_sec
    for attempt in range(attempts):
        try:
            return operation()
        except Exception:
            if attempt == attempts - 1:
                raise
            await asyncio.sleep(delay)
            delay *= backoff
    raise RuntimeError("retry loop exited unexpectedly")


async def _retry_async[T](
    operation: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    delay_sec: float = 1.0,
) -> T:
    for attempt in range(attempts):
        try:
            return await operation()
        except Exception:
            if attempt == attempts - 1:
                raise
            await asyncio.sleep(delay_sec)
    raise RuntimeError("retry loop exited unexpectedly")


def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        run_scheduled_backup,
        trigger="cron",
        hour=3,
        minute=0,
        id="daily_backup",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        run_hive_temperature_poll,
        trigger="interval",
        minutes=15,
        id="hive_temperature_poll",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        run_morning_weather_sync,
        trigger="cron",
        hour=6,
        minute=30,
        timezone=settings.weather_timezone,
        id="morning_weather_sync",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        run_garmin_activity_poll,
        trigger="interval",
        hours=1,
        id="garmin_activity_poll",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        next_run_time=datetime.now(UTC) + timedelta(minutes=5),
    )
    scheduler.add_job(
        run_workout_autopush,
        trigger="cron",
        hour="7,13,19",
        minute=0,
        timezone=settings.weather_timezone,
        id="workout_autopush",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        run_evening_sleep_nudge,
        trigger="cron",
        hour=20,
        minute=0,
        timezone=settings.weather_timezone,
        id="evening_sleep_nudge",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        run_evening_monitoring_alerts,
        trigger="cron",
        hour="19-22",
        minute="0,15,30,45",
        timezone=settings.weather_timezone,
        id="evening_monitoring_alerts",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    return scheduler
