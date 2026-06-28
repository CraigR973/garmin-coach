"""Unit tests for the garmin-coach scheduler."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from contextlib import ExitStack, contextmanager
from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.models.coaching import Analysis
from src.models.notification import ActionType, ActorType, AuditLog
from src.models.profile import Profile, UserRole
from src.scheduler import (
    _retry_async,
    _retry_sync,
    _sync_garmin_daily,
    create_scheduler,
    run_hive_temperature_poll,
    run_morning_weather_sync,
    run_scheduled_backup,
    run_wake_check,
    run_workout_autopush,
)
from src.services.wake_detection import (
    BACKSTOP,
    WAKE_CHECK_ANALYSIS_TYPE,
    WakeDecision,
)

LONDON = ZoneInfo("Europe/London")
_SLEEP_END = datetime(2026, 6, 24, 7, 0)  # UTC-naive, == 08:00 BST


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
            "wake_check",
            "morning_backstop",
            "garmin_activity_poll",
            "workout_autopush",
            "evening_sleep_nudge",
            "evening_monitoring_alerts",
            "fan_control",
        }

        hive_job = scheduler.get_job("hive_temperature_poll")
        wake_job = scheduler.get_job("wake_check")
        backstop_job = scheduler.get_job("morning_backstop")
        garmin_job = scheduler.get_job("garmin_activity_poll")
        autopush_job = scheduler.get_job("workout_autopush")
        nudge_job = scheduler.get_job("evening_sleep_nudge")
        monitoring_job = scheduler.get_job("evening_monitoring_alerts")
        assert hive_job is not None
        assert wake_job is not None
        assert backstop_job is not None
        assert garmin_job is not None
        assert autopush_job is not None
        assert nudge_job is not None
        assert monitoring_job is not None
        assert str(hive_job.trigger) == "interval[0:15:00]"
        # The fixed 06:30 morning cron was replaced by a 15-min wake-check poll
        # plus a 09:30 backstop that still runs the (unchanged) morning sync.
        assert str(wake_job.trigger) == "interval[0:15:00]"
        assert "hour='9', minute='30'" in str(backstop_job.trigger)
        assert str(garmin_job.trigger) == "interval[1:00:00]"
        assert "hour='7,13,19', minute='0'" in str(autopush_job.trigger)
        assert "hour='20', minute='0'" in str(nudge_job.trigger)
        assert "hour='19-22', minute='0,15,30,45'" in str(monitoring_job.trigger)
        assert hive_job.coalesce is True
        assert wake_job.coalesce is True
        assert wake_job.max_instances == 1
        assert backstop_job.max_instances == 1
        assert garmin_job.coalesce is True
        assert garmin_job.max_instances == 1
        # The interval jobs are seeded to fire shortly after startup so a
        # short-lived / restarted container still polls (the unseeded 15-min
        # Hive interval was why the live feed stalled).
        assert hive_job.next_run_time is not None
        assert wake_job.next_run_time is not None
        assert garmin_job.next_run_time is not None
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
# run_wake_check — orchestration (mocked) (wake-triggered morning verdict)
# ---------------------------------------------------------------------------


def _local(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 6, 24, hour, minute, tzinfo=LONDON)


class _FakeGarmin:
    """Light fake for the sleep-only poll. Records calls; can be set to raise."""

    def __init__(self, payload: Any = None, *, raise_on_fetch: bool = False) -> None:
        self.payload = payload
        self.raise_on_fetch = raise_on_fetch
        self.calls = 0

    def fetch_sleep(self, target: object) -> Any:
        self.calls += 1
        if self.raise_on_fetch:
            raise RuntimeError("garmin boom")
        return self.payload


@contextmanager
def _wake_patches(
    *,
    profiles: list[MagicMock],
    now: datetime,
    latest_analysis: object | None = None,
    decision: WakeDecision | None = None,
    client: _FakeGarmin | None = None,
):
    """Patch every collaborator of run_wake_check so orchestration is isolated.

    The decision logic itself is covered exhaustively by test_wake_detection;
    here is_morning_ready is stubbed so we assert only the job's wiring.
    """
    session = AsyncMock()
    session.commit = AsyncMock()

    class _Ctx:
        async def __aenter__(self) -> AsyncMock:
            return session

        async def __aexit__(self, *a: object) -> None:
            return None

    morning = MagicMock()
    morning.latest_analysis = AsyncMock(return_value=latest_analysis)
    fake_client = client if client is not None else _FakeGarmin({})
    record = AsyncMock()
    last_seen = AsyncMock(return_value=None)
    is_ready = MagicMock(return_value=decision or WakeDecision("wait", None, "awaiting_stability"))
    morning_sync = AsyncMock()

    with ExitStack() as stack:
        enter = stack.enter_context
        enter(patch("src.scheduler.AsyncSessionLocal", return_value=_Ctx()))
        enter(patch("src.scheduler._active_profiles", AsyncMock(return_value=profiles)))
        enter(patch("src.scheduler.MorningAnalysisService", return_value=morning))
        enter(patch("src.scheduler._profile_now", lambda profile: now))
        enter(patch("src.scheduler.GarminConnectClient", return_value=fake_client))
        enter(patch("src.scheduler._last_seen_sleep_end", last_seen))
        enter(patch("src.scheduler.is_morning_ready", is_ready))
        enter(patch("src.scheduler._record_wake_check", record))
        enter(patch("src.scheduler.run_morning_weather_sync", morning_sync))
        yield SimpleNamespace(
            session=session,
            morning=morning,
            client=fake_client,
            record=record,
            last_seen=last_seen,
            is_ready=is_ready,
            morning_sync=morning_sync,
        )


@pytest.mark.asyncio
async def test_wake_check_fires_and_triggers_morning_sync() -> None:
    decision = WakeDecision("fire", _SLEEP_END, "stable_wake")
    with _wake_patches(profiles=[_profile()], now=_local(8, 25), decision=decision) as m:
        await run_wake_check()

    m.morning_sync.assert_awaited_once()
    m.record.assert_awaited_once()
    # The fire decision was the one persisted.
    assert m.record.await_args.args[3].action == "fire"
    # The job feeds is_morning_ready London-local now + the 09:30 backstop + floors.
    kwargs = m.is_ready.call_args.kwargs
    assert kwargs["backstop"] == BACKSTOP
    assert kwargs["duration_floor_min"] == 180
    assert kwargs["settle_min"] == 20
    assert kwargs["now"].tzinfo is not None
    assert kwargs["today"].isoformat() == "2026-06-24"


@pytest.mark.asyncio
async def test_wake_check_waits_without_triggering_morning_sync() -> None:
    decision = WakeDecision("wait", _SLEEP_END, "awaiting_stability")
    with _wake_patches(profiles=[_profile()], now=_local(8, 5), decision=decision) as m:
        await run_wake_check()

    m.morning_sync.assert_not_awaited()
    m.record.assert_awaited_once()
    assert m.record.await_args.args[3].action == "wait"


@pytest.mark.asyncio
async def test_wake_check_short_circuits_when_analysis_exists() -> None:
    """Today's verdict already exists → no Garmin call, no decision, no re-fire."""
    with _wake_patches(
        profiles=[_profile()],
        now=_local(8, 25),
        latest_analysis=MagicMock(),
        client=_FakeGarmin(None, raise_on_fetch=True),
    ) as m:
        await run_wake_check()

    assert m.client.calls == 0
    m.is_ready.assert_not_called()
    m.record.assert_not_awaited()
    m.morning_sync.assert_not_awaited()


