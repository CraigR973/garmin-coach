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

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import AsyncSessionLocal
from src.models.coaching import BriefGenerationStatus
from src.models.operations import JobRun
from src.models.profile import Profile
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
    "trend-narratives": timedelta(days=2),
    # Batch 346, 01:30 London; a night without chat still records a skipped run.
    "coach-memory": timedelta(days=2),
    # Batch 335, 03:15 London.
    "live-ride-check": timedelta(days=2),
    # Several times a day.
    "autopush": timedelta(days=1),
    # Batch 326: the day reads its newest reading, so a stopped check is a Home that
    # says "can't check" after 24 hours; this catches the job itself stopping.
    "intervals-rail": timedelta(days=1),
    # Weekly, Sunday 18:00 local.
    "weekly-review": timedelta(days=9),
    # Batch 371: daily evidence poll; actual offsite success has an 8-day check below.
    "backup-drill": timedelta(days=2),
    # Batch 247.2, daily at 03:40 UTC. Watched from the first deploy even while
    # it only measures — a retention job that silently stopped is how a bounded
    # table becomes an unbounded one again.
    "timeseries-retention": timedelta(days=2),
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


# -- Batch 365.1 (DS357-02): the watchdog's view, read from outside the process ------------

#: Jobs that run every hour or more often: one failed run is a blip, two in a row are an
#: outage. Every other job's newest failed run is one.
FREQUENT_JOBS: frozenset[str] = frozenset(
    {"hive-poll", "wake-check", "fan-control", "egress-budget", "activity-poll", "intervals-rail"}
)
#: A failed brief for these reasons is not a fault: his watch has not synced yet. A
#: refused provider (``inputs_provider``) has its own problem, ``garmin_refused``.
_BRIEF_REASONS_NOT_ALERTED: frozenset[str] = frozenset({"inputs", "inputs_provider"})


@dataclass(frozen=True, slots=True)
class WatchdogReport:
    """What the external watchdog reads: coarse problem codes, no personal data."""

    problems: tuple[str, ...]

    @property
    def status(self) -> str:
        return "alert" if self.problems else "ok"


def watchdog_problems(
    *,
    freshness: FreshnessReport,
    recent_runs: Mapping[str, Sequence[tuple[str, str | None]]],
    brief_failures: Sequence[str | None],
) -> tuple[str, ...]:
    """The watchdog's rule, pure (Batch 365.1).

    ``recent_runs`` is each job's two newest runs as (status, reason), newest first;
    ``brief_failures`` the reasons of today's failed briefs.
    """

    problems = [f"stale:{entry.job_name}" for entry in freshness.stale]
    for job_name, runs in sorted(recent_runs.items()):
        if not runs:
            continue
        needed = 2 if job_name in FREQUENT_JOBS else 1
        newest = list(runs[:needed])
        if len(newest) == needed and all(status == "failed" for status, _ in newest):
            problems.append(f"failing:{job_name}")
    newest_reason = {name: runs[0][1] for name, runs in recent_runs.items() if runs}
    if newest_reason.get("activity-poll") == "garmin_auth_refused":
        problems.append("garmin_refused")
    if newest_reason.get("hive-poll") == "hive_reauth_required":
        problems.append("hive_refused")
    for reason in brief_failures:
        if reason not in _BRIEF_REASONS_NOT_ALERTED:
            problems.append(f"brief_failed:{reason or 'unknown'}")
    return tuple(dict.fromkeys(problems))


async def collect_watchdog_report(
    session: AsyncSession, *, now_utc: datetime | None = None
) -> WatchdogReport:
    """Three small reads: newest run per job, the two newest per job, today's briefs."""

    now = (now_utc or datetime.now(UTC)).replace(tzinfo=None)
    freshness = await collect_freshness(session, now_utc=now)
    ranked = (
        select(
            JobRun.job_name,
            JobRun.status,
            JobRun.reason,
            func.row_number()
            .over(partition_by=JobRun.job_name, order_by=JobRun.started_at_utc.desc())
            .label("rank"),
        )
        .where(JobRun.started_at_utc >= now - timedelta(days=10))
        .subquery()
    )
    recent: dict[str, list[tuple[str, str | None]]] = {}
    for job_name, status, reason, _rank in (
        await session.execute(
            select(ranked.c.job_name, ranked.c.status, ranked.c.reason, ranked.c.rank)
            .where(ranked.c.rank <= 2)
            .order_by(ranked.c.job_name, ranked.c.rank)
        )
    ).all():
        recent.setdefault(job_name, []).append((status, reason))
    profiles = (
        await session.execute(
            select(Profile.id, Profile.timezone).where(
                Profile.is_active.is_(True), Profile.deleted_at.is_(None)
            )
        )
    ).all()
    failures: list[str | None] = []
    for profile_id, timezone_name in profiles:
        today = _local_date(now, timezone_name)
        failed = (
            await session.execute(
                select(BriefGenerationStatus.reason).where(
                    BriefGenerationStatus.user_id == profile_id,
                    BriefGenerationStatus.subject_date == today,
                    BriefGenerationStatus.status == "failed",
                )
            )
        ).first()
        if failed is not None:
            failures.append(failed.reason)
    proof_run = (
        await session.execute(
            select(JobRun.counters)
            .where(JobRun.job_name == "backup-drill", JobRun.status == "succeeded")
            .order_by(JobRun.started_at_utc.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    proof_epoch = (proof_run or {}).get("proof_started_epoch")
    proof_missing = (
        not isinstance(proof_epoch, int)
        or not 0 <= now.replace(tzinfo=UTC).timestamp() - proof_epoch <= 8 * 86400
    )
    return WatchdogReport(
        problems=watchdog_problems(freshness=freshness, recent_runs=recent, brief_failures=failures)
        + (("backup_restore_unproved",) if proof_missing else ())
    )


def _local_date(now_utc: datetime, timezone_name: str | None) -> date:
    from zoneinfo import ZoneInfo

    try:
        zone = ZoneInfo(timezone_name or "Europe/London")
    except Exception:
        zone = ZoneInfo("Europe/London")
    return now_utc.replace(tzinfo=UTC).astimezone(zone).date()
