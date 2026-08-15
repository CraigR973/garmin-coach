from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

import structlog

from src.database import AsyncSessionLocal
from src.models.operations import JobRun

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


class JobStatus(StrEnum):
    succeeded = "succeeded"
    skipped = "skipped"
    degraded = "degraded"
    failed = "failed"


@dataclass(frozen=True, slots=True)
class JobResult:
    """Typed result shared by APScheduler and the run-to-completion runner."""

    status: JobStatus
    reason: str | None = None
    counters: Mapping[str, int] = field(default_factory=dict)

    @property
    def exit_code(self) -> int:
        """External schedulers must see degraded and failed runs as failures."""

        return 0 if self.status in {JobStatus.succeeded, JobStatus.skipped} else 1

    @classmethod
    def succeeded(cls, **counters: int) -> JobResult:
        return cls(JobStatus.succeeded, counters=counters)

    @classmethod
    def skipped(cls, reason: str, **counters: int) -> JobResult:
        return cls(JobStatus.skipped, reason=reason, counters=counters)

    @classmethod
    def degraded(cls, reason: str, **counters: int) -> JobResult:
        return cls(JobStatus.degraded, reason=reason, counters=counters)

    @classmethod
    def failed(cls, reason: str, **counters: int) -> JobResult:
        return cls(JobStatus.failed, reason=reason, counters=counters)


JobOperation = Callable[[], Awaitable[JobResult]]


# These are evidence buckets, not dispatch rules: every real invocation gets a
# row whose window answers "which expected cadence did this run belong to?".
_WINDOW_MINUTES: dict[str, int] = {
    "hive-poll": 15,
    "wake-check": 15,
    "evening-alerts": 15,
    "fan-control": 15,
    "activity-poll": 60,
    "autopush": 360,
}

_LOCAL_DAILY_JOBS = {
    "morning-sync",
    "post-workout-backstop",
    "state-change",
    "evening-nudge",
}
_LONDON = ZoneInfo("Europe/London")


def scheduled_window(job_name: str, started_at_utc: datetime) -> tuple[datetime, datetime]:
    """Return the UTC cadence bucket containing ``started_at_utc``."""

    moment = (
        started_at_utc.replace(tzinfo=UTC)
        if started_at_utc.tzinfo is None
        else started_at_utc.astimezone(UTC)
    )
    if job_name == "backup":
        start_utc = moment.replace(hour=0, minute=0, second=0, microsecond=0)
        end_utc = start_utc + timedelta(days=1)
        return start_utc.replace(tzinfo=None), end_utc.replace(tzinfo=None)
    if job_name in _LOCAL_DAILY_JOBS or job_name == "weekly-review":
        local = moment.astimezone(_LONDON)
        start_date = local.date()
        if job_name == "weekly-review":
            start_date -= timedelta(days=local.weekday())
        start_local = datetime.combine(start_date, datetime.min.time(), tzinfo=_LONDON)
        days = 7 if job_name == "weekly-review" else 1
        end_local = datetime.combine(
            start_date + timedelta(days=days), datetime.min.time(), tzinfo=_LONDON
        )
        return (
            start_local.astimezone(UTC).replace(tzinfo=None),
            end_local.astimezone(UTC).replace(tzinfo=None),
        )
    minutes = _WINDOW_MINUTES.get(job_name, 60)
    seconds = minutes * 60
    start_epoch = int(moment.timestamp()) // seconds * seconds
    start = datetime.fromtimestamp(start_epoch, tz=UTC).replace(tzinfo=None)
    return start, start + timedelta(minutes=minutes)


async def run_tracked_job(
    job_name: str,
    operation: JobOperation,
    *,
    started_at_utc: datetime | None = None,
) -> JobResult:
    """Run a job and persist its outcome in an independent transaction.

    The separate session is intentional: a poisoned or rolled-back job session
    must not erase the evidence that the invocation failed.
    """

    started = started_at_utc or datetime.now(UTC).replace(tzinfo=None)
    if started.tzinfo is not None:
        started = started.astimezone(UTC).replace(tzinfo=None)
    try:
        result = await operation()
    except Exception:
        log.exception("scheduled job escaped its result boundary", job_name=job_name)
        result = JobResult.failed("unhandled_exception")
    finished = datetime.now(UTC).replace(tzinfo=None)
    if finished < started:
        finished = started
    window_start, window_end = scheduled_window(job_name, started)

    row = JobRun(
        job_name=job_name,
        scheduled_window_start_utc=window_start,
        scheduled_window_end_utc=window_end,
        started_at_utc=started,
        finished_at_utc=finished,
        status=result.status.value,
        reason=result.reason,
        counters=dict(result.counters),
    )
    try:
        async with AsyncSessionLocal() as session:
            session.add(row)
            await session.commit()
    except Exception:
        log.exception(
            "scheduled job outcome persistence failed",
            job_name=job_name,
            job_status=result.status.value,
        )
        counters = dict(result.counters)
        counters["outcome_persistence_failed"] = 1
        return JobResult.failed("job_run_persistence_failed", **counters)

    log.info(
        "scheduled job outcome recorded",
        job_name=job_name,
        status=result.status.value,
        reason=result.reason,
        counters=dict(result.counters),
        window_start_utc=window_start.isoformat(),
        window_end_utc=window_end.isoformat(),
    )
    return result
