"""Unit tests for the garmin-coach scheduler."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from contextlib import ExitStack, contextmanager
from datetime import UTC, date, datetime, timedelta
from functools import partial
from types import SimpleNamespace
from typing import Any
from unittest.mock import ANY, AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import MissingGreenlet
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.config import settings
from src.models.coaching import (
    DAILY_METRIC_PHASE_MORNING,
    Analysis,
    DailyMetric,
    FanStateReading,
    Sleep,
)
from src.models.notification import ActionType, ActorType, AuditLog
from src.models.profile import Profile, UserRole
from src.scheduler import (
    _active_profiles,
    create_scheduler,
    run_activity_timeseries_retention,
    run_backup_restore_drill,
    run_egress_budget_check,
    run_evening_monitoring_alerts,
    run_evening_sleep_nudge,
    run_fan_control,
    run_hive_temperature_poll,
    run_morning_weather_sync,
    run_post_workout_backstop,
    run_scheduled_backup,
    run_state_change_coach,
    run_tracked_job,
    run_wake_check,
    run_wake_nudge,
    run_weekly_review_delivery,
    run_workout_autopush,
)
from src.services.anthropic_text import AnthropicApiError
from src.services.dreo_fan import DreoFanError, DreoFanState
from src.services.generation_requests import GenerationRequestInProgress
from src.services.job_runs import JobResult, JobStatus
from src.services.morning_inputs import MorningInputPresence
from src.services.morning_pipeline import (
    MorningInputResult,
)
from src.services.morning_pipeline import (
    sync_garmin_daily as _sync_garmin_daily,
)
from src.services.retry import retry_async as _retry_async
from src.services.retry import retry_sync as _retry_sync
from src.services.session_recovery import restore_after_rollback as _restore_after_rollback
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

    logger = MagicMock()

    with (
        patch(
            "src.scheduler.create_backup",
            new_callable=AsyncMock,
            side_effect=RuntimeError("pg_dump not found"),
        ),
        patch("src.scheduler.AsyncSessionLocal", return_value=_Ctx()),
        patch("src.scheduler.log", logger),
    ):
        result = await run_scheduled_backup()

    added = [call.args[0] for call in session.add.call_args_list]
    audit_rows = [a for a in added if isinstance(a, AuditLog)]
    assert len(audit_rows) == 1
    row = audit_rows[0]
    assert row.action_type == ActionType.backup_failed
    assert row.actor_type == ActorType.system
    assert "pg_dump not found" in row.changes["error"]
    session.commit.assert_awaited_once()
    assert result.status == JobStatus.failed
    logger.error.assert_called_once_with(
        "operator backup alert",
        kind="backup_failed",
        reason="pg_dump not found",
        alert_route="provider_log_or_external_monitor",
    )


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
async def test_run_backup_restore_drill_records_success_counters() -> None:
    restore_result = MagicMock()
    restore_result.restored_tables = 31
    restore_result.profile_rows = 1
    restore_result.analysis_rows = 20
    restore_result.excluded_activity_timeseries_rows = 0

    with (
        patch.object(settings, "backup_restore_database_url", "postgresql://drill/db"),
        patch(
            "src.scheduler.restore_latest_backup",
            new_callable=AsyncMock,
            return_value=restore_result,
        ) as restore,
    ):
        result = await run_backup_restore_drill()

    assert result.status == JobStatus.succeeded
    assert result.counters == {
        "restored_tables": 31,
        "profiles": 1,
        "analyses": 20,
        "excluded_activity_timeseries_rows": 0,
    }
    restore.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_backup_restore_drill_alerts_on_simulated_failure() -> None:
    logger = MagicMock()

    with (
        patch.object(settings, "backup_restore_database_url", "postgresql://drill/db"),
        patch(
            "src.scheduler.restore_latest_backup",
            new_callable=AsyncMock,
            side_effect=RuntimeError("invariant failed"),
        ),
        patch("src.scheduler.log", logger),
    ):
        result = await run_backup_restore_drill()

    assert result.status == JobStatus.failed
    assert result.reason == "backup_restore_drill_failed"
    assert result.exit_code == 1
    logger.error.assert_called_once_with(
        "operator backup alert",
        kind="backup_restore_drill_failed",
        reason="invariant failed",
        alert_route="provider_log_or_external_monitor",
    )


# ---------------------------------------------------------------------------
# run_egress_budget_check
# ---------------------------------------------------------------------------


class _JobRunCountersExecuteResult:
    def __init__(self, counters: list[dict[str, int]]) -> None:
        self._counters = counters

    def scalars(self) -> _JobRunCountersExecuteResult:
        return self

    def all(self) -> list[dict[str, int]]:
        return self._counters


def _egress_session(
    counters: list[dict[str, int]] | None = None, *, database_bytes: int = 0
) -> AsyncMock:
    """A session double for ``run_egress_budget_check``.

    Batch 247: the job now issues two counter reads (month-to-date and today) and
    one ``pg_database_size`` scalar, so a single canned ``execute`` result is no
    longer enough.
    """
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_JobRunCountersExecuteResult(counters or []))
    session.scalar = AsyncMock(return_value=database_bytes)
    return session


def _session_ctx(session: AsyncMock) -> Any:
    class _Ctx:
        async def __aenter__(self) -> AsyncMock:
            return session

        async def __aexit__(self, *a: object) -> None:
            return None

    return _Ctx()


@pytest.mark.asyncio
async def test_run_egress_budget_check_ok_stage_does_not_alert() -> None:
    session = _egress_session(database_bytes=100_000_000)
    logger = MagicMock()

    with (
        patch("src.scheduler.response_byte_counter") as counter,
        patch("src.scheduler.latest_backup", return_value=None),
        patch("src.scheduler.AsyncSessionLocal", return_value=_session_ctx(session)),
        patch("src.scheduler.log", logger),
    ):
        counter.drain.return_value = 1000
        result = await run_egress_budget_check()

    assert result.status == JobStatus.succeeded
    # Batch 247 (DS237-03 Defect A): named for what it counts. The bytes that
    # bill travel pooler -> application and this proxy cannot see them.
    assert result.counters["http_response_bytes_today"] == 1000
    assert result.counters["http_response_bytes_month"] == 1000
    assert result.counters["alert_stage_ordinal"] == 0
    assert result.counters["database_bytes"] == 100_000_000
    assert result.counters["storage_stage_ordinal"] == 0
    logger.error.assert_not_called()


@pytest.mark.asyncio
async def test_run_egress_budget_check_alerts_once_on_new_stage() -> None:
    from src.services.egress_budget import BUDGET_BYTES

    session = _egress_session(database_bytes=100_000_000)
    logger = MagicMock()

    with (
        patch("src.scheduler.response_byte_counter") as counter,
        patch("src.scheduler.latest_backup", return_value=None),
        patch("src.scheduler.AsyncSessionLocal", return_value=_session_ctx(session)),
        patch("src.scheduler.log", logger),
    ):
        counter.drain.return_value = int(BUDGET_BYTES * 0.6)
        result = await run_egress_budget_check()

    assert result.status == JobStatus.degraded
    assert result.reason == "egress_budget_warning"
    logger.error.assert_called_once_with(
        "operator egress alert",
        kind="egress_budget_warning",
        http_response_bytes_month=int(BUDGET_BYTES * 0.6),
        budget_bytes=BUDGET_BYTES,
        measures="http_response_bytes (application->client); the billed direction "
        "is pooler->application and is not visible to this proxy",
        alert_route="sentry",
    )


@pytest.mark.asyncio
async def test_run_egress_budget_check_does_not_repeat_alert_for_same_stage() -> None:
    from src.services.egress_budget import BUDGET_BYTES

    # The old key name on purpose: a month-to-date sum spans the Batch 247 rename
    # on the day it ships, so the reader must still understand rows written before it.
    prior_counters = [{"response_bytes_delta": 0, "alert_stage_ordinal": 1}]
    session = _egress_session(prior_counters, database_bytes=100_000_000)
    logger = MagicMock()

    with (
        patch("src.scheduler.response_byte_counter") as counter,
        patch("src.scheduler.latest_backup", return_value=None),
        patch("src.scheduler.AsyncSessionLocal", return_value=_session_ctx(session)),
        patch("src.scheduler.log", logger),
    ):
        counter.drain.return_value = int(BUDGET_BYTES * 0.6)
        result = await run_egress_budget_check()

    assert result.status == JobStatus.degraded
    logger.error.assert_not_called()


@pytest.mark.asyncio
async def test_run_egress_budget_check_includes_todays_backup_size() -> None:
    session = _egress_session(database_bytes=100_000_000)
    backup_info = MagicMock()
    backup_info.size_bytes = 5_000_000
    backup_info.created_at = datetime.now(UTC)

    with (
        patch("src.scheduler.response_byte_counter") as counter,
        patch("src.scheduler.latest_backup", return_value=backup_info),
        patch("src.scheduler.AsyncSessionLocal", return_value=_session_ctx(session)),
    ):
        counter.drain.return_value = 0
        result = await run_egress_budget_check()

    assert result.counters["backup_bytes_today"] == 5_000_000
    assert result.counters["http_response_bytes_today"] == 5_000_000


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
# Batch 105 — holiday-away environment gates
# ---------------------------------------------------------------------------


@contextmanager
def _evening_environment_patches(*, active_window: object | None):
    profile = _profile()
    subject_date = date(2026, 7, 12)
    session = AsyncMock()
    session.commit = AsyncMock()
    # Batch 228: the evening job now also runs an operator-only baseline
    # freshness read on its own session. Answer it with "no sleep history", so
    # these thermal/nudge tests exercise the wiring without asserting on it.
    session.execute = AsyncMock(return_value=MagicMock(one=MagicMock(return_value=(None, None))))
    session.scalar = AsyncMock(return_value=None)

    class _Ctx:
        async def __aenter__(self) -> AsyncMock:
            return session

        async def __aexit__(self, *a: object) -> None:
            return None

    holiday_service = MagicMock()
    holiday_service.get_overnight_away_window_for_date = AsyncMock(return_value=active_window)
    nudge_service = MagicMock()
    nudge_service.run_evening_nudge = AsyncMock(return_value=True)
    nudge_service.run_monitoring_alerts = AsyncMock(return_value=1)

    with ExitStack() as stack:
        enter = stack.enter_context
        enter(patch("src.scheduler.AsyncSessionLocal", return_value=_Ctx()))
        enter(patch("src.scheduler._active_profiles", AsyncMock(return_value=[profile])))
        enter(patch("src.scheduler._profile_today", return_value=subject_date))
        enter(patch("src.scheduler.HolidayPauseService", return_value=holiday_service))
        enter(patch("src.scheduler.NudgeAlertService", return_value=nudge_service))
        yield SimpleNamespace(
            profile=profile,
            subject_date=subject_date,
            session=session,
            holiday=holiday_service,
            nudge=nudge_service,
        )


@pytest.mark.asyncio
async def test_holiday_suppresses_evening_nudge_and_thermal_monitoring() -> None:
    with _evening_environment_patches(active_window=MagicMock()) as spies:
        await run_evening_sleep_nudge()
        await run_evening_monitoring_alerts()

    assert spies.holiday.get_overnight_away_window_for_date.await_count == 2
    for call in spies.holiday.get_overnight_away_window_for_date.await_args_list:
        assert call.args == (spies.profile, spies.subject_date)
    spies.nudge.run_evening_nudge.assert_not_awaited()
    spies.nudge.run_monitoring_alerts.assert_awaited_once_with(
        spies.profile,
        commit=False,
        include_thermal=False,
    )
    assert spies.session.commit.await_count == 2


@pytest.mark.asyncio
async def test_normal_day_keeps_evening_nudge_and_monitoring_alerts() -> None:
    with _evening_environment_patches(active_window=None) as spies:
        await run_evening_sleep_nudge()
        await run_evening_monitoring_alerts()

    spies.nudge.run_evening_nudge.assert_awaited_once_with(spies.profile, commit=False)
    spies.nudge.run_monitoring_alerts.assert_awaited_once_with(
        spies.profile,
        commit=False,
        include_thermal=True,
    )
    assert spies.session.commit.await_count == 2


# ---------------------------------------------------------------------------
# Batch 185 — scheduled weekly review delivery
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_weekly_review_delivery_uses_sunday_and_skips_holiday() -> None:
    profile = _profile()
    sunday = date(2026, 8, 2)
    session = AsyncMock()

    class _Ctx:
        async def __aenter__(self) -> AsyncMock:
            return session

        async def __aexit__(self, *a: object) -> None:
            return None

    holiday = MagicMock()
    holiday.get_active_window_for_date = AsyncMock(return_value=MagicMock())
    delivery = MagicMock()
    delivery.run = AsyncMock()

    with (
        patch("src.scheduler.AsyncSessionLocal", return_value=_Ctx()),
        patch("src.scheduler._active_profiles", AsyncMock(return_value=[profile])),
        patch("src.scheduler._profile_today", return_value=sunday),
        patch("src.scheduler.HolidayPauseService", return_value=holiday),
        patch("src.scheduler.WeeklyReviewDeliveryService", return_value=delivery),
    ):
        await run_weekly_review_delivery()

    holiday.get_active_window_for_date.assert_awaited_once_with(profile, sunday)
    delivery.run.assert_not_awaited()


@pytest.mark.asyncio
async def test_weekly_review_defers_to_the_in_flight_holder_without_failing() -> None:
    """Batch 232.1: losing the artifact lock is the designed outcome here.

    Decision #266 runs the Railway ``weekly-review`` cron *and* this in-process
    job on purpose, with the lock deciding which one pays. Treating the loser as
    a failure posts a failure turn into Mark's coach thread and alerts the
    operator about a review the winner is writing successfully.
    """

    profile = _profile()
    sunday = date(2026, 8, 2)
    session = AsyncMock()
    session.rollback = AsyncMock()

    class _Ctx:
        async def __aenter__(self) -> AsyncMock:
            return session

        async def __aexit__(self, *a: object) -> None:
            return None

    holiday = MagicMock()
    holiday.get_active_window_for_date = AsyncMock(return_value=None)
    delivery = MagicMock()
    delivery.run = AsyncMock(side_effect=GenerationRequestInProgress())
    delivery.record_failure = AsyncMock()
    nudge = MagicMock()
    nudge.notify_admin_generation_failure = AsyncMock(return_value=True)

    with (
        patch("src.scheduler.AsyncSessionLocal", return_value=_Ctx()),
        patch("src.scheduler._active_profiles", AsyncMock(return_value=[profile])),
        patch("src.scheduler._profile_today", return_value=sunday),
        patch("src.scheduler.HolidayPauseService", return_value=holiday),
        patch("src.scheduler.WeeklyReviewDeliveryService", return_value=delivery),
        patch("src.scheduler.NudgeAlertService", return_value=nudge),
    ):
        result = await run_weekly_review_delivery()

    delivery.record_failure.assert_not_awaited()
    nudge.notify_admin_generation_failure.assert_not_awaited()
    session.rollback.assert_awaited_once()
    assert result.counters["skipped_in_flight"] == 1
    assert result.counters["failed"] == 0


@pytest.mark.asyncio
async def test_weekly_review_failure_rolls_back_and_uses_admin_alert_path() -> None:
    profile = _profile()
    sunday = date(2026, 8, 2)
    session = AsyncMock()
    session.rollback = AsyncMock()

    class _Ctx:
        async def __aenter__(self) -> AsyncMock:
            return session

        async def __aexit__(self, *a: object) -> None:
            return None

    holiday = MagicMock()
    holiday.get_active_window_for_date = AsyncMock(return_value=None)
    delivery = MagicMock()
    delivery.run = AsyncMock(
        side_effect=AnthropicApiError("credits", reason="billing", status_code=400)
    )
    delivery.record_failure = AsyncMock(return_value=(MagicMock(), True))
    nudge = MagicMock()
    nudge.notify_admin_generation_failure = AsyncMock(return_value=True)

    with (
        patch("src.scheduler.AsyncSessionLocal", return_value=_Ctx()),
        patch("src.scheduler._active_profiles", AsyncMock(return_value=[profile])),
        patch("src.scheduler._profile_today", return_value=sunday),
        patch("src.scheduler.HolidayPauseService", return_value=holiday),
        patch("src.scheduler.WeeklyReviewDeliveryService", return_value=delivery),
        patch("src.scheduler.NudgeAlertService", return_value=nudge),
    ):
        await run_weekly_review_delivery()

    delivery.run.assert_awaited_once_with(profile, as_of=sunday, commit=True)
    session.rollback.assert_awaited_once()
    delivery.record_failure.assert_awaited_once_with(
        profile,
        subject_date=sunday,
        commit=False,
    )
    nudge.notify_admin_generation_failure.assert_awaited_once_with(
        reason="billing",
        subject_date=sunday,
        artifact="weekly_review",
        commit=False,
    )
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_state_change_coach_skips_holiday_before_candidate_generation() -> None:
    profile = _profile()
    subject_date = date(2026, 8, 5)
    session = AsyncMock()

    class _Ctx:
        async def __aenter__(self) -> AsyncMock:
            return session

        async def __aexit__(self, *a: object) -> None:
            return None

    holiday = MagicMock()
    holiday.get_active_window_for_date = AsyncMock(return_value=MagicMock())
    coach = MagicMock()
    coach.run = AsyncMock()

    with (
        patch("src.scheduler.AsyncSessionLocal", return_value=_Ctx()),
        patch("src.scheduler._active_profiles", AsyncMock(return_value=[profile])),
        patch("src.scheduler._profile_today", return_value=subject_date),
        patch("src.scheduler.HolidayPauseService", return_value=holiday),
        patch("src.scheduler.StateChangeCoachService", return_value=coach),
    ):
        result = await run_state_change_coach()

    holiday.get_active_window_for_date.assert_awaited_once_with(profile, subject_date)
    coach.run.assert_not_awaited()
    assert result.status == JobStatus.skipped
    assert result.reason == "holiday_away"
    assert result.counters["skipped_holiday"] == 1


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
            "connection_warmup",
            "daily_backup",
            # Batch 247.3 (DS237-04): Batch 196 built the drill and it had never
            # once been pointed at a real archive — zero job_runs rows ever.
            "backup_drill",
            # Batch 247.2 — registered from the first deploy, dry-run by default.
            "timeseries_retention",
            # Batch 249.4 (CI239-12) — retires proposals for dates already past.
            "proposal_expiry",
            "metric_baseline_refresh",
            "hive_temperature_poll",
            "wake_check",
            "morning_backstop",
            "garmin_activity_poll",
            "post_workout_backstop",
            "workout_autopush",
            "weekly_review_delivery",
            "state_change_coach",
            "longitudinal_analysis",
            "evening_sleep_nudge",
            "evening_monitoring_alerts",
            "fan_control",
            "egress_budget",
        }

        hive_job = scheduler.get_job("hive_temperature_poll")
        wake_job = scheduler.get_job("wake_check")
        backstop_job = scheduler.get_job("morning_backstop")
        garmin_job = scheduler.get_job("garmin_activity_poll")
        post_workout_backstop = scheduler.get_job("post_workout_backstop")
        autopush_job = scheduler.get_job("workout_autopush")
        nudge_job = scheduler.get_job("evening_sleep_nudge")
        weekly_review_job = scheduler.get_job("weekly_review_delivery")
        state_change_job = scheduler.get_job("state_change_coach")
        longitudinal_job = scheduler.get_job("longitudinal_analysis")
        monitoring_job = scheduler.get_job("evening_monitoring_alerts")
        assert hive_job is not None
        assert wake_job is not None
        assert backstop_job is not None
        assert garmin_job is not None
        assert post_workout_backstop is not None
        assert autopush_job is not None
        assert nudge_job is not None
        assert weekly_review_job is not None
        assert state_change_job is not None
        assert longitudinal_job is not None
        assert monitoring_job is not None
        assert str(hive_job.trigger) == "interval[0:15:00]"
        # The fixed 06:30 morning cron was replaced by a 15-min wake-check poll
        # plus an 11:00 backstop that still runs the (unchanged) morning sync
        # (moved later from 09:30 in Batch 138 / Decision #217).
        assert str(wake_job.trigger) == "interval[0:15:00]"
        assert "hour='11', minute='0'" in str(backstop_job.trigger)
        assert str(garmin_job.trigger) == "interval[1:00:00]"
        assert "hour='20', minute='30'" in str(post_workout_backstop.trigger)
        assert "hour='7,13,19', minute='0'" in str(autopush_job.trigger)
        assert "hour='20', minute='0'" in str(nudge_job.trigger)
        assert "day_of_week='sun', hour='18', minute='0'" in str(weekly_review_job.trigger)
        assert "hour='11', minute='45'" in str(state_change_job.trigger)
        assert "hour='12', minute='15'" in str(longitudinal_job.trigger)
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
        assert weekly_review_job.coalesce is True
        assert weekly_review_job.max_instances == 1
        assert state_change_job.coalesce is True
        assert state_change_job.max_instances == 1
        assert monitoring_job.max_instances == 1
        for job in jobs:
            if job.id == "connection_warmup":
                continue
            assert isinstance(job.func, partial)
            assert job.func.func is run_tracked_job
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)


# ---------------------------------------------------------------------------
# _sync_garmin_daily (Batch 18)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_garmin_daily_syncs_metrics_and_sleep() -> None:
    """Today plus D-1..D-3 are synced and counted for each active profile."""
    session = AsyncMock()
    profiles = [_profile(), _profile()]

    client = MagicMock()
    client.fetch_daily_payloads = MagicMock(return_value="payloads")

    sync_service = MagicMock()
    sync_service.sync_daily = AsyncMock(
        return_value=MagicMock(daily_metrics_synced=1, sleep_synced=1)
    )

    today = date(2026, 8, 2)
    with (
        patch("src.services.morning_pipeline.GarminSyncService", return_value=sync_service),
        patch("src.services.morning_pipeline.profile_today", return_value=today),
    ):
        daily, sleep, failures = await _sync_garmin_daily(session, profiles, client=client)

    assert (daily, sleep) == (8, 8)
    assert failures == 0
    assert client.fetch_daily_payloads.call_count == 8
    assert sync_service.sync_daily.await_count == 8
    expected_dates = [today - timedelta(days=offset) for offset in range(4)]
    for profile_index, profile in enumerate(profiles):
        profile_calls = sync_service.sync_daily.await_args_list[
            profile_index * 4 : (profile_index + 1) * 4
        ]
        assert [call.args[:2] for call in profile_calls] == [
            (profile.id, subject_date) for subject_date in expected_dates
        ]
    # Each date is committed independently after the service stages it.
    for call in sync_service.sync_daily.await_args_list:
        assert call.kwargs["commit"] is False
    assert session.commit.await_count == 8


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

    with (
        patch("src.services.morning_pipeline.GarminSyncService", return_value=sync_service),
        patch("src.services.morning_pipeline.profile_today", return_value=date(2026, 8, 2)),
    ):
        daily, sleep, failures = await _sync_garmin_daily(session, [bad, good], client=client)

    # The failing profile contributes nothing; the healthy one still syncs.
    assert (daily, sleep) == (4, 4)
    assert failures == 4
    assert session.rollback.await_count == 4
    assert sync_service.sync_daily.await_count == 8


@pytest.mark.asyncio
async def test_poisoned_garmin_step_recovers_session_for_verdict(
    db_conn: AsyncConnection,
) -> None:
    """A real PostgreSQL transaction abort is rolled back before downstream work."""

    profile = _profile()
    client = MagicMock()
    client.fetch_daily_payloads = MagicMock(return_value="payloads")
    calls = 0

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        sync_service = MagicMock()

        async def sync_daily(*_args: object, **_kwargs: object) -> MagicMock:
            nonlocal calls
            calls += 1
            if calls == 1:
                await session.execute(text("SELECT 1 / 0"))
            await session.execute(text("SELECT 1"))
            return MagicMock(daily_metrics_synced=1, sleep_synced=1)

        sync_service.sync_daily = AsyncMock(side_effect=sync_daily)
        with (
            patch("src.services.morning_pipeline.GarminSyncService", return_value=sync_service),
            patch("src.services.morning_pipeline.profile_today", return_value=date(2026, 8, 15)),
        ):
            daily, sleep, failures = await _sync_garmin_daily(session, [profile], client=client)

        assert (daily, sleep, failures) == (3, 3, 1)
        # This is the transaction state the morning-analysis query inherits.
        # Without the caught-step rollback it raises PendingRollbackError.
        assert await session.scalar(text("SELECT 1")) == 1


@pytest.mark.asyncio
async def test_sync_garmin_daily_no_profiles_skips_client() -> None:
    """With no active profiles the helper short-circuits without building a client."""
    session = AsyncMock()
    with patch("src.services.morning_pipeline.GarminConnectClient") as client_cls:
        result = await _sync_garmin_daily(session, [])
    assert result == (0, 0, 0)
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

    async def fake_daily_sync(
        _session: object, _profiles: object, **_k: object
    ) -> tuple[int, int, int]:
        calls.append("garmin_daily")
        return (1, 1, 0)

    analysis_service = MagicMock()

    async def generate(*_args: object, **_kwargs: object) -> MagicMock:
        calls.append("analysis")
        return MagicMock(generated=True)

    analysis_service.generate_and_store = AsyncMock(side_effect=generate)

    coaching_service = MagicMock()
    coaching_service.regenerate_for_verdict = AsyncMock(return_value=[])
    coaching_service.propose_chronic_deload = AsyncMock(return_value=[])
    nudge_service = MagicMock()
    nudge_service.push_brief_ready = AsyncMock(return_value=True)

    with (
        patch("src.scheduler.AsyncSessionLocal", return_value=_Ctx()),
        patch("src.services.morning_pipeline.OpenMeteoClient", return_value=meteo_client),
        patch("src.services.morning_pipeline.EnvironmentSyncService", return_value=weather_service),
        patch("src.services.morning_pipeline.sync_garmin_daily", side_effect=fake_daily_sync),
        patch(
            "src.services.morning_pipeline.morning_input_presence",
            AsyncMock(return_value=MorningInputPresence(daily_metrics=True, sleep=True)),
        ),
        patch(
            "src.services.morning_pipeline.MorningAnalysisService", return_value=analysis_service
        ),
        patch(
            "src.services.morning_pipeline.ExecutableCoachingService", return_value=coaching_service
        ),
        patch("src.services.morning_pipeline.NudgeAlertService", return_value=nudge_service),
    ):
        await run_morning_weather_sync()

    assert "garmin_daily" in calls
    assert "analysis" in calls
    assert calls.index("garmin_daily") < calls.index("analysis")
    # Batch 112: the freshly generated brief is pushed exactly once via the same
    # brief-ready notification the check-in path uses.
    assert nudge_service.push_brief_ready.await_count == 1
    assert coaching_service.propose_chronic_deload.await_count == 1


@pytest.mark.asyncio
async def test_poisoned_input_step_does_not_cost_verdict() -> None:
    """A degraded sibling step still reaches generation when wake inputs exist."""

    profile = _profile()
    session = AsyncMock()
    analysis = MagicMock()
    analysis_service = MagicMock()
    analysis_service.generate_and_store = AsyncMock(
        return_value=MagicMock(generated=True, analysis=analysis)
    )
    coaching_service = MagicMock()
    coaching_service.regenerate_for_verdict = AsyncMock(return_value=[])
    coaching_service.propose_chronic_deload = AsyncMock(return_value=[])
    nudge_service = MagicMock()
    nudge_service.push_brief_ready = AsyncMock(return_value=False)
    insights_service = MagicMock()
    insights_service.record_drivers = AsyncMock(return_value=MagicMock(record_count=0))

    with (
        patch("src.scheduler.AsyncSessionLocal", return_value=_morning_sync_ctx(session)),
        patch("src.scheduler._active_profiles", AsyncMock(return_value=[profile])),
        patch(
            "src.services.morning_pipeline.MorningBriefPipeline.sync_inputs",
            AsyncMock(return_value=MorningInputResult(failures=1)),
        ),
        patch(
            "src.services.morning_pipeline.morning_input_presence",
            AsyncMock(return_value=MorningInputPresence(daily_metrics=True, sleep=True)),
        ),
        patch(
            "src.services.morning_pipeline.MorningAnalysisService", return_value=analysis_service
        ),
        patch(
            "src.services.morning_pipeline.ExecutableCoachingService", return_value=coaching_service
        ),
        patch("src.services.morning_pipeline.NudgeAlertService", return_value=nudge_service),
        patch("src.services.morning_pipeline.InsightsService", return_value=insights_service),
        patch("src.services.morning_pipeline.pregenerate_brief_audio", AsyncMock()),
    ):
        result = await run_morning_weather_sync()

    analysis_service.generate_and_store.assert_awaited_once_with(
        profile, ANY, client=None, force=False, commit=True
    )
    assert result.status == JobStatus.degraded
    assert result.counters["analyses_generated"] == 1
    assert result.counters["failed"] == 1


@pytest.mark.asyncio
async def test_morning_backstop_holds_instead_of_generating_unsynced_read() -> None:
    profile = _profile()
    session = AsyncMock()
    analysis_service = MagicMock()
    analysis_service.generate_and_store = AsyncMock()

    with (
        patch("src.scheduler.AsyncSessionLocal", return_value=_morning_sync_ctx(session)),
        patch("src.scheduler._active_profiles", AsyncMock(return_value=[profile])),
        patch(
            "src.services.morning_pipeline.MorningBriefPipeline.sync_inputs",
            AsyncMock(return_value=MorningInputResult()),
        ),
        patch(
            "src.services.morning_pipeline.morning_input_presence",
            AsyncMock(return_value=MorningInputPresence(daily_metrics=False, sleep=False)),
        ),
        patch(
            "src.services.morning_pipeline.MorningAnalysisService", return_value=analysis_service
        ),
        patch("src.services.morning_pipeline.ExecutableCoachingService", return_value=MagicMock()),
        patch("src.services.morning_pipeline.NudgeAlertService", return_value=MagicMock()),
        patch("src.services.morning_pipeline.InsightsService", return_value=MagicMock()),
    ):
        result = await run_morning_weather_sync()

    analysis_service.generate_and_store.assert_not_awaited()
    assert result.status == JobStatus.degraded
    assert result.counters["inputs_not_ready"] == 1
    assert result.counters["analyses_generated"] == 0


def _morning_sync_ctx(session: AsyncMock) -> object:
    class _Ctx:
        async def __aenter__(self) -> AsyncMock:
            return session

        async def __aexit__(self, *a: object) -> None:
            return None

    return _Ctx()


@pytest.mark.asyncio
async def test_run_morning_sync_syncs_then_nudges() -> None:
    """Batch 85: the wake job pulls all inputs, then fires the good-morning nudge —
    so by tap-time the data is synced and the brief generates fast."""
    profile = _profile()
    calls: list[str] = []

    session = AsyncMock()
    session.commit = AsyncMock()

    async def fake_sync(*_args: object, **_kwargs: object) -> MorningInputResult:
        calls.append("sync")
        return MorningInputResult(weather_days=1, daily_metrics=1, sleep=1)

    morning = MagicMock()
    morning.latest_analysis = AsyncMock(return_value=None)  # no brief yet → nudge

    async def fake_nudge(_profile: object, *, subject_date: object, commit: bool = True) -> bool:
        calls.append("nudge")
        return True

    nudge_service = MagicMock()
    nudge_service.push_good_morning = AsyncMock(side_effect=fake_nudge)

    with (
        patch("src.scheduler.AsyncSessionLocal", return_value=_morning_sync_ctx(session)),
        patch("src.scheduler._active_profiles", AsyncMock(return_value=[profile])),
        patch(
            "src.services.morning_pipeline.MorningBriefPipeline.sync_inputs", side_effect=fake_sync
        ),
        patch("src.services.morning_pipeline.MorningAnalysisService", return_value=morning),
        patch("src.services.morning_pipeline.NudgeAlertService", return_value=nudge_service),
    ):
        await run_wake_nudge()

    assert calls == ["sync", "nudge"]  # sync strictly before the nudge
    nudge_service.push_good_morning.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_morning_sync_skips_nudge_when_brief_exists() -> None:
    """Once today's brief already exists (he checked in, or the backstop ran) the
    wake job still syncs but never nudges him to check in again."""
    profile = _profile()

    session = AsyncMock()
    session.commit = AsyncMock()

    fake_sync = AsyncMock(return_value=MorningInputResult(weather_days=1, daily_metrics=1, sleep=1))
    morning = MagicMock()
    morning.latest_analysis = AsyncMock(return_value=MagicMock())  # brief already there
    nudge_service = MagicMock()
    nudge_service.push_good_morning = AsyncMock(return_value=True)

    with (
        patch("src.scheduler.AsyncSessionLocal", return_value=_morning_sync_ctx(session)),
        patch("src.scheduler._active_profiles", AsyncMock(return_value=[profile])),
        patch("src.services.morning_pipeline.MorningBriefPipeline.sync_inputs", fake_sync),
        patch("src.services.morning_pipeline.MorningAnalysisService", return_value=morning),
        patch("src.services.morning_pipeline.NudgeAlertService", return_value=nudge_service),
    ):
        await run_wake_nudge()

    fake_sync.assert_awaited_once()  # inputs still synced
    nudge_service.push_good_morning.assert_not_awaited()  # but no redundant nudge


@pytest.mark.asyncio
async def test_activity_poll_syncs_then_nudges_without_generating() -> None:
    """The primary poll stops at sync -> check-in nudge for every workout kind."""
    profile = _profile()

    session = AsyncMock()
    profile_rows = MagicMock()
    profile_rows.scalars.return_value.all.return_value = [profile]
    analysis_rows = MagicMock()
    analysis_rows.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(side_effect=[profile_rows, analysis_rows])

    class _Ctx:
        async def __aenter__(self) -> AsyncMock:
            return session

        async def __aexit__(self, *a: object) -> None:
            return None

    client = MagicMock()
    client.fetch_activity_payloads = MagicMock(return_value=[])
    sync_service = MagicMock()
    sync_service.sync_activities = AsyncMock(
        return_value=MagicMock(activities_synced=0, timeseries_samples_synced=0)
    )

    def _service(pending_method: str) -> MagicMock:
        svc = MagicMock()
        activity = MagicMock()
        activity.id = uuid.uuid4()
        activity.start_utc = datetime(2026, 7, 11, 12, 0)
        setattr(svc, pending_method, AsyncMock(return_value=[activity]))
        return svc

    ride = _service("pending_ride_activities")
    flex = _service("pending_flexibility_activities")
    strength = _service("pending_strength_activities")
    walk = _service("pending_walk_activities")

    nudge_service = MagicMock()
    nudge_service.push_workout_checkin = AsyncMock(return_value=True)

    from src.scheduler import run_garmin_activity_poll

    with (
        patch("src.scheduler.AsyncSessionLocal", return_value=_Ctx()),
        patch("src.scheduler.GarminConnectClient", return_value=client),
        patch("src.scheduler.GarminSyncService", return_value=sync_service),
        patch("src.scheduler.PostWorkoutAnalysisService", return_value=ride),
        patch("src.scheduler.PostFlexibilityAnalysisService", return_value=flex),
        patch("src.scheduler.PostStrengthAnalysisService", return_value=strength),
        patch("src.scheduler.PostWalkAnalysisService", return_value=walk),
        patch("src.scheduler.NudgeAlertService", return_value=nudge_service),
    ):
        await run_garmin_activity_poll()

    assert nudge_service.push_workout_checkin.await_count == 4
    kinds = {call.kwargs["kind"] for call in nudge_service.push_workout_checkin.await_args_list}
    assert kinds == {"ride", "flexibility", "strength", "walk"}
    for service, generate_method in (
        (ride, "generate_for_pending_rides"),
        (flex, "generate_for_pending_flexibility"),
        (strength, "generate_for_pending_strength"),
        (walk, "generate_for_pending_walks"),
    ):
        assert not getattr(service, generate_method).called


@pytest.mark.asyncio
async def test_post_workout_backstop_generates_and_pushes_all_unread_kinds() -> None:
    profile = _profile()
    session = AsyncMock()
    rows = MagicMock()
    rows.scalars.return_value.all.return_value = [profile]
    session.execute = AsyncMock(return_value=rows)

    class _Ctx:
        async def __aenter__(self) -> AsyncMock:
            return session

        async def __aexit__(self, *a: object) -> None:
            return None

    def _service(method: str) -> MagicMock:
        service = MagicMock()
        result = MagicMock(generated=True, analysis=MagicMock(activity_id=uuid.uuid4()))
        setattr(service, method, AsyncMock(return_value=[result]))
        return service

    ride = _service("generate_for_pending_rides")
    flex = _service("generate_for_pending_flexibility")
    strength = _service("generate_for_pending_strength")
    walk = _service("generate_for_pending_walks")
    nudge = MagicMock()
    nudge.push_workout_analysis = AsyncMock(return_value=True)

    with (
        patch("src.scheduler.AsyncSessionLocal", return_value=_Ctx()),
        patch("src.scheduler.PostWorkoutAnalysisService", return_value=ride),
        patch("src.scheduler.PostFlexibilityAnalysisService", return_value=flex),
        patch("src.scheduler.PostStrengthAnalysisService", return_value=strength),
        patch("src.scheduler.PostWalkAnalysisService", return_value=walk),
        patch("src.scheduler.NudgeAlertService", return_value=nudge),
    ):
        await run_post_workout_backstop()

    assert nudge.push_workout_analysis.await_count == 4
    assert {call.kwargs["kind"] for call in nudge.push_workout_analysis.await_args_list} == {
        "ride",
        "flexibility",
        "strength",
        "walk",
    }


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
    inputs: MorningInputPresence | None = None,
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

    fake_client = client if client is not None else _FakeGarmin({})
    input_presence = AsyncMock(
        return_value=inputs or MorningInputPresence(daily_metrics=False, sleep=False)
    )
    record = AsyncMock()
    last_seen = AsyncMock(return_value=None)
    is_ready = MagicMock(return_value=decision or WakeDecision("wait", None, "awaiting_stability"))
    morning_sync = AsyncMock(return_value=JobResult.succeeded())

    with ExitStack() as stack:
        enter = stack.enter_context
        enter(patch("src.scheduler.AsyncSessionLocal", return_value=_Ctx()))
        enter(patch("src.scheduler._active_profiles", AsyncMock(return_value=profiles)))
        enter(patch("src.scheduler.morning_input_presence", input_presence))
        enter(patch("src.scheduler._profile_now", lambda profile: now))
        enter(patch("src.scheduler.GarminConnectClient", return_value=fake_client))
        enter(patch("src.scheduler._last_seen_sleep_end", last_seen))
        enter(patch("src.scheduler.is_morning_ready", is_ready))
        enter(patch("src.scheduler._record_wake_check", record))
        enter(patch("src.scheduler.run_wake_nudge", morning_sync))
        yield SimpleNamespace(
            session=session,
            input_presence=input_presence,
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
    # The job feeds is_morning_ready London-local now + the 11:00 backstop + floors.
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
async def test_wake_check_short_circuits_when_inputs_are_present() -> None:
    """Today's synced daily/sleep rows stop polling without consulting an analysis."""
    with _wake_patches(
        profiles=[_profile()],
        now=_local(8, 25),
        inputs=MorningInputPresence(daily_metrics=True, sleep=True),
        client=_FakeGarmin(None, raise_on_fetch=True),
    ) as m:
        await run_wake_check()

    assert m.client.calls == 0
    m.is_ready.assert_not_called()
    m.record.assert_not_awaited()
    m.morning_sync.assert_not_awaited()


