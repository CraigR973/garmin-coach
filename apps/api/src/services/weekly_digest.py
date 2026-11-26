"""The weekly ops digest to Craig (Batch 391.5, takes 337.10; Decision #513).

One email every Sunday evening, through Batch 378's route: what the daily reviewer
found and would have done, the week's alerts and Mark's points by count, every job's
runs and failures, the backup and its offsite proof, the database against the free
plan's limits, and how long until intervals.icu would pause the Zwift rail. It says
"all clear" when nothing needs looking at, so a missing digest is itself a signal.

Codes, counts and the reviewer's own one-line summaries only: never Mark's words.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.operations import ImprovementItem, JobRun

_LONDON: Final = ZoneInfo("Europe/London")
STORAGE_BUDGET_MB: Final = 500
EGRESS_BUDGET_GB: Final = 5
INTERVALS_DORMANT_AFTER_DAYS: Final = 90
JOB_REPORT_URL: Final = "https://api-production-e2bc7.up.railway.app/api/v1/health/jobs"
LANE_WORDS: Final = {
    "fix_alone": "fix alone",
    "mark": "Mark's yes",
    "evidence": "evidence",
    "craig": "you",
    None: "no lane yet",
}


@dataclass
class DigestData:
    week_start: datetime
    week_end: datetime
    findings: list[dict[str, Any]] = field(default_factory=list)
    alerts: Counter[str] = field(default_factory=Counter)
    mark_points: Counter[str] = field(default_factory=Counter)
    runs: Counter[str] = field(default_factory=Counter)
    unhealthy: dict[str, Counter[str]] = field(default_factory=dict)
    open_items: int = 0
    latest: dict[str, JobRun] = field(default_factory=dict)


async def collect(session: AsyncSession, *, now: datetime | None = None) -> DigestData:
    """The seven days to ``now`` (UTC, naive)."""

    end = now or datetime.now(UTC).replace(tzinfo=None)
    start = end - timedelta(days=7)
    data = DigestData(week_start=start, week_end=end)

    items = await session.scalars(
        select(ImprovementItem).where(ImprovementItem.last_seen_utc >= start)
    )
    for item in items:
        if item.source in ("review", "suggestion") and item.first_seen_utc >= start:
            data.findings.append({"summary": item.summary, "lane": item.lane, "state": item.state})
        elif item.source in ("alert", "job_outcome"):
            data.alerts[item.kind] += item.occurrences
        elif item.source in ("correction", "pass_on", "dispute") and item.first_seen_utc >= start:
            data.mark_points[item.source] += 1
    data.open_items = len(
        list(
            await session.scalars(
                select(ImprovementItem.id).where(ImprovementItem.closed_utc.is_(None))
            )
        )
    )

    runs = await session.scalars(select(JobRun).where(JobRun.started_at_utc >= start))
    for run in runs:
        data.runs[run.job_name] += 1
        if run.status in ("degraded", "failed"):
            data.unhealthy.setdefault(run.job_name, Counter())[run.status] += 1
    for job in ("backup", "backup-drill", "egress-budget", "intervals-rail"):
        latest = await session.scalar(
            select(JobRun)
            .where(JobRun.job_name == job)
            .order_by(JobRun.started_at_utc.desc())
            .limit(1)
        )
        if latest is not None:
            data.latest[job] = latest
    return data


def _local(moment: datetime) -> datetime:
    return moment.replace(tzinfo=UTC).astimezone(_LONDON)


def _day(moment: datetime) -> str:
    return f"{_local(moment).day} {_local(moment):%b}"


def _when(moment: datetime) -> str:
    return f"{_day(moment)}, {_local(moment):%H:%M}"


def _count(counters: dict[str, Any], key: str) -> int | None:
    value = counters.get(key)
    return int(value) if isinstance(value, int | float) else None


def compose(data: DigestData) -> tuple[str, str]:
    """The subject and body. Things to look at: failures, new alerts and findings, backups."""

    attention: list[str] = []
    lines: list[str] = [
        f"Week: {_day(data.week_start)} to {_day(data.week_end)} (London)",
        "",
        "THE DAILY REVIEW (shadow mode: it changes nothing)",
    ]
    if data.findings:
        lanes = Counter(LANE_WORDS.get(f["lane"], str(f["lane"])) for f in data.findings)
        lines.append(
            f"- {len(data.findings)} findings: "
            + ", ".join(
                f"{count} {lane}"
                for lane, count in sorted(lanes.items(), key=lambda kv: (-kv[1], kv[0].lower()))
            )
        )
        for finding in data.findings[:12]:
            lines.append(
                f"  • {finding['summary']} ({LANE_WORDS.get(finding['lane'], finding['lane'])}, "
                f"{finding['state']})"
            )
        if len(data.findings) > 12:
            lines.append(f"  • and {len(data.findings) - 12} more")
        attention.append("findings")
    else:
        lines.append("- No findings this week.")
    lines.append(f"- Open items in the queue: {data.open_items}")

    lines += ["", "ALERTS"]
    if data.alerts:
        for kind, count in sorted(data.alerts.items()):
            lines.append(f"- {kind}: {count}")
        attention.append("alerts")
    else:
        lines.append("- None.")

    points = data.mark_points
    lines += [
        "",
        "MARK'S POINTS",
        f"- Written corrections: {points['correction']}; pass-ons: {points['pass_on']}; "
        f"disputes: {points['dispute']}",
    ]

    lines += ["", "JOBS", f"- {sum(data.runs.values())} runs across {len(data.runs)} jobs."]
    if data.unhealthy:
        for job, statuses in sorted(data.unhealthy.items()):
            detail = ", ".join(f"{count} {status}" for status, count in sorted(statuses.items()))
            lines.append(f"- {job}: {detail} of {data.runs[job]}")
        attention.append("jobs")
    else:
        lines.append("- None failed or degraded.")

    lines += ["", "BACKUPS"]
    backup = data.latest.get("backup")
    if backup is None:
        lines.append("- Nightly backup: no run recorded.")
        attention.append("backup")
    else:
        lines.append(f"- Nightly backup: {backup.status} at {_when(backup.started_at_utc)}.")
        if backup.status != "succeeded":
            attention.append("backup")
    drill = data.latest.get("backup-drill")
    proof_age = _count(drill.counters, "proof_age_seconds") if drill else None
    if drill is None or drill.status != "succeeded" or proof_age is None:
        lines.append("- Offsite restore proof: not confirmed this week.")
        attention.append("restore proof")
    else:
        lines.append(f"- Offsite restore proof: {proof_age // 86400} days old (limit 8).")

    lines += ["", "DATABASE"]
    egress = data.latest.get("egress-budget")
    if egress is not None:
        size = _count(egress.counters, "all_databases_bytes")
        month = _count(egress.counters, "egress_bytes_month")
        if size is not None:
            lines.append(f"- Storage: {size / 1e6:.0f} MB of {STORAGE_BUDGET_MB} MB.")
        if month is not None:
            lines.append(f"- Egress this month: {month / 1e9:.2f} GB of {EGRESS_BUDGET_GB} GB.")
        if (_count(egress.counters, "storage_stage_ordinal") or 0) or (
            _count(egress.counters, "alert_stage_ordinal") or 0
        ):
            attention.append("database limits")
    else:
        lines.append("- No measurement recorded.")

    rail = data.latest.get("intervals-rail")
    login = _count(rail.counters, "last_login_epoch") if rail else None
    lines += ["", "ZWIFT DELIVERY"]
    if login:
        days_since = (
            data.week_end.replace(tzinfo=UTC) - datetime.fromtimestamp(login, tz=UTC)
        ).days
        left = INTERVALS_DORMANT_AFTER_DAYS - days_since
        lines.append(
            f"- Mark last signed in to intervals.icu {days_since} days ago; "
            f"its free account pauses in {left} days unless he signs in."
        )
        if left <= 14:
            attention.append("intervals.icu")
    else:
        lines.append("- No intervals.icu reading this week.")

    lines += [
        "",
        "Not covered yet: red CI runs that deployed.",
        f"Job report: {JOB_REPORT_URL}",
    ]
    if attention:
        subject = f"[Garmin Coach] Weekly digest: {len(attention)} things to look at"
    else:
        subject = "[Garmin Coach] Weekly digest: all clear"
    return subject, "\n".join(lines)
