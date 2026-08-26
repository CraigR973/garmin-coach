"""Batch 228 — the nightly ``metric_baselines`` refresh and its staleness detector.

Before this batch nothing in the system refreshed a personal baseline:
``MetricBaselineBackfillService.rebuild`` was reachable only from the manual
``src/metric_baselines_backfill`` admin runner. ``metric_baselines.created_at``
in production records every refresh that has ever happened — 2026-06-24,
2026-07-05, 2026-08-20, 2026-08-26 — each one a side effect of a human adding a
*new* metric, with a longest gap of 46 days.

Covered here: the job's counters and skip/degrade contract; the three-place
registration that 228.3 exists to protect; the 02:30 Europe/London slot and the
two properties it was chosen for; and the operator-only staleness alert.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from src import run_scheduled
from src.models.coaching import DailyMetric, MetricBaseline, Sleep
from src.models.profile import Profile, UserRole
from src.scheduler import (
    create_scheduler,
    run_evening_monitoring_alerts,
    run_metric_baseline_refresh,
)
from src.services.job_runs import (
    _LOCAL_DAILY_JOBS,
    JobStatus,
    run_tracked_job,
    scheduled_window,
)
from src.services.metric_baselines import (
    BASELINE_STALENESS_LIMIT_DAYS,
    DB_HISTORY_SOURCE,
    MetricBaselineBackfillService,
    unincorporated_nights,
)
from src.services.wake_detection import WINDOW_START

JOB_NAME = "baseline-refresh"


def _profile() -> MagicMock:
    profile = MagicMock()
    profile.id = uuid.uuid4()
    profile.timezone = "Europe/London"
    return profile


def _db_profile() -> Profile:
    return Profile(
        id=uuid.uuid4(),
        display_name="Mark",
        role=UserRole.admin,
        timezone="Europe/London",
        is_active=True,
    )


def _seed_day(session: object, user_id: uuid.UUID, day: date) -> None:
    session.add(  # type: ignore[attr-defined]
        Sleep(
            user_id=user_id,
            calendar_date=day,
            score=70 + (day.day % 10),
            age_adjusted_score=min(74 + (day.day % 10), 100),
            average_spo2_pct=95.0 + (day.day % 3),
            average_respiration=11.0,
        )
    )
    session.add(  # type: ignore[attr-defined]
        DailyMetric(
            user_id=user_id,
            calendar_date=day,
            phase="settled",
            readiness_score=70 + (day.day % 8),
            resting_heart_rate_bpm=44 + (day.day % 4),
            hrv_weekly_avg_ms=42 + (day.day % 6),
        )
    )


# ---------------------------------------------------------------------------
# 228.3 — the job
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_rebuilds_each_active_profile_and_reports_counters() -> None:
    profiles = [_profile(), _profile()]
    session = AsyncMock()
    service = MagicMock()
    service.rebuild = AsyncMock(
        side_effect=[
            SimpleNamespace(
                baselines_created=1,
                baselines_updated=2,
                baselines_unchanged=6,
                samples_considered=84,
                window_start=date(2026, 6, 3),
                window_end=date(2026, 8, 25),
            ),
            SimpleNamespace(
                baselines_created=0,
                baselines_updated=0,
                baselines_unchanged=9,
                samples_considered=40,
                window_start=date(2026, 7, 17),
                window_end=date(2026, 8, 25),
            ),
        ]
    )

    with _refresh_patches(session, profiles, service):
        result = await run_metric_baseline_refresh()

    assert service.rebuild.await_count == 2
    # No `as_of` / `window_days` override: the window end is whatever the newest
    # stored night is, which at 02:30 is yesterday's. See 228.4.
    for call in service.rebuild.await_args_list:
        assert call.kwargs == {}
    assert result.status is JobStatus.succeeded
    assert result.counters == {"profiles": 2, "created": 1, "updated": 2, "unchanged": 15}


@pytest.mark.asyncio
async def test_refresh_skips_when_there_are_no_active_profiles() -> None:
    session = AsyncMock()
    service = MagicMock()
    service.rebuild = AsyncMock()

    with _refresh_patches(session, [], service):
        result = await run_metric_baseline_refresh()

    service.rebuild.assert_not_awaited()
    assert result.status is JobStatus.skipped
    assert result.reason == "no_active_profiles"
    assert result.counters == {"profiles": 0, "created": 0, "updated": 0, "unchanged": 0}


@pytest.mark.asyncio
async def test_refresh_isolates_one_profile_failure_and_degrades() -> None:
    profiles = [_profile(), _profile()]
    session = AsyncMock()
    service = MagicMock()
    service.rebuild = AsyncMock(
        side_effect=[
            RuntimeError("boom"),
            SimpleNamespace(
                baselines_created=0,
                baselines_updated=3,
                baselines_unchanged=6,
                samples_considered=84,
                window_start=date(2026, 6, 3),
                window_end=date(2026, 8, 25),
            ),
        ]
    )

    with _refresh_patches(session, profiles, service):
        result = await run_metric_baseline_refresh()

    session.rollback.assert_awaited_once()
    assert service.rebuild.await_count == 2
    assert result.status is JobStatus.degraded
    assert result.reason == "metric_baseline_refresh_failed"
    assert result.counters["failures"] == 1
    assert result.counters["updated"] == 3


@contextmanager
def _refresh_patches(
    session: AsyncMock, profiles: list[MagicMock], service: MagicMock
) -> Iterator[None]:
    class _Ctx:
        async def __aenter__(self) -> AsyncMock:
            return session

        async def __aexit__(self, *a: object) -> None:
            return None

    with ExitStack() as stack:
        enter = stack.enter_context
        enter(patch("src.scheduler.AsyncSessionLocal", return_value=_Ctx()))
        enter(patch("src.scheduler._active_profiles", AsyncMock(return_value=profiles)))
        enter(patch("src.scheduler.MetricBaselineBackfillService", return_value=service))
        yield


# ---------------------------------------------------------------------------
# 228.3 — registered in all three places, or it is only two-thirds wired
# ---------------------------------------------------------------------------


def test_job_is_registered_in_all_three_places() -> None:
    """The omission this phase exists to prevent, pinned.

    Registering the APScheduler job without the ``_LOCAL_DAILY_JOBS`` entry is
    silent: ``scheduled_window`` falls through to ``_WINDOW_MINUTES.get(name,
    60)`` and files a once-a-night job into hourly buckets, so its run history
    answers a question nobody asked.
    """

    assert JOB_NAME in run_scheduled.JOBS
    assert JOB_NAME in _LOCAL_DAILY_JOBS

    scheduler = create_scheduler()
    try:
        job = scheduler.get_job("metric_baseline_refresh")
        assert job is not None
        # The name the scheduler tracks the run under must be the same string the
        # other two registries key on, or all three are wired to different jobs.
        assert job.func.func is run_tracked_job
        assert job.func.args[0] == JOB_NAME
        assert job.func.args[1] is run_metric_baseline_refresh
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)


def test_cadence_bucket_is_a_local_day_not_an_hour() -> None:
    moment = datetime(2026, 8, 26, 1, 30)
    start, end = scheduled_window(JOB_NAME, moment)
    assert (end - start) == timedelta(days=1)
    # An unregistered name would bucket into the 60-minute default instead.
    unregistered_start, unregistered_end = scheduled_window("not-a-daily-job", moment)
    assert (unregistered_end - unregistered_start) == timedelta(minutes=60)


# ---------------------------------------------------------------------------
# 228.4 — the slot, and the two properties it was chosen for
# ---------------------------------------------------------------------------


def test_slot_runs_before_the_morning_window_opens() -> None:
    """02:30 Europe/London is load-bearing, not decorative.

    It must stay strictly before ``wake_detection.WINDOW_START``: that is both
    what stops the refresh racing the morning read it feeds, *and* what keeps
    tonight's ``sleep`` row — written by the wake sync — outside the 84-night
    distribution tonight will be judged against a few hours later.
    """

    scheduler = create_scheduler()
    try:
        job = scheduler.get_job("metric_baseline_refresh")
        assert job is not None
        fields = {field.name: str(field) for field in job.trigger.fields}
        assert fields["hour"] == "2"
        assert fields["minute"] == "30"
        assert str(job.trigger.timezone) == "Europe/London"
        assert (int(fields["hour"]), int(fields["minute"])) < (
            WINDOW_START.hour,
            WINDOW_START.minute,
        )
        assert job.coalesce is True
        assert job.max_instances == 1
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_refresh_window_ends_on_the_newest_stored_night(db_conn: AsyncConnection) -> None:
    """A 02:30 run sees yesterday as the newest night, so the window ends there.

    Tonight's row does not exist yet — the wake sync writes it hours later — so
    the night being judged is excluded from its own baseline by construction
    rather than by an ``as_of`` argument the job would have to remember to pass.
    """

    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    profile = _db_profile()
    yesterday = date(2026, 8, 25)
    days = [yesterday - timedelta(days=offset) for offset in range(9, -1, -1)]

    async with session_factory() as session:
        session.add(profile)
        await session.flush()
        for day in days:
            _seed_day(session, profile.id, day)
        await session.flush()

        first = await MetricBaselineBackfillService(session).rebuild(profile)
        # A same-day re-run on the same data must be a no-op, not a rewrite.
        second = await MetricBaselineBackfillService(session).rebuild(profile)

        rows = (
            (
                await session.execute(
                    select(MetricBaseline).where(MetricBaseline.user_id == profile.id)
                )
            )
            .scalars()
            .all()
        )

    assert first.window_end == yesterday
    assert first.baselines_created > 0
    assert second.baselines_created == 0
    assert second.baselines_updated == 0
    assert second.baselines_unchanged == first.baselines_created
    assert rows
    assert {row.window_end_date for row in rows} == {yesterday}
    assert all(row.source == DB_HISTORY_SOURCE for row in rows)


# ---------------------------------------------------------------------------
# 228.5 — the staleness detector
# ---------------------------------------------------------------------------


def test_healthy_steady_state_is_one_unincorporated_night() -> None:
    lag = unincorporated_nights(
        newest_sleep_date=date(2026, 8, 26),
        oldest_sleep_date=date(2025, 6, 24),
        baseline_window_end=date(2026, 8, 25),
    )
    assert lag == 1
    assert lag < BASELINE_STALENESS_LIMIT_DAYS


def test_each_missed_night_adds_one_and_the_limit_precedes_measured_harm() -> None:
    newest = date(2026, 8, 26)
    lags = [
        unincorporated_nights(
            newest_sleep_date=newest,
            oldest_sleep_date=date(2025, 6, 24),
            baseline_window_end=newest - timedelta(days=n),
        )
        for n in range(1, 6)
    ]
    assert lags == [1, 2, 3, 4, 5]
    # Two consecutive blips stay quiet; the third fires — and it fires a day
    # before the five-day drift that actually moved the readiness floor
    # (window end 2026-08-20 -> 2026-08-25 moved the median 59.0 -> 61.0).
    assert [lag >= BASELINE_STALENESS_LIMIT_DAYS for lag in lags] == [
        False,
        False,
        False,
        True,
        True,
    ]


def test_no_baselines_counts_the_whole_history_without_a_special_case() -> None:
    # A brand-new profile is new, not stale.
    assert (
        unincorporated_nights(
            newest_sleep_date=date(2026, 8, 26),
            oldest_sleep_date=date(2026, 8, 26),
            baseline_window_end=None,
        )
        == 1
    )
    # Mark's 428 nights with no baseline rows is the job having never run.
    assert (
        unincorporated_nights(
            newest_sleep_date=date(2026, 8, 25),
            oldest_sleep_date=date(2025, 6, 24),
            baseline_window_end=None,
        )
        == 428
    )


def test_no_sleep_history_cannot_be_stale() -> None:
    assert (
        unincorporated_nights(
            newest_sleep_date=None,
            oldest_sleep_date=None,
            baseline_window_end=None,
        )
        is None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("window_end", "expect_alert"),
    [
        (date(2026, 8, 25), False),  # lag 1 — healthy
        (date(2026, 8, 23), False),  # lag 3 — two blips, still quiet
        (date(2026, 8, 22), True),  # lag 4 — the limit
    ],
)
async def test_evening_alerts_flag_a_stale_baseline_to_the_operator_only(
    window_end: date, expect_alert: bool
) -> None:
    """Never a push to Mark: he cannot make a background job run."""

    profile = _profile()
    session = AsyncMock()
    session.execute = AsyncMock(
        return_value=MagicMock(one=MagicMock(return_value=(date(2025, 6, 24), date(2026, 8, 26))))
    )
    session.scalar = AsyncMock(return_value=window_end)

    class _Ctx:
        async def __aenter__(self) -> AsyncMock:
            return session

        async def __aexit__(self, *a: object) -> None:
            return None

    holiday_service = MagicMock()
    holiday_service.get_overnight_away_window_for_date = AsyncMock(return_value=None)
    nudge_service = MagicMock()
    nudge_service.run_monitoring_alerts = AsyncMock(return_value=0)

    with ExitStack() as stack:
        enter = stack.enter_context
        enter(patch("src.scheduler.AsyncSessionLocal", return_value=_Ctx()))
        enter(patch("src.scheduler._active_profiles", AsyncMock(return_value=[profile])))
        enter(patch("src.scheduler._profile_today", return_value=date(2026, 8, 26)))
        enter(patch("src.scheduler.HolidayPauseService", return_value=holiday_service))
        enter(patch("src.scheduler.NudgeAlertService", return_value=nudge_service))
        operator = enter(patch("src.scheduler._log_operator_alert"))
        result = await run_evening_monitoring_alerts()

    assert result.status is JobStatus.succeeded
    assert result.counters["stale_baselines"] == int(expect_alert)
    # The user-facing stale-source pushes are untouched either way.
    nudge_service.run_monitoring_alerts.assert_awaited_once()
    if expect_alert:
        operator.assert_called_once()
        assert operator.call_args.args[0] == "metric_baselines_stale"
        assert operator.call_args.kwargs["unincorporated_nights"] == 4
    else:
        operator.assert_not_called()


@pytest.mark.asyncio
async def test_freshness_check_failure_cannot_fail_the_evening_alerts() -> None:
    profile = _profile()
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=RuntimeError("boom"))

    class _Ctx:
        async def __aenter__(self) -> AsyncMock:
            return session

        async def __aexit__(self, *a: object) -> None:
            return None

    holiday_service = MagicMock()
    holiday_service.get_overnight_away_window_for_date = AsyncMock(return_value=None)
    nudge_service = MagicMock()
    nudge_service.run_monitoring_alerts = AsyncMock(return_value=2)

    with ExitStack() as stack:
        enter = stack.enter_context
        enter(patch("src.scheduler.AsyncSessionLocal", return_value=_Ctx()))
        enter(patch("src.scheduler._active_profiles", AsyncMock(return_value=[profile])))
        enter(patch("src.scheduler._profile_today", return_value=date(2026, 8, 26)))
        enter(patch("src.scheduler.HolidayPauseService", return_value=holiday_service))
        enter(patch("src.scheduler.NudgeAlertService", return_value=nudge_service))
        result = await run_evening_monitoring_alerts()

    assert result.status is JobStatus.succeeded
    assert result.counters["alerts"] == 2
    assert result.counters["stale_baselines"] == 0
