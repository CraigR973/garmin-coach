"""Background scheduler for time-driven match transitions.

Runs a minute-by-minute job that locks any match whose kickoff has arrived,
and writes a corresponding audit_log row for each lock transition.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from apscheduler.schedulers.asyncio import (  # type: ignore[import-untyped,unused-ignore]
    AsyncIOScheduler,
)
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.config import settings
from src.database import AsyncSessionLocal
from src.models.match import Match, MatchStatus
from src.models.notification import ActionType, ActorType, AuditLog
from src.models.team import TournamentStage
from src.services.backup import create_backup
from src.services.notification_triggers import (
    MatchUpdate,
    check_deadline_warnings,
    check_evening_kickoff_warnings,
    check_pick_confirmations,
    notify_backup_failed,
    notify_match_locked,
    notify_tournament_started,
    send_daily_prediction_digest,
)
from src.services.result_sync import sync_results

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def lock_due_matches(
    session_factory: async_sessionmaker[AsyncSession] = AsyncSessionLocal,
    now: datetime | None = None,
) -> int:
    """Transition any scheduled match whose kickoff has passed to ``locked``.

    Returns the number of matches that were locked. Each transition writes
    an ``audit_log`` row with action_type=predictions_locked, actor_type=system.
    """
    current = now if now is not None else _utc_now()
    locked_count = 0

    async with session_factory() as session:
        result = await session.execute(
            select(Match).where(
                Match.status == MatchStatus.scheduled,
                Match.kickoff_utc <= current,
                Match.deleted_at.is_(None),
            )
        )
        matches = list(result.scalars().all())

        locked_updates: list[MatchUpdate] = []
        for match in matches:
            match.status = MatchStatus.locked
            match.locked_at = current
            session.add(
                AuditLog(
                    actor_id=None,
                    actor_type=ActorType.system,
                    action_type=ActionType.predictions_locked,
                    target_table="matches",
                    target_id=match.id,
                    changes={"locked_at": current.isoformat()},
                )
            )
            locked_updates.append(
                MatchUpdate(
                    event_type="match_locked",
                    match_id=match.id,
                    stage=match.stage.value,
                    home_team_id=match.home_team_id,
                    away_team_id=match.away_team_id,
                    home_placeholder=match.home_team_placeholder,
                    away_placeholder=match.away_team_placeholder,
                )
            )
            locked_count += 1

        if locked_count:
            await session.commit()
            log.info("matches locked", count=locked_count)
            for upd in locked_updates:
                try:
                    await notify_match_locked(session, upd)
                except Exception:
                    log.exception("notify_match_locked failed", match_id=str(upd.match_id))

            # Fire the tournament-started notification exactly once: when the
            # opening group match (earliest kickoff) is among the just-locked set.
            try:
                opening_row = await session.execute(
                    select(Match.id)
                    .where(
                        Match.stage == TournamentStage.group,
                        Match.deleted_at.is_(None),
                    )
                    .order_by(Match.kickoff_utc.asc())
                    .limit(1)
                )
                opening_id = opening_row.scalar_one_or_none()
                locked_ids = {upd.match_id for upd in locked_updates}
                if opening_id is not None and opening_id in locked_ids:
                    await notify_tournament_started(session)
                    log.info("tournament started notification sent")
            except Exception:
                log.exception("notify_tournament_started failed")

            await session.commit()

    return locked_count


async def prune_leaderboard_snapshots(
    session_factory: async_sessionmaker[AsyncSession] = AsyncSessionLocal,
    keep_recent: int = 50,
) -> int:
    """Delete old leaderboard_snapshots, keeping the latest `keep_recent` per
    (league_id, player_id) plus one snapshot per calendar day.

    Without pruning, every result entry inserts one row per active member and
    the table grows without bound over a 104-match tournament.
    """
    async with session_factory() as session:
        result = await session.execute(
            text("""
                DELETE FROM leaderboard_snapshots
                WHERE id IN (
                    SELECT id FROM (
                        SELECT
                            id,
                            ROW_NUMBER() OVER (
                                PARTITION BY league_id, player_id
                                ORDER BY snapshot_at DESC
                            ) AS rn,
                            snapshot_at::date AS snap_date,
                            ROW_NUMBER() OVER (
                                PARTITION BY league_id, player_id, snapshot_at::date
                                ORDER BY snapshot_at DESC
                            ) AS daily_rn
                        FROM leaderboard_snapshots
                    ) ranked
                    WHERE rn > :keep_recent AND daily_rn > 1
                )
            """),
            {"keep_recent": keep_recent},
        )
        deleted: int = result.rowcount  # type: ignore[attr-defined]
        await session.commit()
    if deleted:
        log.info("pruned leaderboard_snapshots", deleted=deleted)
    return deleted


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
                    target_table=None,
                    target_id=None,
                    changes={"error": reason},
                )
            )
            try:
                await notify_backup_failed(session, reason)
            except Exception:
                log.exception("notify_backup_failed failed")
            await session.commit()


def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        lock_due_matches,
        trigger="interval",
        seconds=15,
        id="lock_due_matches",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        sync_results,
        trigger="interval",
        minutes=5,
        id="sync_results",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        check_deadline_warnings,
        kwargs={
            "session_factory": AsyncSessionLocal,
            "warning_minutes": 15,
            "unpredicted_only": True,
        },
        trigger="interval",
        minutes=1,
        id="deadline_warnings_15",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        check_evening_kickoff_warnings,
        kwargs={"session_factory": AsyncSessionLocal},
        trigger="interval",
        minutes=1,
        id="evening_kickoff_warnings",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        check_deadline_warnings,
        kwargs={"session_factory": AsyncSessionLocal, "warning_minutes": 60},
        trigger="interval",
        minutes=1,
        id="deadline_warnings_60",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        check_pick_confirmations,
        kwargs={"session_factory": AsyncSessionLocal},
        trigger="interval",
        minutes=1,
        id="pick_confirmations",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
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
        send_daily_prediction_digest,
        kwargs={"session_factory": AsyncSessionLocal},
        trigger="cron",
        hour=9,
        minute=0,
        id="daily_prediction_digest",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        prune_leaderboard_snapshots,
        trigger="cron",
        hour=4,
        minute=0,
        id="prune_leaderboard_snapshots",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    return scheduler
