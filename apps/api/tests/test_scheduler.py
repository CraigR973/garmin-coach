"""Unit tests for the garmin-coach scheduler."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.notification import ActionType, ActorType, AuditLog
from src.scheduler import _retry_async, _retry_sync, create_scheduler, run_scheduled_backup

# ---------------------------------------------------------------------------
# run_scheduled_backup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_scheduled_backup_failure_writes_audit() -> None:
    """When create_backup raises, an audit row is written."""
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()

    class _Ctx:
        async def __aenter__(self) -> AsyncMock:
            return session

        async def __aexit__(self, *a: object) -> None:
            return None

    with (
        patch(
            "src.scheduler.create_backup",
            new_callable=AsyncMock,
            side_effect=RuntimeError("pg_dump not found"),
        ),
        patch("src.scheduler.AsyncSessionLocal", return_value=_Ctx()),
    ):
        await run_scheduled_backup()

    added = [call.args[0] for call in session.add.call_args_list]
    audit_rows = [a for a in added if isinstance(a, AuditLog)]
    assert len(audit_rows) == 1
    row = audit_rows[0]
    assert row.action_type == ActionType.backup_failed
    assert row.actor_type == ActorType.system
    assert "pg_dump not found" in row.changes["error"]
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_scheduled_backup_success_does_not_raise() -> None:
    """On success, no exception is raised."""
    info = MagicMock()
    info.filename = "backup-20260619.sql.gz"
    info.size_bytes = 1024

    with patch(
        "src.scheduler.create_backup",
        new_callable=AsyncMock,
        return_value=info,
    ):
        await run_scheduled_backup()
    # No exception raised = pass


# ---------------------------------------------------------------------------
# create_scheduler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retry_sync_retries_transient_failure() -> None:
    calls = 0

    def operation() -> str:
        nonlocal calls
        calls += 1
        if calls < 2:
            raise RuntimeError("temporary")
        return "ok"

    result = await _retry_sync(operation, attempts=3, delay_sec=0)

    assert result == "ok"
    assert calls == 2


@pytest.mark.asyncio
async def test_retry_async_retries_transient_failure() -> None:
    calls = 0

    async def operation() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise RuntimeError("temporary")
        return "ok"

    result = await _retry_async(operation, attempts=3, delay_sec=0)

    assert result == "ok"
    assert calls == 3


def test_create_scheduler_registers_daily_backup_job() -> None:
    scheduler = create_scheduler()
    try:
        job = scheduler.get_job("daily_backup")
        assert job is not None
        assert str(job.trigger) == "cron[hour='3', minute='0']"
        assert job.coalesce is True
        assert job.max_instances == 1
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)


def test_create_scheduler_registers_environment_jobs() -> None:
    """Environment cadence stays stable; morning weather job now triggers analysis internally."""
    scheduler = create_scheduler()
    try:
        jobs = scheduler.get_jobs()
        job_ids = {j.id for j in jobs}
        assert job_ids == {"daily_backup", "hive_temperature_poll", "morning_weather_sync"}

        hive_job = scheduler.get_job("hive_temperature_poll")
        weather_job = scheduler.get_job("morning_weather_sync")
        assert hive_job is not None
        assert weather_job is not None
        assert str(hive_job.trigger) == "interval[0:15:00]"
        assert "hour='6', minute='30'" in str(weather_job.trigger)
        assert hive_job.coalesce is True
        assert weather_job.max_instances == 1
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)


# ---------------------------------------------------------------------------
# Lifespan integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scheduler_lifespan_starts_and_stops(monkeypatch: pytest.MonkeyPatch) -> None:
    """Lifespan context starts the scheduler when enabled."""
    import asyncio

    from src.config import settings
    from src.main import app, lifespan

    monkeypatch.setattr(settings, "scheduler_enabled", True)

    async with lifespan(app):
        scheduler = app.state.scheduler
        assert scheduler.running is True
        assert scheduler.get_job("daily_backup") is not None
        assert scheduler.get_job("hive_temperature_poll") is not None
        assert scheduler.get_job("morning_weather_sync") is not None

    await asyncio.sleep(0)
    assert scheduler.running is False


@pytest.mark.asyncio
async def test_scheduler_lifespan_disabled_skips_start(monkeypatch: pytest.MonkeyPatch) -> None:
    """When scheduler_enabled is False the scheduler is created but never started."""
    from src.config import settings
    from src.main import app, lifespan

    monkeypatch.setattr(settings, "scheduler_enabled", False)

    async with lifespan(app):
        assert app.state.scheduler.running is False