@pytest.mark.asyncio
async def test_wake_check_outside_window_skips_poll() -> None:
    """Before the morning window: not even a cheap morning-analysis lookup."""
    with _wake_patches(
        profiles=[_profile()],
        now=_local(2, 0),
        client=_FakeGarmin(None, raise_on_fetch=True),
    ) as m:
        await run_wake_check()

    m.morning.latest_analysis.assert_not_awaited()
    assert m.client.calls == 0
    m.morning_sync.assert_not_awaited()


@pytest.mark.asyncio
async def test_wake_check_no_active_profiles_skips() -> None:
    with _wake_patches(
        profiles=[],
        now=_local(8, 25),
        client=_FakeGarmin(None, raise_on_fetch=True),
    ) as m:
        await run_wake_check()

    assert m.client.calls == 0
    m.morning_sync.assert_not_awaited()


@pytest.mark.asyncio
async def test_wake_check_sleep_fetch_failure_is_isolated() -> None:
    """A Garmin failure is logged and skipped — no decision, no fire, no crash."""
    failing = _FakeGarmin(None, raise_on_fetch=True)
    with (
        _wake_patches(profiles=[_profile()], now=_local(8, 25), client=failing) as m,
        patch("src.scheduler.asyncio.sleep", new=AsyncMock()),
    ):
        await run_wake_check()

    assert failing.calls >= 1  # it tried (and retried)
    m.is_ready.assert_not_called()
    m.record.assert_not_awaited()
    m.morning_sync.assert_not_awaited()


# ---------------------------------------------------------------------------
# run_wake_check — DB-backed (real Postgres, fake Garmin, no LLM)
# Skips automatically when DATABASE_URL is unset; CI runs them.
# ---------------------------------------------------------------------------


def _bind(db_conn: AsyncConnection) -> Callable[[], AsyncSession]:
    def factory() -> AsyncSession:
        return AsyncSession(bind=db_conn, expire_on_commit=False)

    return factory


def _sleep_payload(
    *,
    sleep_end: str = "2026-06-24T07:00:00",
    duration_sec: int = 28800,
    day: str = "2026-06-24",
) -> dict[str, Any]:
    return {
        "dailySleepDTO": {
            "calendarDate": day,
            "sleepStartTimestampGMT": "2026-06-23T23:00:00",
            "sleepEndTimestampGMT": sleep_end,
            "sleepTimeSeconds": duration_sec,
            "sleepScores": {"overall": {"value": 80, "qualifierKey": "good"}},
        }
    }


