"""Batch 242.5 — the ledger check that runs outside the scheduler it watches."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.models.operations import JobRun
from src.run_scheduled import JOBS
from src.services.job_ledger_freshness import (
    MAX_AGE,
    collect_freshness,
    run_ledger_freshness_check,
)
from src.services.job_runs import JobStatus

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)


def _session_ctx(session: object) -> object:
    class _Ctx:
        async def __aenter__(self) -> object:
            return session

        async def __aexit__(self, *a: object) -> None:
            return None

    return _Ctx()


def test_the_watchdog_is_not_registered_in_the_scheduler_it_watches() -> None:
    """The property the whole phase exists for.

    A freshness check registered on the in-process APScheduler stops running for
    exactly the reason it would need to fire. It must stay reachable only
    through the external runner.
    """
    from src import scheduler as scheduler_module

    assert "ledger-freshness" in JOBS
    assert not hasattr(scheduler_module, "run_ledger_freshness_check")

    # Never started, so never shut down — only its registration is under test.
    registered = {job.id for job in scheduler_module.create_scheduler().get_jobs()}
    assert "ledger_freshness" not in registered
    assert not any("ledger" in job_id for job_id in registered)


def test_every_externally_runnable_recurring_job_has_a_tolerance() -> None:
    """A job nothing watches is how DS237-01 happened. Adding one must be noticed."""
    watched = set(MAX_AGE)
    runnable = set(JOBS) - {
        "ledger-freshness",  # the watchdog does not watch itself
    }
    assert runnable <= watched, f"unwatched jobs: {sorted(runnable - watched)}"


@pytest.mark.asyncio
async def test_a_job_that_has_never_run_is_stale() -> None:
    session = MagicMock()
    session.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[])))

    report = await collect_freshness(session, now_utc=NOW)

    assert len(report.checked) == len(MAX_AGE)
    assert len(report.stale) == len(MAX_AGE)
    assert all(entry.last_run_utc is None for entry in report.stale)


@pytest.mark.asyncio
async def test_a_recent_run_is_fresh_and_an_overdue_one_is_not() -> None:
    naive_now = NOW.replace(tzinfo=None)
    # Everything ran five minutes ago except hive-poll, which stopped a
    # fortnight back — longer than every tolerance in the map.
    rows = [
        (name, naive_now - (timedelta(days=14) if name == "hive-poll" else timedelta(minutes=5)))
        for name in MAX_AGE
    ]
    session = MagicMock()
    session.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=rows)))

    report = await collect_freshness(session, now_utc=NOW)

    assert {entry.job_name for entry in report.stale} == {"hive-poll"}


@pytest.mark.asyncio
async def test_the_check_logs_an_error_per_stale_job_and_reports_degraded() -> None:
    """log.error is the delivery mechanism: it is what Sentry turns into a signal."""
    naive_now = NOW.replace(tzinfo=None)
    rows = [
        (
            name,
            naive_now - (timedelta(days=30) if name == "weekly-review" else timedelta(minutes=5)),
        )
        for name in MAX_AGE
    ]
    session = MagicMock()
    session.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=rows)))
    logger = MagicMock()

    with (
        patch(
            "src.services.job_ledger_freshness.AsyncSessionLocal",
            return_value=_session_ctx(session),
        ),
        patch("src.services.job_ledger_freshness.log", logger),
    ):
        result = await run_ledger_freshness_check(now_utc=NOW)

    assert result.status is JobStatus.degraded
    assert result.reason == "stale_jobs"
    assert result.counters["stale"] == 1
    logger.error.assert_called_once()
    assert logger.error.call_args.kwargs["job_name"] == "weekly-review"
    assert logger.error.call_args.kwargs["reason"] == "overdue"


@pytest.mark.asyncio
async def test_a_fully_fresh_ledger_succeeds_and_logs_no_error() -> None:
    naive_now = NOW.replace(tzinfo=None)
    rows = [(name, naive_now - timedelta(minutes=1)) for name in MAX_AGE]
    session = MagicMock()
    session.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=rows)))
    logger = MagicMock()

    with (
        patch(
            "src.services.job_ledger_freshness.AsyncSessionLocal",
            return_value=_session_ctx(session),
        ),
        patch("src.services.job_ledger_freshness.log", logger),
    ):
        result = await run_ledger_freshness_check(now_utc=NOW)

    assert result.status is JobStatus.succeeded
    assert result.counters == {"checked": len(MAX_AGE), "stale": 0}
    logger.error.assert_not_called()


@pytest.mark.asyncio
async def test_freshness_reads_the_real_ledger(db_conn: AsyncConnection) -> None:
    """Against real rows, so the grouped max() query is exercised, not mocked."""
    naive_now = NOW.replace(tzinfo=None)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        for job_name, started in (
            ("hive-poll", naive_now - timedelta(minutes=10)),
            ("hive-poll", naive_now - timedelta(days=20)),  # older row must lose
            ("weekly-review", naive_now - timedelta(days=30)),
        ):
            session.add(
                JobRun(
                    id=uuid.uuid4(),
                    job_name=job_name,
                    scheduled_window_start_utc=started,
                    scheduled_window_end_utc=started + timedelta(minutes=15),
                    started_at_utc=started,
                    finished_at_utc=started,
                    status=JobStatus.succeeded.value,
                    reason=None,
                    counters={},
                )
            )
        await session.commit()

        report = await collect_freshness(session, now_utc=NOW)

    by_name = {entry.job_name: entry for entry in report.checked}
    # max() picked the newer of the two hive-poll rows.
    assert not by_name["hive-poll"].is_stale
    assert by_name["weekly-review"].is_stale
    # A job with no rows at all reads as stale rather than as absent.
    assert by_name["backup"].last_run_utc is None
    assert by_name["backup"].is_stale
