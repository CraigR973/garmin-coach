"""Background scheduler — APScheduler harness for garmin-coach.

Current jobs:
  - daily_backup: runs at 03:00 UTC
  - hive_temperature_poll: polls Hive indoor temperature every 15 minutes
  - morning_weather_sync: pulls Kilmarnock weather at 06:30 Europe/London
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import structlog
from apscheduler.schedulers.asyncio import (  # type: ignore[import-untyped,unused-ignore]
    AsyncIOScheduler,
)
from sqlalchemy import select

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
            synced = 0
            for profile in profiles:
                result = await service.sync_hive_temperatures(
                    profile.id, payloads, commit=False
                )
                synced += result.temperature_readings_synced
            await session.commit()
        log.info("hive temperature poll complete", profiles=len(profiles), readings=synced)
    except Exception:
        log.exception("hive temperature poll failed")


async def run_morning_weather_sync() -> None:
    """Sync Open-Meteo daily weather without triggering analysis yet."""
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
        log.info("morning weather sync complete", profiles=len(profiles), days=synced)
    except Exception:
        log.exception("morning weather sync failed")


async def _retry_sync[T](
    operation: Callable[[], T],
    *,
    attempts: int = 3,
    delay_sec: float = 1.0,
) -> T:
    for attempt in range(attempts):
        try:
            return operation()
        except Exception:
            if attempt == attempts - 1:
                raise
            await asyncio.sleep(delay_sec)
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
    return scheduler
