from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.operations import JobRun
from src.services.job_runs import JobResult, JobStatus, run_tracked_job, scheduled_window


def test_job_result_exit_contract_is_loud_for_partial_or_full_failure() -> None:
    assert JobResult.succeeded().exit_code == 0
    assert JobResult.skipped("outside_window").exit_code == 0
    assert JobResult.degraded("step_failures").exit_code == 1
    assert JobResult.failed("unhandled_exception").exit_code == 1


def test_scheduled_window_uses_the_jobs_cadence_bucket() -> None:
    started = datetime(2026, 8, 15, 10, 37, 42)

    hive_start, hive_end = scheduled_window("hive-poll", started)
    assert hive_start == datetime(2026, 8, 15, 10, 30)
    assert hive_end == datetime(2026, 8, 15, 10, 45)

    activity_start, activity_end = scheduled_window("activity-poll", started)
    assert activity_start == datetime(2026, 8, 15, 10, 0)
    assert activity_end == datetime(2026, 8, 15, 11, 0)

    review_start, review_end = scheduled_window("weekly-review", datetime(2026, 8, 16, 17, 0))
    assert review_start == datetime(2026, 8, 9, 23, 0)  # Monday 00:00 BST
    assert review_end == datetime(2026, 8, 16, 23, 0)


@pytest.mark.asyncio
async def test_tracked_job_persists_typed_result_in_independent_session() -> None:
    session = MagicMock()
    session.add = MagicMock()
    session.commit = AsyncMock()

    class _Ctx:
        async def __aenter__(self) -> MagicMock:
            return session

        async def __aexit__(self, *args: object) -> None:
            return None

    operation = AsyncMock(return_value=JobResult.degraded("profile_failures", profiles=2, failed=1))
    with patch("src.services.job_runs.AsyncSessionLocal", return_value=_Ctx()):
        result = await run_tracked_job(
            "weekly-review",
            operation,
            started_at_utc=datetime(2026, 8, 16, 17, 0),
        )

    assert result.status == JobStatus.degraded
    operation.assert_awaited_once()
    session.commit.assert_awaited_once()
    row = session.add.call_args.args[0]
    assert isinstance(row, JobRun)
    assert row.job_name == "weekly-review"
    assert row.status == "degraded"
    assert row.reason == "profile_failures"
    assert row.counters == {"profiles": 2, "failed": 1}
    assert row.scheduled_window_end_utc > row.scheduled_window_start_utc
    assert row.finished_at_utc >= row.started_at_utc


@pytest.mark.asyncio
async def test_outcome_persistence_failure_makes_external_result_fail() -> None:
    class _Ctx:
        async def __aenter__(self) -> MagicMock:
            session = MagicMock()
            session.add = MagicMock()
            session.commit = AsyncMock(side_effect=RuntimeError("database unavailable"))
            return session

        async def __aexit__(self, *args: object) -> None:
            return None

    with patch("src.services.job_runs.AsyncSessionLocal", return_value=_Ctx()):
        result = await run_tracked_job(
            "hive-poll",
            AsyncMock(return_value=JobResult.succeeded(readings=1)),
        )

    assert result.status == JobStatus.failed
    assert result.reason == "job_run_persistence_failed"
    assert result.exit_code == 1
    assert result.counters["outcome_persistence_failed"] == 1
