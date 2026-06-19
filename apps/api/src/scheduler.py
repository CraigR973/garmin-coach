"""Background scheduler — APScheduler harness for garmin-coach.

Current jobs:
  - daily_backup: runs at 03:00 UTC

# Phase 1: add garmin sync, hive temp poll, morning analysis, activity poll jobs here
"""

from __future__ import annotations

import structlog
from apscheduler.schedulers.asyncio import (  # type: ignore[import-untyped,unused-ignore]
    AsyncIOScheduler,
)

from src.config import settings
from src.database import AsyncSessionLocal
from src.models.notification import ActionType, ActorType, AuditLog
from src.services.backup import create_backup

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
    return scheduler
