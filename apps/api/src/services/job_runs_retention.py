"""A rolling window on the job log (Batch 387).

`job_runs` holds one row of operator evidence for every scheduled run, about 450
a day, and nothing bounded it: 39,636 rows since 15 Aug, 15 MB with its indexes,
when measured on 12 Nov 2026. Its readers never look far back. The Zwift rail
reads its own runs from the last 48 hours (`zwift_rail.recent_readings`), and the
freshness watchdog takes each job's newest run (`job_ledger_freshness`). So the
window keeps 30 days, and always each job's newest run whatever its age: a job
that has stopped running still reads "last ran N days ago", never "never ran".

Everything removed is still in the nightly archives (seven kept) and the weekly
full ones (four kept), so it stays recoverable for about a month.

As with the ride samples (`activity_timeseries_retention`), a `DELETE` returns
space to the free-space map and does not shrink the files. The one-off rewrite
that took the table down is recorded in DECISIONS #504, and it is not this job.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import structlog
from sqlalchemy import Select, delete, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.operations import JobRun

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

RETENTION_DAYS = 30

# The first pass removes ~26,000 rows; later ones a day's worth (~450). Bounded
# commits keep each transaction small on a database whose disk budget is thin.
DELETE_BATCH_ROWS = 5_000


@dataclass(frozen=True, slots=True)
class JobRunsRetentionResult:
    cutoff_utc: datetime
    deleted_rows: int


def retention_cutoff(now_utc: datetime | None = None) -> datetime:
    now = (now_utc or datetime.now(UTC)).replace(tzinfo=None)
    return now - timedelta(days=RETENTION_DAYS)


def _newest_run_per_job() -> Select[tuple[Any]]:
    return (
        select(JobRun.id)
        .distinct(JobRun.job_name)
        .order_by(JobRun.job_name, JobRun.started_at_utc.desc(), JobRun.id.desc())
    )


def _expired_batch(cutoff: datetime) -> Select[tuple[Any]]:
    return (
        select(JobRun.id)
        .where(JobRun.started_at_utc < cutoff, JobRun.id.not_in(_newest_run_per_job()))
        .limit(DELETE_BATCH_ROWS)
    )


async def purge_old_job_runs(
    session: AsyncSession, *, now_utc: datetime | None = None
) -> JobRunsRetentionResult:
    """Delete runs older than the window, keeping each job's newest. Irreversible
    here; recoverable from the archives for about a month."""

    cutoff = retention_cutoff(now_utc)
    deleted = 0
    while True:
        result = await session.execute(delete(JobRun).where(JobRun.id.in_(_expired_batch(cutoff))))
        removed = int(cast("CursorResult[Any]", result).rowcount or 0)
        await session.commit()
        deleted += removed
        if removed < DELETE_BATCH_ROWS:
            break

    log.info(
        "job runs retention purged",
        cutoff_utc=cutoff.isoformat(),
        retention_days=RETENTION_DAYS,
        deleted_rows=deleted,
    )
    return JobRunsRetentionResult(cutoff_utc=cutoff, deleted_rows=deleted)
