"""Watch the job ledger from outside the scheduler that writes it (Batch 242.5).

Every other job in this app rides the api container's in-process APScheduler and
records its outcome in ``job_runs``. That ledger answers "did this run fail?" — it
cannot answer "did this run at all?", because the thing that would write the row
is the thing that stopped. DS237-01 found two jobs (``longitudinal-analysis`` on
2026-08-25, ``morning-sync`` on 2026-08-28) that had simply failed, visible only
because a review went looking; a scheduler that dies outright is quieter still.

So this check is **deliberately not registered in ``create_scheduler()``**. It is
exposed through ``run_scheduled.py`` for an external runner — a Railway cron
service, a manual ``railway run``, anything with its own clock — and
``test_job_ledger_freshness`` pins that separation, because registering it
in-process would silently turn a watchdog into another thing the same failure
takes down.

It reports by ``log.error``, which is what makes it useful: ``SENTRY_DSN_BACKEND``
captures ERROR-level records, so a stale job becomes an operator signal without a
second delivery mechanism. It also returns ``degraded``, so ``run_scheduled.py``
exits non-zero and the external scheduler can alert from process state too.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import AsyncSessionLocal
from src.models.operations import JobRun
from src.services.job_runs import JobResult

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


# How old the newest run of each job may be before it is called stale.
#
# These are *tolerances*, not schedules: each is comfortably longer than the
# job's own cadence so that one missed fire is not an alert, while a job that
# has genuinely stopped is caught within roughly one further period. The
# cadences themselves live in ``create_scheduler`` and
# ``docs/runbooks/scheduled-jobs-cron.md``.
MAX_AGE: dict[str, timedelta] = {
    # Every 10–15 minutes.
    "hive-poll": timedelta(hours=2),
    "wake-check": timedelta(hours=2),
    "fan-control": timedelta(hours=2),
    "egress-budget": timedelta(hours=2),
    # Hourly.
    "activity-poll": timedelta(hours=4),
    # Daily, at a fixed local hour.
    "backup": timedelta(days=2),
    "baseline-refresh": timedelta(days=2),
    "morning-sync": timedelta(days=2),
    "post-workout-backstop": timedelta(days=2),
    "state-change": timedelta(days=2),
    "evening-nudge": timedelta(days=2),
    "evening-alerts": timedelta(days=2),
    "longitudinal-analysis": timedelta(days=2),
    # Several times a day.
    "autopush": timedelta(days=1),
    # Weekly, Sunday 18:00 local.
    "weekly-review": timedelta(days=9),
}


@dataclass(frozen=True, slots=True)
class JobFreshness:
    job_name: str
    last_run_utc: datetime | None
    age: timedelta | None
    max_age: timedelta

    @property
    def is_stale(self) -> bool:
        # Never having run at all is the loudest case, not an exempt one: it is
        # what a job registered but never wired looks like (Batch 228), and what
        # `backup-drill` looked like for the whole of its existence (DS237-04).
        return self.age is None or self.age > self.max_age


@dataclass(frozen=True, slots=True)
class FreshnessReport:
    checked: tuple[JobFreshness, ...]

    @property
    def stale(self) -> tuple[JobFreshness, ...]:
        return tuple(entry for entry in self.checked if entry.is_stale)


async def collect_freshness(
    session: AsyncSession, *, now_utc: datetime | None = None
) -> FreshnessReport:
    """Read the newest ``job_runs`` row per job and age it against ``MAX_AGE``."""

    now = (now_utc or datetime.now(UTC)).replace(tzinfo=None)
    # One grouped read rather than one query per job — this runs on a schedule
    # against a database already at ~90% of its cap (DS237-02), so it should not
    # add fifteen round trips to do it.
    rows = (
        await session.execute(
            select(JobRun.job_name, func.max(JobRun.started_at_utc)).group_by(JobRun.job_name)
        )
    ).all()
    latest: dict[str, datetime] = {name: started for name, started in rows if started is not None}

    checked: list[JobFreshness] = []
    for job_name, max_age in sorted(MAX_AGE.items()):
        last = latest.get(job_name)
        checked.append(
            JobFreshness(
                job_name=job_name,
                last_run_utc=last,
                age=None if last is None else now - last,
                max_age=max_age,
            )
        )
    return FreshnessReport(checked=tuple(checked))


async def run_ledger_freshness_check(*, now_utc: datetime | None = None) -> JobResult:
    """Report any job whose newest ledger row is older than its tolerance.

    Never registered in the in-process scheduler — see the module docstring.
    """

    async with AsyncSessionLocal() as session:
        report = await collect_freshness(session, now_utc=now_utc)

    for entry in report.stale:
        # log.error, not log.warning: this is the line Sentry turns into an
        # operator signal once SENTRY_DSN_BACKEND is set (Batch 242.1).
        log.error(
            "scheduled job ledger is stale",
            job_name=entry.job_name,
            last_run_utc=(
                entry.last_run_utc.isoformat() if entry.last_run_utc is not None else None
            ),
            age_hours=(None if entry.age is None else round(entry.age.total_seconds() / 3600.0, 2)),
            max_age_hours=round(entry.max_age.total_seconds() / 3600.0, 2),
            reason="never_run" if entry.last_run_utc is None else "overdue",
            alert_route="sentry",
        )

    counters = {"checked": len(report.checked), "stale": len(report.stale)}
    if report.stale:
        return JobResult.degraded("stale_jobs", **counters)
    log.info("scheduled job ledger is fresh", **counters)
    return JobResult.succeeded(**counters)