async def _seed_profile(db_conn: AsyncConnection, user_id: uuid.UUID) -> None:
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add(
            Profile(
                id=user_id,
                display_name="Wake Test",
                pin_hash="x" * 60,
                role=UserRole.admin,
                timezone="Europe/London",
                is_active=True,
            )
        )
        await session.commit()


async def _wake_check_row(db_conn: AsyncConnection, user_id: uuid.UUID) -> Analysis | None:
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        return await session.scalar(
            select(Analysis)
            .where(
                Analysis.user_id == user_id,
                Analysis.analysis_type == WAKE_CHECK_ANALYSIS_TYPE,
            )
            .order_by(Analysis.generated_at_utc.desc())
            .limit(1)
        )


async def _count_wake_check(db_conn: AsyncConnection, user_id: uuid.UUID) -> int:
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        return (
            await session.scalar(
                select(func.count())
                .select_from(Analysis)
                .where(
                    Analysis.user_id == user_id,
                    Analysis.analysis_type == WAKE_CHECK_ANALYSIS_TYPE,
                )
            )
        ) or 0


@pytest.mark.asyncio
async def test_wake_check_persists_then_fires(db_conn: AsyncConnection) -> None:
    """Poll 1 records the sleepEnd (wait); poll 2 reads it back, settles, fires."""
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    client = _FakeGarmin(_sleep_payload())
    morning_sync = AsyncMock()
    now = {"value": _local(8, 5)}  # 07:05 UTC → not yet settled

    with (
        patch("src.scheduler.AsyncSessionLocal", new=_bind(db_conn)),
        patch("src.scheduler.GarminConnectClient", return_value=client),
        patch("src.scheduler._profile_now", lambda profile: now["value"]),
        patch("src.scheduler.run_morning_weather_sync", morning_sync),
    ):
        await run_wake_check()  # poll 1 → first sighting → wait, persist 07:00
        row1 = await _wake_check_row(db_conn, user_id)
        assert row1 is not None
        assert row1.verdict == "wait"
        assert row1.context_packet["sleepEndUtc"] == "2026-06-24T07:00:00"
        morning_sync.assert_not_awaited()

        now["value"] = _local(8, 25)  # 07:25 UTC → settled 25 min
        await run_wake_check()  # poll 2 → stable + settled → fire

    row2 = await _wake_check_row(db_conn, user_id)
    assert row2 is not None
    assert row2.verdict == "fire"
    morning_sync.assert_awaited_once()
    assert client.calls == 2  # one cheap Garmin poll per run


@pytest.mark.asyncio
async def test_wake_check_backstop_fires_on_unfinalized(db_conn: AsyncConnection) -> None:
    """Past 09:30 with no finalized session → fire on whatever exists."""
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    client = _FakeGarmin({})  # no dailySleepDTO → unfinalized
    morning_sync = AsyncMock()

    with (
        patch("src.scheduler.AsyncSessionLocal", new=_bind(db_conn)),
        patch("src.scheduler.GarminConnectClient", return_value=client),
        patch("src.scheduler._profile_now", lambda profile: _local(9, 35)),
        patch("src.scheduler.run_morning_weather_sync", morning_sync),
    ):
        await run_wake_check()

    morning_sync.assert_awaited_once()
    row = await _wake_check_row(db_conn, user_id)
    assert row is not None
    assert row.verdict == "fire"
    assert row.context_packet["reason"] == "backstop"
    assert row.context_packet["sleepEndUtc"] is None


@pytest.mark.asyncio
async def test_wake_check_short_circuits_with_existing_morning_row(
    db_conn: AsyncConnection,
) -> None:
    """A real morning analysis row for today stops the poll cold — no Garmin call."""
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add(
            Analysis(
                user_id=user_id,
                analysis_type="morning",
                subject_date=datetime(2026, 6, 24).date(),
                generated_at_utc=datetime(2026, 6, 24, 8, 0),
                prompt_version="morning-x",
                verdict="Green",
                context_packet={},
                output_markdown="x",
                raw_response={},
            )
        )
        await session.commit()

    client = _FakeGarmin(None, raise_on_fetch=True)
    morning_sync = AsyncMock()
    with (
        patch("src.scheduler.AsyncSessionLocal", new=_bind(db_conn)),
        patch("src.scheduler.GarminConnectClient", return_value=client),
        patch("src.scheduler._profile_now", lambda profile: _local(8, 25)),
        patch("src.scheduler.run_morning_weather_sync", morning_sync),
    ):
        await run_wake_check()

    assert client.calls == 0
    morning_sync.assert_not_awaited()
    assert await _count_wake_check(db_conn, user_id) == 0


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
        assert scheduler.get_job("wake_check") is not None
        assert scheduler.get_job("morning_backstop") is not None
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
