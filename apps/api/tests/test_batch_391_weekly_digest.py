"""Batch 391.5 (Decision #513): the weekly ops digest to Craig.

Every Sunday evening: what the daily reviewer found, the week's alerts and Mark's points
by count, every job's failures, the backup and its proof, the database against the free
plan, and the intervals.icu countdown. "All clear" when nothing needs looking at.
"""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from src import run_scheduled, scheduler
from src.config import settings
from src.models.operations import JobRun
from src.services import improvement_items, job_ledger_freshness, job_runs, weekly_digest
from src.services.weekly_digest import DigestData, compose

NOW = datetime(2026, 11, 29, 19, 0)


def _run(job: str, status: str = "succeeded", **counters: int) -> JobRun:
    return JobRun(
        job_name=job,
        scheduled_window_start_utc=NOW - timedelta(hours=2),
        scheduled_window_end_utc=NOW - timedelta(hours=1),
        started_at_utc=NOW - timedelta(hours=2),
        finished_at_utc=NOW - timedelta(hours=2),
        status=status,
        counters=counters,
    )


def _healthy() -> DigestData:
    data = DigestData(week_start=NOW - timedelta(days=7), week_end=NOW)
    data.runs = Counter({"hive-poll": 600, "backup": 7})
    data.latest = {
        "backup": _run("backup"),
        "backup-drill": _run("backup-drill", proof_age_seconds=2 * 86400),
        "egress-budget": _run(
            "egress-budget",
            all_databases_bytes=215_000_000,
            egress_bytes_month=1_640_000_000,
            storage_stage_ordinal=0,
            alert_stage_ordinal=0,
        ),
        "intervals-rail": _run(
            "intervals-rail",
            last_login_epoch=int((NOW - timedelta(days=30)).replace(tzinfo=UTC).timestamp()),
        ),
    }
    return data


def test_a_quiet_week_is_all_clear() -> None:
    subject, body = compose(_healthy())
    assert subject == "[Garmin Coach] Weekly digest: all clear"
    for line in (
        "Week: 22 Nov to 29 Nov (London)",
        "- No findings this week.",
        "- None failed or degraded.",
        "- Nightly backup: succeeded at 29 Nov, 17:00.",
        "- Offsite restore proof: 2 days old (limit 8).",
        "- Storage: 215 MB of 500 MB.",
        "- Egress this month: 1.64 GB of 5 GB.",
        "- Mark last signed in to intervals.icu 30 days ago; its free account pauses in 60 days",
        "Not covered yet: red CI runs that deployed.",
    ):
        assert line in body, line


def test_findings_failures_and_a_near_pause_are_things_to_look_at() -> None:
    data = _healthy()
    data.findings = [
        {
            "summary": "Two screens named different sleep scores",
            "lane": "fix_alone",
            "state": "triaged",
        },
        {"summary": "A post-ride read used a field name", "lane": "fix_alone", "state": "triaged"},
        {"summary": "Weekly sleep summary suggested", "lane": "mark", "state": "triaged"},
    ]
    data.alerts = Counter({"job_outcome": 2})
    data.unhealthy = {"morning-sync": Counter({"degraded": 1})}
    data.runs["morning-sync"] = 7
    data.latest["backup"] = _run("backup", status="failed")
    data.latest["intervals-rail"] = _run(
        "intervals-rail",
        last_login_epoch=int((NOW - timedelta(days=80)).replace(tzinfo=UTC).timestamp()),
    )
    subject, body = compose(data)
    assert subject == "[Garmin Coach] Weekly digest: 5 things to look at"
    assert "- 3 findings: 2 fix alone, 1 Mark's yes" in body
    assert "  • Two screens named different sleep scores (fix alone, triaged)" in body
    assert "- job_outcome: 2" in body
    assert "- morning-sync: 1 degraded of 7" in body
    assert "pauses in 10 days" in body


def test_a_missing_proof_and_a_missing_backup_say_so() -> None:
    data = _healthy()
    del data.latest["backup"]
    del data.latest["backup-drill"]
    subject, body = compose(data)
    assert "- Nightly backup: no run recorded." in body
    assert "- Offsite restore proof: not confirmed this week." in body
    assert subject.endswith("2 things to look at")