@pytest.mark.asyncio
async def test_wake_check_keeps_polling_for_lagging_sleep_before_backstop() -> None:
    decision = WakeDecision("fire", _SLEEP_END, "stable_wake")
    with _wake_patches(
        profiles=[_profile()],
        now=_local(8, 25),
        inputs=MorningInputPresence(daily_metrics=True, sleep=False),
        decision=decision,
    ) as m:
        await run_wake_check()

    assert m.client.calls == 1
    m.morning_sync.assert_awaited_once()


@pytest.mark.asyncio
async def test_wake_check_accepts_synced_no_sleep_day_after_backstop() -> None:
    with _wake_patches(
        profiles=[_profile()],
        now=_local(11, 5),
        inputs=MorningInputPresence(daily_metrics=True, sleep=False),
        client=_FakeGarmin(None, raise_on_fetch=True),
    ) as m:
        await run_wake_check()

    assert m.client.calls == 0
    m.record.assert_not_awaited()
    m.morning_sync.assert_not_awaited()


@pytest.mark.asyncio
async def test_wake_check_outside_window_skips_poll() -> None:
    """Before the morning window: not even a cheap input-presence lookup."""
    with _wake_patches(
        profiles=[_profile()],
        now=_local(2, 0),
        client=_FakeGarmin(None, raise_on_fetch=True),
    ) as m:
        await run_wake_check()

    m.input_presence.assert_not_awaited()
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
    morning_sync = AsyncMock(return_value=JobResult.succeeded())
    now = {"value": _local(8, 5)}  # 07:05 UTC → not yet settled

    with (
        patch("src.scheduler.AsyncSessionLocal", new=_bind(db_conn)),
        patch("src.scheduler.GarminConnectClient", return_value=client),
        patch("src.scheduler._profile_now", lambda profile: now["value"]),
        patch("src.scheduler.run_wake_nudge", morning_sync),
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
    """Past 11:00 with no finalized session → fire on whatever exists."""
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    client = _FakeGarmin({})  # no dailySleepDTO → unfinalized
    morning_sync = AsyncMock(return_value=JobResult.succeeded())

    with (
        patch("src.scheduler.AsyncSessionLocal", new=_bind(db_conn)),
        patch("src.scheduler.GarminConnectClient", return_value=client),
        patch("src.scheduler._profile_now", lambda profile: _local(11, 5)),
        patch("src.scheduler.run_wake_nudge", morning_sync),
    ):
        await run_wake_check()

    morning_sync.assert_awaited_once()
    row = await _wake_check_row(db_conn, user_id)
    assert row is not None
    assert row.verdict == "fire"
    assert row.context_packet["reason"] == "backstop"
    assert row.context_packet["sleepEndUtc"] is None


@pytest.mark.asyncio
async def test_wake_check_existing_empty_read_cannot_cancel_later_sync(
    db_conn: AsyncConnection,
) -> None:
    """Pin the real 07:19 poll → 07:26 empty read → 07:34 fire ordering."""
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    client = _FakeGarmin(_sleep_payload(sleep_end="2026-06-24T07:12:15"))
    morning_sync = AsyncMock(return_value=JobResult.succeeded())
    now = {
        "value": datetime(2026, 6, 24, 8, 19, 41, tzinfo=LONDON),
    }

    with (
        patch("src.scheduler.AsyncSessionLocal", new=_bind(db_conn)),
        patch("src.scheduler.GarminConnectClient", return_value=client),
        patch("src.scheduler._profile_now", lambda profile: now["value"]),
        patch("src.scheduler.run_wake_nudge", morning_sync),
    ):
        await run_wake_check()  # 07:19:41 UTC: first sighting, wait and persist.

        # 07:26:55 UTC: the pre-fix check-in path wrote an empty morning read.
        # It is history, not proof that Garmin inputs have synced.
        async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
            session.add(
                Analysis(
                    user_id=user_id,
                    analysis_type="morning",
                    subject_date=date(2026, 6, 24),
                    generated_at_utc=datetime(2026, 6, 24, 7, 27, 47),
                    prompt_version="morning-empty",
                    verdict="Green",
                    context_packet={"sleep": None, "dailyMetrics": None},
                    output_markdown="No overnight data.",
                    raw_response={},
                )
            )
            await session.commit()

        now["value"] = datetime(2026, 6, 24, 8, 34, 39, tzinfo=LONDON)
        await run_wake_check()  # stable and settled: must still fire the sync.

    row = await _wake_check_row(db_conn, user_id)
    assert row is not None
    assert row.verdict == "fire"
    assert row.context_packet["reason"] == "stable_wake"
    assert client.calls == 2
    morning_sync.assert_awaited_once()


@pytest.mark.asyncio
async def test_wake_check_short_circuits_with_synced_inputs(
    db_conn: AsyncConnection,
) -> None:
    """Real current-day morning metrics + sleep stop the poll cold."""
    user_id = uuid.uuid4()
    await _seed_profile(db_conn, user_id)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add_all(
            [
                DailyMetric(
                    user_id=user_id,
                    calendar_date=date(2026, 6, 24),
                    phase=DAILY_METRIC_PHASE_MORNING,
                    raw_payload={},
                ),
                Sleep(
                    user_id=user_id,
                    calendar_date=date(2026, 6, 24),
                    duration_sec=7 * 3600,
                    raw_payload={},
                ),
            ]
        )
        await session.commit()

    client = _FakeGarmin(None, raise_on_fetch=True)
    morning_sync = AsyncMock(return_value=JobResult.succeeded())
    with (
        patch("src.scheduler.AsyncSessionLocal", new=_bind(db_conn)),
        patch("src.scheduler.GarminConnectClient", return_value=client),
        patch("src.scheduler._profile_now", lambda profile: _local(8, 25)),
        patch("src.scheduler.run_wake_nudge", morning_sync),
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


# ---------------------------------------------------------------------------
# run_fan_control persistence (Batch 31) — one tick per within-window fire
# ---------------------------------------------------------------------------


class _FakeFanClient:
    """Stand-in for DreoFanClient; records commands and can fail on connect."""

    def __init__(
        self,
        *,
        is_on: bool = False,
        fan_speed: int | None = None,
        connect_error: Exception | None = None,
    ) -> None:
        self._state = DreoFanState(is_on=is_on, fan_speed=fan_speed)
        self._connect_error = connect_error
        self.connected = False
        self.commands: list[tuple] = []

    def connect(self) -> None:
        self.connected = True
        if self._connect_error is not None:
            raise self._connect_error

    def read_state(self) -> DreoFanState:
        return self._state

    def power(self, on: bool) -> None:
        self.commands.append(("power", on))

    def set_speed(self, speed: int) -> None:
        self.commands.append(("set_speed", speed))

    def close(self) -> None:
        pass


async def _seed_fan_profile(
    db_conn: AsyncConnection, user_id: uuid.UUID, *, auto_enabled: bool = True
) -> None:
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add(
            Profile(
                id=user_id,
                display_name="Fan Loop Test",
                role=UserRole.admin,
                timezone="Europe/London",
                is_active=True,
                fan_auto_enabled=auto_enabled,
            )
        )
        await session.commit()


async def _fan_rows(db_conn: AsyncConnection, user_id: uuid.UUID) -> list[FanStateReading]:
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        return list(
            (
                await session.execute(
                    select(FanStateReading)
                    .where(FanStateReading.user_id == user_id)
                    .order_by(FanStateReading.captured_at_utc)
                )
            )
            .scalars()
            .all()
        )


@contextmanager
def _fan_patches(
    db_conn: AsyncConnection,
    *,
    now_local: datetime,
    temperature_c: float | None,
    fan: _FakeFanClient,
):
    with ExitStack() as stack:
        stack.enter_context(patch("src.scheduler._fan_control_configured", lambda: True))
        stack.enter_context(patch("src.scheduler.AsyncSessionLocal", new=_bind(db_conn)))
        stack.enter_context(patch("src.scheduler._profile_now", lambda profile: now_local))
        stack.enter_context(
            patch("src.scheduler._fresh_temperature_c", lambda reading, now: temperature_c)
        )
        stack.enter_context(patch("src.scheduler.DreoFanClient", lambda: fan))
        yield


@pytest.mark.asyncio
async def test_fan_control_records_apply_tick(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    await _seed_fan_profile(db_conn, user_id)
    fan = _FakeFanClient(is_on=False)
    with _fan_patches(db_conn, now_local=_local(23, 0), temperature_c=20.0, fan=fan):
        await run_fan_control()

    rows = await _fan_rows(db_conn, user_id)
    assert len(rows) == 1
    row = rows[0]
    assert row.action == "apply"
    assert row.phase == "control"
    assert row.auto_enabled is True
    assert row.observed_temp_c == 20.0
    assert row.fan_on is True
    assert row.fan_speed == 5  # 20.0 °C → ladder speed 5
    assert ("power", True) in fan.commands
    assert ("set_speed", 5) in fan.commands


@pytest.mark.asyncio
async def test_fan_control_records_hold_tick(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    await _seed_fan_profile(db_conn, user_id)
    fan = _FakeFanClient(is_on=True, fan_speed=3)  # already at the 19.6 °C target
    with _fan_patches(db_conn, now_local=_local(23, 0), temperature_c=19.6, fan=fan):
        await run_fan_control()

    rows = await _fan_rows(db_conn, user_id)
    assert len(rows) == 1
    assert rows[0].action == "hold"
    assert rows[0].fan_on is True
    assert rows[0].fan_speed == 3
    assert fan.commands == []  # nothing issued when already at target


@pytest.mark.asyncio
async def test_fan_control_records_no_data_tick(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    await _seed_fan_profile(db_conn, user_id)
    fan = _FakeFanClient(is_on=False)
    with _fan_patches(db_conn, now_local=_local(23, 0), temperature_c=None, fan=fan):
        await run_fan_control()

    rows = await _fan_rows(db_conn, user_id)
    assert len(rows) == 1
    assert rows[0].action == "no_data"
    assert rows[0].observed_temp_c is None
    assert fan.commands == []  # never actuate blind


@pytest.mark.asyncio
async def test_fan_control_records_auto_off_tick_without_cloud(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    await _seed_fan_profile(db_conn, user_id, auto_enabled=False)
    fan = _FakeFanClient(is_on=True, fan_speed=5)
    with _fan_patches(db_conn, now_local=_local(23, 0), temperature_c=21.0, fan=fan):
        await run_fan_control()

    rows = await _fan_rows(db_conn, user_id)
    assert len(rows) == 1
    assert rows[0].action == "auto_off"
    assert rows[0].auto_enabled is False
    assert rows[0].fan_on is None
    assert fan.connected is False  # manual control never touches the cloud


@pytest.mark.asyncio
async def test_fan_control_records_unreachable_tick(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    await _seed_fan_profile(db_conn, user_id)
    fan = _FakeFanClient(connect_error=DreoFanError("transport not ready"))
    with _fan_patches(db_conn, now_local=_local(23, 0), temperature_c=20.0, fan=fan):
        await run_fan_control()

    rows = await _fan_rows(db_conn, user_id)
    assert len(rows) == 1
    assert rows[0].action == "unreachable"
    assert rows[0].fan_on is None
    assert rows[0].observed_temp_c == 20.0
    assert rows[0].reason == "cloud unreachable"  # secret-safe, no exception text


@pytest.mark.asyncio
async def test_fan_control_records_winddown_tick(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    await _seed_fan_profile(db_conn, user_id)
    fan = _FakeFanClient(is_on=True, fan_speed=5)
    with _fan_patches(db_conn, now_local=_local(8, 45), temperature_c=None, fan=fan):
        await run_fan_control()

    rows = await _fan_rows(db_conn, user_id)
    assert len(rows) == 1
    assert rows[0].action == "winddown"
    assert rows[0].phase == "winddown"
    assert rows[0].fan_on is False  # reconciled off for the morning
    assert ("power", False) in fan.commands


@pytest.mark.asyncio
async def test_fan_control_idle_writes_no_tick(db_conn: AsyncConnection) -> None:
    user_id = uuid.uuid4()
    await _seed_fan_profile(db_conn, user_id)
    fan = _FakeFanClient(is_on=False)
    with _fan_patches(db_conn, now_local=_local(14, 0), temperature_c=20.0, fan=fan):
        await run_fan_control()

    assert await _fan_rows(db_conn, user_id) == []
    assert fan.connected is False  # daytime is a true no-op


@pytest.mark.asyncio
async def test_fan_control_is_idempotent_on_coalesced_double_fire(
    db_conn: AsyncConnection,
) -> None:
    user_id = uuid.uuid4()
    await _seed_fan_profile(db_conn, user_id)
    fan = _FakeFanClient(is_on=False)
    with _fan_patches(db_conn, now_local=_local(23, 0), temperature_c=20.0, fan=fan):
        await run_fan_control()
        await run_fan_control()

    # Both fires land in the same 15-min slot → one upserted row, not two.
    assert len(await _fan_rows(db_conn, user_id)) == 1


# ---------------------------------------------------------------------------
# Batch 242 / CR236-01 — the error handlers must survive their own rollback
#
# These are isolation tests, not ordering tests. They use a real AsyncSession
# and real ``Profile`` rows because the defect lives in what SQLAlchemy does to
# the identity map on rollback, which an ``AsyncMock`` session and a
# ``MagicMock`` profile are structurally incapable of showing (CR236-03).
#
# ``join_transaction_mode="create_savepoint"`` is load-bearing. The session's
# own transaction stays top-level, so ``rollback()`` still expires the whole
# identity map and the defect reproduces exactly as in production — but the
# rollback unwinds to a savepoint, so the seeded row and the ``db_conn``
# fixture's ``SET search_path`` both survive it. Without it the code under test
# discards the very rows the test seeded, and the test would be exercising a
# state production can never be in.
# ---------------------------------------------------------------------------


def _job_session(db_conn: AsyncConnection) -> AsyncSession:
    return AsyncSession(
        bind=db_conn,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )


async def _seed_active_profile(db_conn: AsyncConnection, name: str) -> uuid.UUID:
    user_id = uuid.uuid4()
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add(
            Profile(
                id=user_id,
                display_name=name,
                role=UserRole.admin,
                timezone="Europe/London",
                is_active=True,
            )
        )
        await session.commit()
    return user_id


@pytest.mark.asyncio
async def test_rollback_expires_a_loaded_profile_and_restore_reloads_it(
    db_conn: AsyncConnection,
) -> None:
    """The premise, pinned: rollback expires everything, including the PK.

    If SQLAlchemy ever stops expiring untouched instances on a top-level
    rollback, this fails and the hoists below become dead weight — which is
    worth being told about rather than discovering by archaeology.
    """
    await _seed_active_profile(db_conn, "Expiry Premise")

    async with _job_session(db_conn) as session:
        profiles = await _active_profiles(session)
        profile = profiles[0]
        assert not inspect(profile).expired

        await session.rollback()

        # Untouched, never modified, and the primary key is not exempt.
        assert inspect(profile).expired
        assert "id" in inspect(profile).unloaded
        with pytest.raises(MissingGreenlet):
            str(profile.id)

        await _restore_after_rollback(session, profile)
        assert not inspect(profile).expired
        assert str(profile.id)
        assert profile.timezone == "Europe/London"


@pytest.mark.asyncio
async def test_weekly_review_in_flight_overlap_is_skipped_not_failed(
    db_conn: AsyncConnection,
) -> None:
    """Decision #266's designed cron overlap is a skip, not an outage.

    Before the Batch 242 hoist, ``str(profile.id)`` in this handler raised
    ``MissingGreenlet`` past the sibling ``except Exception``, escaped the
    profile loop, and the job's outer handler reported
    ``failed("weekly_review_failed")`` — the designed outcome recorded as an
    outage, with ``run_scheduled.py`` exiting 1.
    """
    await _seed_active_profile(db_conn, "Overlap Skip")

    service = MagicMock()
    service.run = AsyncMock(side_effect=GenerationRequestInProgress())
    service.record_failure = AsyncMock()
    holiday = MagicMock()
    holiday.get_active_window_for_date = AsyncMock(return_value=None)

    async with _job_session(db_conn) as session:
        with (
            patch("src.scheduler.AsyncSessionLocal", return_value=_session_ctx(session)),
            patch("src.scheduler.WeeklyReviewDeliveryService", return_value=service),
            patch("src.scheduler.HolidayPauseService", return_value=holiday),
        ):
            result = await run_weekly_review_delivery()

    assert result.status is not JobStatus.failed
    assert result.counters["skipped_in_flight"] == 1
    assert result.counters["failed"] == 0
    # The designed skip must never be recorded as a failed generation.
    service.record_failure.assert_not_awaited()


@pytest.mark.asyncio
async def test_weekly_review_failure_reaches_record_failure_and_the_operator_alert(
    db_conn: AsyncConnection,
) -> None:
    """An ordinary generation failure must still reach the failure turn and the alert.

    This is the half CR236-01 broke silently: the handler raised on
    ``str(profile.id)`` *before* ``record_failure`` and
    ``notify_admin_generation_failure`` on the lines below it, so Mark got no
    failure turn and no operator signal was ever emitted. Both callees take the
    live ``Profile``, so this also proves the instance is usable again — a mock
    that never touched it would pass whether or not the restore worked.
    """
    user_id = await _seed_active_profile(db_conn, "Alert Reaches Human")

    seen: dict[str, object] = {}

    async def _record_failure(profile: Profile, **kwargs: object) -> tuple[object, bool]:
        # Reading the instance here is the assertion: before the fix this line
        # raises MissingGreenlet from inside the handler.
        seen["record_failure_profile_id"] = profile.id
        return (MagicMock(), True)

    async def _notify(**kwargs: object) -> bool:
        seen["alert_reason"] = kwargs.get("reason")
        seen["alert_artifact"] = kwargs.get("artifact")
        return True

    service = MagicMock()
    service.run = AsyncMock(
        side_effect=AnthropicApiError("boom", reason="timeout", status_code=504)
    )
    service.record_failure = AsyncMock(side_effect=_record_failure)
    nudges = MagicMock()
    nudges.notify_admin_generation_failure = AsyncMock(side_effect=_notify)
    holiday = MagicMock()
    holiday.get_active_window_for_date = AsyncMock(return_value=None)

    async with _job_session(db_conn) as session:
        with (
            patch("src.scheduler.AsyncSessionLocal", return_value=_session_ctx(session)),
            patch("src.scheduler.WeeklyReviewDeliveryService", return_value=service),
            patch("src.scheduler.NudgeAlertService", return_value=nudges),
            patch("src.scheduler.HolidayPauseService", return_value=holiday),
        ):
            result = await run_weekly_review_delivery()

    assert result.counters["failed"] == 1
    service.record_failure.assert_awaited_once()
    nudges.notify_admin_generation_failure.assert_awaited_once()
    assert seen["record_failure_profile_id"] == user_id
    assert seen["alert_reason"] == "timeout"
    assert seen["alert_artifact"] == "weekly_review"


@pytest.mark.asyncio
async def test_profile_loop_survives_a_sibling_iteration_rollback(
    db_conn: AsyncConnection,
) -> None:
    """One profile's failure must not expire the instance the next one needs.

    The intra-handler hoist alone does not cover this: iteration N+1 reads
    ``profile.timezone`` through ``_profile_today`` *before* its own ``try``,
    so with a shared session the rollback in iteration N takes the next
    iteration down outside any handler at all.
    """
    await _seed_active_profile(db_conn, "Sibling A")
    await _seed_active_profile(db_conn, "Sibling B")

    handled: list[uuid.UUID] = []

    async def _run(profile: Profile, **kwargs: object) -> object:
        handled.append(profile.id)
        if len(handled) == 1:
            raise AnthropicApiError("first profile fails", reason="other", status_code=500)
        return SimpleNamespace(generated=1, message_created=1, push_recorded=1)

    service = MagicMock()
    service.run = AsyncMock(side_effect=_run)
    service.record_failure = AsyncMock(return_value=(MagicMock(), True))
    nudges = MagicMock()
    nudges.notify_admin_generation_failure = AsyncMock(return_value=True)
    holiday = MagicMock()
    holiday.get_active_window_for_date = AsyncMock(return_value=None)

    async with _job_session(db_conn) as session:
        with (
            patch("src.scheduler.AsyncSessionLocal", return_value=_session_ctx(session)),
            patch("src.scheduler.WeeklyReviewDeliveryService", return_value=service),
            patch("src.scheduler.NudgeAlertService", return_value=nudges),
            patch("src.scheduler.HolidayPauseService", return_value=holiday),
        ):
            result = await run_weekly_review_delivery()

    # Both profiles were attempted, and the job did not abort at the first one.
    assert len(handled) == 2
    assert result.status is not JobStatus.failed
    assert result.counters["failed"] == 1
    assert result.counters["generated"] == 1


# ---------------------------------------------------------------------------
# Batch 247 — the runway: storage measured, and the meter says what it measures
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_storage_threshold_alerts_when_the_database_crosses_it() -> None:
    """DS237-02: the database was at ~90% of a 500 MB cap, watched by nothing.

    Egress got a meter after its incident. Storage had *also* already caused one
    — DECISIONS #93 records the 2026-06-28 backfill filling the physical disk,
    at which point `VACUUM FULL` could not run because there was no room to
    write the compacted copy — and got nothing.
    """
    from src.services.egress_budget import STORAGE_BUDGET_BYTES

    session = _egress_session(database_bytes=int(STORAGE_BUDGET_BYTES * 0.91))
    logger = MagicMock()

    with (
        patch("src.scheduler.response_byte_counter") as counter,
        patch("src.scheduler.latest_backup", return_value=None),
        patch("src.scheduler.AsyncSessionLocal", return_value=_session_ctx(session)),
        patch("src.scheduler.log", logger),
    ):
        counter.drain.return_value = 0
        result = await run_egress_budget_check()

    assert result.status == JobStatus.degraded
    assert result.reason == "egress_budget_storage_critical"
    assert result.counters["storage_stage_ordinal"] == 2
    logger.error.assert_called_once()
    kwargs = logger.error.call_args.kwargs
    assert kwargs["kind"] == "database_storage_critical"
    # The trap travels with the alert rather than living in a runbook: near a
    # full disk, VACUUM FULL / CLUSTER / CTAS all need the new copy's size free.
    assert "dump/truncate/reload" in kwargs["remediation"]


@pytest.mark.asyncio
async def test_a_storage_alert_is_not_repeated_within_the_day() -> None:
    from src.services.egress_budget import STORAGE_BUDGET_BYTES

    session = _egress_session(
        [{"response_bytes_delta": 0, "storage_stage_ordinal": 2}],
        database_bytes=int(STORAGE_BUDGET_BYTES * 0.91),
    )
    logger = MagicMock()

    with (
        patch("src.scheduler.response_byte_counter") as counter,
        patch("src.scheduler.latest_backup", return_value=None),
        patch("src.scheduler.AsyncSessionLocal", return_value=_session_ctx(session)),
        patch("src.scheduler.log", logger),
    ):
        counter.drain.return_value = 0
        result = await run_egress_budget_check()

    assert result.status == JobStatus.degraded
    logger.error.assert_not_called()


@pytest.mark.asyncio
async def test_a_steady_daily_rate_over_the_monthly_cap_no_longer_reads_ok() -> None:
    """DS237-03 Defect C: a daily total was compared against a monthly cap.

    Warning fired at 2.75 GB *in a single day*, while a steady 200 MB/day — 6 GB
    a month, over the cap — scored 0.036 and read `ok` for ever. Month-to-date is
    what the cap is about, so month-to-date is what is compared.
    """
    from src.services.egress_budget import BUDGET_BYTES

    daily = 200_000_000
    # Fifteen prior days at 200 MB is 3 GB — over half the monthly cap, and under
    # a fiftieth of it on any single day.
    prior = [{"http_response_bytes_delta": daily} for _ in range(15)]
    session = _egress_session(prior, database_bytes=100_000_000)

    with (
        patch("src.scheduler.response_byte_counter") as counter,
        patch("src.scheduler.latest_backup", return_value=None),
        patch("src.scheduler.AsyncSessionLocal", return_value=_session_ctx(session)),
    ):
        counter.drain.return_value = 0
        result = await run_egress_budget_check()

    assert result.counters["http_response_bytes_month"] == 15 * daily
    assert result.counters["http_response_bytes_month"] > BUDGET_BYTES * 0.5
    assert result.status == JobStatus.degraded
    assert result.reason == "egress_budget_warning"


@pytest.mark.asyncio
async def test_the_drill_skips_honestly_when_it_is_not_configured() -> None:
    """DS237-04: registered weekly, but `BACKUP_RESTORE_DATABASE_URL` is unset.

    Failing every week would be a standing false alarm that teaches the operator
    to ignore this job. But it must not read as healthy either — "configured but
    inert" is the exact shape DS237-01 found everywhere — so it skips and says
    plainly, every pass, that no backup has ever been proved restorable.
    """
    logger = MagicMock()
    restore = AsyncMock()

    with (
        patch.object(settings, "backup_restore_database_url", ""),
        patch("src.scheduler.restore_latest_backup", restore),
        patch("src.scheduler.log", logger),
    ):
        result = await run_backup_restore_drill()

    assert result.status is JobStatus.skipped
    assert result.reason == "not_configured"
    # A skip must not exit non-zero — that is what makes it a false alarm.
    assert result.exit_code == 0
    restore.assert_not_awaited()
    logger.warning.assert_called_once()
    assert "restorable" in logger.warning.call_args.kwargs["consequence"]


@pytest.mark.asyncio
async def test_retention_ships_registered_and_dry_run() -> None:
    """Batch 247.2: the job runs from the first deploy and deletes nothing.

    This is the shape the group's hard stop requires — build it, test it, watch
    it report against production, and make the first real execution an explicit
    decision with a row count attached rather than a side effect of a deploy.
    """
    session = AsyncMock()
    scheduler = create_scheduler()
    assert scheduler.get_job("timeseries_retention") is not None
    assert settings.activity_timeseries_retention_enabled is False

    purge = AsyncMock(
        return_value=SimpleNamespace(
            expired_rows=466_449, expired_activities=552, deleted_rows=0, dry_run=True
        )
    )
    with (
        patch("src.scheduler.AsyncSessionLocal", return_value=_session_ctx(session)),
        patch("src.scheduler.purge_expired_timeseries", purge),
    ):
        result = await run_activity_timeseries_retention()

    assert result.status is JobStatus.skipped
    assert result.reason == "dry_run"
    assert result.counters["expired_rows"] == 466_449
    assert result.counters["deleted_rows"] == 0
    # The default must reach the service, not merely exist in config.
    assert purge.await_args.kwargs["dry_run"] is True


@pytest.mark.asyncio
async def test_retention_deletes_only_when_deliberately_enabled() -> None:
    session = AsyncMock()
    purge = AsyncMock(
        return_value=SimpleNamespace(
            expired_rows=466_449, expired_activities=552, deleted_rows=466_449, dry_run=False
        )
    )
    with (
        patch.object(settings, "activity_timeseries_retention_enabled", True),
        patch("src.scheduler.AsyncSessionLocal", return_value=_session_ctx(session)),
        patch("src.scheduler.purge_expired_timeseries", purge),
    ):
        result = await run_activity_timeseries_retention()

    assert result.status is JobStatus.succeeded
    assert result.counters["deleted_rows"] == 466_449
    assert purge.await_args.kwargs["dry_run"] is False
