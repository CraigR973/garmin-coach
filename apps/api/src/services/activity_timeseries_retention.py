"""A rolling window for the table that is 82% of the database (Batch 247.2).

`activity_timeseries` holds one row per per-second sample of every ride and
walk. Measured 2026-09-02: **670,192 rows across 838 activities, 371 MB — 82% of
a 452 MB database against a 500 MB cap**, growing ~1.45 MB/day. Nothing bounded
it, and this app has already been to the harder version of that wall (DECISIONS
#93: the 2026-06-28 backfill filled the physical disk, at which point
`VACUUM FULL` could not run because there was no room to write the compacted
copy).

**What retention costs, precisely.** The prose stays: `analyses` keeps every
post-workout and post-walk read permanently. What goes is the per-second samples,
so regenerating a read for a ride older than the window, re-grading its
intervals, or any future per-second feature over old rides becomes impossible.
The table is also **excluded from every backup by design** (`services/backup.py`
`EXCLUDED_TABLE_DATA`), so this data is already unprotected against disk loss
regardless of retention — deleting it removes something that was never
recoverable anyway.

**Why the window is keyed on the activity, not on the sample.** The two readers —
`post_workout_analysis._timeseries` and `post_walk_analysis._timeseries` — both
select `where activity_id == ...` and nothing reads across a window, so an
activity is the natural unit. Keying on `timestamp_utc` would, for an activity
spanning the boundary, delete the early samples and keep the late ones: a
half-readable ride that produces a *wrong* read rather than an absent one. On
today's data the two keyings happen to agree exactly (466,449 rows either way,
zero null timestamps, zero orphans), so this costs nothing and removes a failure
mode.

**The reclaim trap, and it corrects the ledger row.** A plain `DELETE` returns
space to the free-space map; it does **not** shrink the files, so
`pg_database_size` barely moves. It converts unbounded growth into a bounded
steady state — which is the actual goal — but it does not itself take the
database to ~41% of cap. Doing that needs `VACUUM FULL`, `pg_repack` or
dump/truncate/reload, and `VACUUM FULL` needs the *live* data's size free before
it starts. That is the 2026-06-28 failure exactly, so the reclaim step is a
separate, deliberate operation and this job does not attempt it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import structlog
from sqlalchemy import Select, delete, func, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import Activity, ActivityTimeSeries

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

# Decided 2026-09-01. Long enough that a post-workout read is regenerable for
# every ride still in living memory; short enough to turn 14 months of unbounded
# growth into a constant.
RETENTION_DAYS = 90

# One transaction deleting ~466,000 rows would hold locks and WAL for the length
# of the whole operation, on a database already near its cap. Batched so each
# commit is bounded and the job can be interrupted without losing its progress.
DELETE_BATCH_ROWS = 20_000


@dataclass(frozen=True, slots=True)
class RetentionResult:
    cutoff_utc: datetime
    expired_rows: int
    expired_activities: int
    deleted_rows: int
    dry_run: bool


def retention_cutoff(now_utc: datetime | None = None) -> datetime:
    now = (now_utc or datetime.now(UTC)).replace(tzinfo=None)
    return now - timedelta(days=RETENTION_DAYS)


def _expired_activity_ids(cutoff: datetime) -> Select[tuple[uuid.UUID]]:
    return select(Activity.id).where(Activity.start_utc < cutoff)


async def measure_expired(
    session: AsyncSession, *, now_utc: datetime | None = None
) -> tuple[datetime, int, int]:
    """Count what a purge would remove, without removing it."""

    cutoff = retention_cutoff(now_utc)
    rows = int(
        await session.scalar(
            select(func.count())
            .select_from(ActivityTimeSeries)
            .where(ActivityTimeSeries.activity_id.in_(_expired_activity_ids(cutoff)))
        )
        or 0
    )
    activities = int(
        await session.scalar(
            select(func.count(func.distinct(ActivityTimeSeries.activity_id))).where(
                ActivityTimeSeries.activity_id.in_(_expired_activity_ids(cutoff))
            )
        )
        or 0
    )
    return cutoff, rows, activities


async def purge_expired_timeseries(
    session: AsyncSession,
    *,
    now_utc: datetime | None = None,
    dry_run: bool = True,
) -> RetentionResult:
    """Delete samples for activities older than the window. Irreversible.

    ``dry_run`` defaults to **True** and is the shipped production setting until
    it is deliberately changed. The first real execution is a decision with a row
    count attached, not something a deploy should perform on its own: this table
    is excluded from every backup, so there is no undo.
    """

    cutoff, expired_rows, expired_activities = await measure_expired(session, now_utc=now_utc)

    if dry_run:
        log.info(
            "activity timeseries retention dry run",
            cutoff_utc=cutoff.isoformat(),
            retention_days=RETENTION_DAYS,
            would_delete_rows=expired_rows,
            would_delete_activities=expired_activities,
            enabled=False,
        )
        return RetentionResult(
            cutoff_utc=cutoff,
            expired_rows=expired_rows,
            expired_activities=expired_activities,
            deleted_rows=0,
            dry_run=True,
        )

    deleted = 0
    while True:
        batch = (
            select(ActivityTimeSeries.id)
            .where(ActivityTimeSeries.activity_id.in_(_expired_activity_ids(cutoff)))
            .limit(DELETE_BATCH_ROWS)
        )
        result = await session.execute(
            delete(ActivityTimeSeries).where(ActivityTimeSeries.id.in_(batch))
        )
        removed = int(cast("CursorResult[Any]", result).rowcount or 0)
        await session.commit()
        deleted += removed
        if removed == 0:
            break

    log.warning(
        "activity timeseries retention purged",
        cutoff_utc=cutoff.isoformat(),
        retention_days=RETENTION_DAYS,
        deleted_rows=deleted,
        deleted_activities=expired_activities,
        # Said on the line itself so nobody reads a purge as a reclaim: DELETE
        # returns space to the free-space map and does not shrink the files.
        note="space returns to the free-space map; pg_database_size needs a "
        "separate VACUUM FULL / pg_repack / dump-truncate-reload to fall",
    )
    return RetentionResult(
        cutoff_utc=cutoff,
        expired_rows=expired_rows,
        expired_activities=expired_activities,
        deleted_rows=deleted,
        dry_run=False,
    )
