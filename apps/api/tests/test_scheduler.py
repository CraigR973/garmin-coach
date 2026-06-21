"""Unit tests for the garmin-coach scheduler."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.notification import ActionType, ActorType, AuditLog
from src.scheduler import (
    _retry_async,
    _retry_sync,
    _sync_garmin_daily,
    create_scheduler,
    run_hive_temperature_poll,
    run_morning_weather_sync,
    run_scheduled_backup,
    run_workout_autopush,
)


def _profile(timezone: str = "Europe/London") -> MagicMock:
    profile = MagicMock()
    profile.id = uuid.uuid4()
    profile.timezone = timezone
    profile.latitude = None
    profile.longitude = None
    return profile


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


@pytest.mark.asyncio
async def test_run_hive_temperature_poll_passes_poll_time_to_sync() -> None:
    session = AsyncMock()

    class _ExecuteResult:
        def scalars(self) -> _ExecuteResult:
            return self

        def all(self) -> list[MagicMock]:
            return [_profile()]

    session.execute = AsyncMock(return_value=_ExecuteResult())
    session.commit = AsyncMock()

    class _Ctx:
        async def __aenter__(self) -> AsyncMock:
            return session

        async def __aexit__(self, *a: object) -> None:
            return None

    hive_client = MagicMock()
    hive_client.fetch_payloads.return_value = MagicMock()
    sync_service = AsyncMock()
    sync_service.sync_hive_temperatures = AsyncMock(
        return_value=MagicMock(temperature_readings_synced=1)
    )

    with (
        patch("src.scheduler.AsyncSessionLocal", return_value=_Ctx()),
        patch("src.scheduler.HiveClient", return_value=hive_client),
        patch("src.scheduler.EnvironmentSyncService", return_value=sync_service),
    ):
        await run_hive_temperature_poll()

    sync_service.sync_hive_temperatures.assert_awaited_once()
    kwargs = sync_service.sync_hive_temperatures.await_args.kwargs
    assert kwargs["commit"] is False
    assert kwargs["captured_at_utc"] is not None


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
async def test_retry_sync_uses_exponential_backoff() -> None:
    """A transient 429 is survived and the sleep delay grows by the backoff factor."""
    calls = 0

    def operation() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise RuntimeError("429 Too Many Requests")
        return "ok"

    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    with patch("src.scheduler.asyncio.sleep", new=fake_sleep):
        result = await _retry_sync(operation, attempts=3, delay_sec=1.0, backoff=2.0)

    assert result == "ok"
    assert calls == 3
    assert sleeps == [1.0, 2.0]


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
    """Environment and evening-alert cadences stay stable."""
    scheduler = create_scheduler()
    try:
        jobs = scheduler.get_jobs()
        job_ids = {j.id for j in jobs}
        assert job_ids == {
            "daily_backup",
            "hive_temperature_poll",
            "morning_weather_sync",
            "garmin_activity_poll",
            "workout_autopush",
            "evening_sleep_nudge",
            "evening_monitoring_alerts",
        }

        hive_job = scheduler.get_job("hive_temperature_poll")
        weather_job = scheduler.get_job("morning_weather_sync")
        garmin_job = scheduler.get_job("garmin_activity_poll")
        autopush_job = scheduler.get_job("workout_autopush")
        nudge_job = scheduler.get_job("evening_sleep_nudge")
        monitoring_job = scheduler.get_job("evening_monitoring_alerts")
        assert hive_job is not None
        assert weather_job is not None
        assert garmin_job is not None
        assert autopush_job is not None
        assert nudge_job is not None
        assert monitoring_job is not None
        assert str(hive_job.trigger) == "interval[0:15:00]"
        assert "hour='6', minute='30'" in str(weather_job.trigger)
        assert str(garmin_job.trigger) == "interval[1:00:00]"
        assert "hour='7,13,19', minute='0'" in str(autopush_job.trigger)
        assert "hour='20', minute='0'" in str(nudge_job.trigger)
        assert "hour='19-22', minute='0,15,30,45'" in str(monitoring_job.trigger)
        assert hive_job.coalesce is True
        assert weather_job.max_instances == 1
        assert garmin_job.coalesce is True
        assert garmin_job.max_instances == 1
        assert autopush_job.coalesce is True
        assert autopush_job.max_instances == 1
        assert nudge_job.coalesce is True
        assert monitoring_job.max_instances == 1
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)


# ---------------------------------------------------------------------------
# _sync_garmin_daily (Batch 18)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_garmin_daily_syncs_metrics_and_sleep() -> None:
    """Each active profile's daily metrics + sleep are synced and counted."""
    session = AsyncMock()
    profiles = [_profile(), _profile()]

    client = MagicMock()
    client.fetch_daily_payloads = MagicMock(return_value="payloads")

    sync_service = MagicMock()
    sync_service.sync_daily = AsyncMock(
        return_value=MagicMock(daily_metrics_synced=1, sleep_synced=1)
    )

    with patch("src.scheduler.GarminSyncService", return_value=sync_service):
        daily, sleep = await _sync_garmin_daily(session, profiles, client=client)

    assert (daily, sleep) == (2, 2)
    assert client.fetch_daily_payloads.call_count == 2
    assert sync_service.sync_daily.await_count == 2
    # commit is the caller's responsibility — the helper only syncs with commit=False
    for call in sync_service.sync_daily.await_args_list:
        assert call.kwargs["commit"] is False


