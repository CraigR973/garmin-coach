"""Tests for the single-job runner used by external cron."""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, patch

import pytest

from src import run_scheduled
from src.services.job_runs import JobResult


def test_jobs_cover_expected_names() -> None:
    assert set(run_scheduled.JOBS) == {
        "hive-poll",
        "wake-check",
        "morning-sync",
        "activity-poll",
        "autopush",
        "weekly-review",
        "state-change",
        "evening-nudge",
        "evening-alerts",
        "fan-control",
        "backup",
        "backup-drill",
    }


def test_jobs_map_to_the_same_scheduler_coroutines() -> None:
    from src import scheduler

    assert run_scheduled.JOBS["hive-poll"] is scheduler.run_hive_temperature_poll
    assert run_scheduled.JOBS["wake-check"] is scheduler.run_wake_check
    assert run_scheduled.JOBS["morning-sync"] is scheduler.run_morning_weather_sync
    assert run_scheduled.JOBS["activity-poll"] is scheduler.run_garmin_activity_poll
    assert run_scheduled.JOBS["backup"] is scheduler.run_scheduled_backup
    assert run_scheduled.JOBS["backup-drill"] is scheduler.run_backup_restore_drill
    assert run_scheduled.JOBS["weekly-review"] is scheduler.run_weekly_review_delivery
    assert run_scheduled.JOBS["state-change"] is scheduler.run_state_change_coach


@pytest.mark.asyncio
async def test_run_awaits_selected_job() -> None:
    fake = AsyncMock()
    tracked = AsyncMock(return_value=JobResult.succeeded(readings=1))
    with (
        patch.dict(run_scheduled.JOBS, {"hive-poll": fake}),
        patch("src.run_scheduled.run_tracked_job", tracked),
    ):
        result = await run_scheduled._run("hive-poll")
    tracked.assert_awaited_once_with("hive-poll", fake)
    assert result.exit_code == 0


def test_main_runs_named_job(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["run_scheduled", "backup"])
    run = AsyncMock(return_value=JobResult.succeeded(backups=1))
    with patch("src.run_scheduled._run", run):
        run_scheduled.main()
    run.assert_awaited_once_with("backup")


def test_main_exits_nonzero_when_job_reports_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["run_scheduled", "backup"])
    run = AsyncMock(return_value=JobResult.failed("backup_failed"))
    with (
        patch("src.run_scheduled._run", run),
        pytest.raises(SystemExit) as exc_info,
    ):
        run_scheduled.main()
    assert exc_info.value.code == 1


def test_main_rejects_unknown_job(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["run_scheduled", "not-a-job"])
    with pytest.raises(SystemExit):
        run_scheduled.main()
