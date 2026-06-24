"""Tests for the single-job runner used by external cron."""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, patch

import pytest

from src import run_scheduled


def test_jobs_cover_expected_names() -> None:
    assert set(run_scheduled.JOBS) == {
        "hive-poll",
        "wake-check",
        "morning-sync",
        "activity-poll",
        "autopush",
        "evening-nudge",
        "evening-alerts",
        "backup",
    }


def test_jobs_map_to_the_same_scheduler_coroutines() -> None:
    from src import scheduler

    assert run_scheduled.JOBS["hive-poll"] is scheduler.run_hive_temperature_poll
    assert run_scheduled.JOBS["wake-check"] is scheduler.run_wake_check
    assert run_scheduled.JOBS["morning-sync"] is scheduler.run_morning_weather_sync
    assert run_scheduled.JOBS["activity-poll"] is scheduler.run_garmin_activity_poll
    assert run_scheduled.JOBS["backup"] is scheduler.run_scheduled_backup


@pytest.mark.asyncio
async def test_run_awaits_selected_job() -> None:
    fake = AsyncMock()
    with patch.dict(run_scheduled.JOBS, {"hive-poll": fake}):
        await run_scheduled._run("hive-poll")
    fake.assert_awaited_once()


def test_main_runs_named_job(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = AsyncMock()
    monkeypatch.setattr(sys, "argv", ["run_scheduled", "backup"])
    with patch.dict(run_scheduled.JOBS, {"backup": fake}):
        run_scheduled.main()
    fake.assert_awaited_once()


def test_main_rejects_unknown_job(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["run_scheduled", "not-a-job"])
    with pytest.raises(SystemExit):
        run_scheduled.main()