@pytest.mark.asyncio
async def test_sync_garmin_daily_isolates_profile_failure() -> None:
    """One profile's Garmin failure is logged and skipped; others still sync."""
    session = AsyncMock()
    good, bad = _profile(), _profile()

    client = MagicMock()
    client.fetch_daily_payloads = MagicMock(return_value="payloads")

    sync_service = MagicMock()

    async def sync_daily(user_id: uuid.UUID, *_a: object, **_k: object) -> MagicMock:
        if user_id == bad.id:
            raise RuntimeError("Garmin 429")
        return MagicMock(daily_metrics_synced=1, sleep_synced=1)

    sync_service.sync_daily = AsyncMock(side_effect=sync_daily)

    with patch("src.scheduler.GarminSyncService", return_value=sync_service):
        daily, sleep = await _sync_garmin_daily(session, [bad, good], client=client)

    # The failing profile contributes nothing; the healthy one still syncs.
    assert (daily, sleep) == (1, 1)
    assert sync_service.sync_daily.await_count == 2


@pytest.mark.asyncio
async def test_sync_garmin_daily_no_profiles_skips_client() -> None:
    """With no active profiles the helper short-circuits without building a client."""
    session = AsyncMock()
    with patch("src.scheduler.GarminConnectClient") as client_cls:
        result = await _sync_garmin_daily(session, [])
    assert result == (0, 0)
    client_cls.assert_not_called()


@pytest.mark.asyncio
async def test_morning_weather_sync_runs_daily_sync_before_analysis() -> None:
    """The morning job syncs Garmin daily data before generating the verdict."""
    profile = _profile()
    calls: list[str] = []

    session = AsyncMock()
    session.commit = AsyncMock(side_effect=lambda: calls.append("commit"))

    scalars = MagicMock()
    scalars.scalars.return_value.all.return_value = [profile]
    session.execute = AsyncMock(return_value=scalars)

    class _Ctx:
        async def __aenter__(self) -> AsyncMock:
            return session

        async def __aexit__(self, *a: object) -> None:
            return None

    weather_service = MagicMock()
    weather_service.sync_weather_daily = AsyncMock(return_value=MagicMock(weather_days_synced=1))
    meteo_client = MagicMock()
    meteo_client.fetch_daily_payload = AsyncMock(return_value="weather")

    async def fake_daily_sync(_session: object, _profiles: object, **_k: object) -> tuple[int, int]:
        calls.append("garmin_daily")
        return (1, 1)

    analysis_service = MagicMock()

    async def generate(_profile: object, _date: object) -> MagicMock:
        calls.append("analysis")
        return MagicMock(generated=True)

    analysis_service.generate_and_store = AsyncMock(side_effect=generate)

    with (
        patch("src.scheduler.AsyncSessionLocal", return_value=_Ctx()),
        patch("src.scheduler.OpenMeteoClient", return_value=meteo_client),
        patch("src.scheduler.EnvironmentSyncService", return_value=weather_service),
        patch("src.scheduler._sync_garmin_daily", side_effect=fake_daily_sync),
        patch("src.scheduler.MorningAnalysisService", return_value=analysis_service),
    ):
        await run_morning_weather_sync()

    assert "garmin_daily" in calls
    assert "analysis" in calls
    assert calls.index("garmin_daily") < calls.index("analysis")


@pytest.mark.asyncio
async def test_run_workout_autopush_pushes_per_profile() -> None:
    """The autopush job delegates to auto_push_due for each active profile."""
    profiles = [_profile(), _profile()]

    session = AsyncMock()

    class _ExecuteResult:
        def scalars(self) -> _ExecuteResult:
            return self

        def all(self) -> list[MagicMock]:
            return profiles

    session.execute = AsyncMock(return_value=_ExecuteResult())

    class _Ctx:
        async def __aenter__(self) -> AsyncMock:
            return session

        async def __aexit__(self, *a: object) -> None:
            return None

    coaching_service = MagicMock()
    coaching_service.auto_push_due = AsyncMock(return_value=[MagicMock()])

    with (
        patch("src.scheduler.AsyncSessionLocal", return_value=_Ctx()),
        patch("src.scheduler.ExecutableCoachingService", return_value=coaching_service),
    ):
        await run_workout_autopush()

    assert coaching_service.auto_push_due.await_count == 2


@pytest.mark.asyncio
async def test_run_workout_autopush_isolates_profile_failure() -> None:
    """One profile's push failure is logged and skipped; others still run."""
    good, bad = _profile(), _profile()

    session = AsyncMock()

    class _ExecuteResult:
        def scalars(self) -> _ExecuteResult:
            return self

        def all(self) -> list[MagicMock]:
            return [bad, good]

    session.execute = AsyncMock(return_value=_ExecuteResult())

    class _Ctx:
        async def __aenter__(self) -> AsyncMock:
            return session

        async def __aexit__(self, *a: object) -> None:
            return None

    coaching_service = MagicMock()

    async def auto_push(profile: object, **_k: object) -> list[MagicMock]:
        if profile is bad:
            raise RuntimeError("intervals.icu 503")
        return [MagicMock()]

    coaching_service.auto_push_due = AsyncMock(side_effect=auto_push)

    with (
        patch("src.scheduler.AsyncSessionLocal", return_value=_Ctx()),
        patch("src.scheduler.ExecutableCoachingService", return_value=coaching_service),
    ):
        await run_workout_autopush()

    assert coaching_service.auto_push_due.await_count == 2


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
        assert scheduler.get_job("garmin_activity_poll") is not None
        assert scheduler.get_job("evening_sleep_nudge") is not None
        assert scheduler.get_job("evening_monitoring_alerts") is not None

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