@pytest.mark.asyncio
async def test_the_job_skips_without_the_email_route(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "alert_email_relay_url", "")
    result = await scheduler.run_weekly_ops_digest()
    assert (result.status.value, result.reason) == ("skipped", "email_route_unset")


class _FakeSession:
    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


@pytest.mark.asyncio
@pytest.mark.parametrize(("sent", "status"), [(True, "succeeded"), (False, "failed")])
async def test_the_job_sends_the_composed_digest(
    monkeypatch: pytest.MonkeyPatch, sent: bool, status: str
) -> None:
    monkeypatch.setattr(
        settings, "alert_email_relay_url", "https://script.google.com/macros/s/x/exec"
    )
    monkeypatch.setattr(settings, "alert_email_relay_secret", "s")
    monkeypatch.setattr(scheduler, "AsyncSessionLocal", _FakeSession)
    monkeypatch.setattr(weekly_digest, "collect", AsyncMock(return_value=_healthy()))
    send = AsyncMock(return_value=sent)
    monkeypatch.setattr(scheduler.operator_email, "send", send)
    result = await scheduler.run_weekly_ops_digest()
    assert result.status.value == status
    subject, body = send.await_args.args
    assert subject == "[Garmin Coach] Weekly digest: all clear" and "BACKUPS" in body


def test_the_digest_is_registered_watched_and_bucketed_by_the_london_week() -> None:
    sched = scheduler.create_scheduler()
    try:
        job = sched.get_job("weekly_ops_digest")
        assert job is not None
        assert "day_of_week='sun'" in str(job.trigger) and "hour='19'" in str(job.trigger)
        assert str(job.trigger.timezone) == "Europe/London"
    finally:
        if sched.running:
            sched.shutdown(wait=False)
    assert "weekly-ops-digest" in run_scheduled.JOBS
    assert job_ledger_freshness.MAX_AGE["weekly-ops-digest"] == timedelta(days=9)
    start, end = job_runs.scheduled_window("weekly-ops-digest", datetime(2026, 11, 29, 19, 0))
    assert (start, end) == (datetime(2026, 11, 23, 0, 0), datetime(2026, 11, 30, 0, 0))


@pytest.mark.asyncio
async def test_collect_counts_the_week_from_the_queue_and_the_job_log(
    db_conn: AsyncConnection,
) -> None:
    factory = async_sessionmaker(
        bind=db_conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    async with factory() as session:
        await session.execute(text("DELETE FROM improvement_items"))
        week_ago = NOW - timedelta(days=7)
        for days, source, kind in (
            (2, "review", "figure_mismatch"),
            (10, "review", "app_words"),
            (3, "correction", "feedback_summary"),
        ):
            await improvement_items.record(
                session,
                source=source,
                kind=kind,
                summary=f"{kind} summary",
                fingerprint=f"{kind}:{uuid.uuid4()}",
                now=NOW - timedelta(days=days),
            )
        for hours in (5, 4):
            await improvement_items.record(
                session,
                source="job_outcome",
                kind="morning-sync",
                summary="The morning-sync job finished degraded",
                fingerprint="job:morning-sync-digest-test",
                now=NOW - timedelta(hours=hours),
            )
        session.add_all([_run("morning-sync", status="degraded"), _run("backup")])
        await session.flush()
        data = await weekly_digest.collect(session, now=NOW)
    assert [f["summary"] for f in data.findings] == ["figure_mismatch summary"]
    assert data.alerts["morning-sync"] == 2
    assert data.mark_points["correction"] == 1
    assert data.unhealthy["morning-sync"]["degraded"] >= 1
    assert data.latest["backup"].status == "succeeded"
    assert data.week_start == week_ago


def test_a_finding_without_a_lane_says_so() -> None:
    data: Any = _healthy()
    data.findings = [{"summary": "s", "lane": None, "state": "new"}]
    _, body = compose(data)
    assert "(no lane yet, new)" in body
