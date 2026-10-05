"""Batch 312: a slow Garmin no longer freezes the app.

Every Garmin and Hive call ran on the event loop, through ``retry_sync``, so while
one ran nothing else in the API did: no request and no other job, for minutes on
27 Sep. And each job read its profiles and called out inside that read's
transaction, so a pooled connection sat idle for the whole fetch. These pin the
three rules that close it: the call runs in a worker thread; one Garmin call, and
one Hive call, at a time across the process; and no transaction is open while
either answers. What each job stores is unchanged.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.models.coaching import Activity, Analysis, DailyMetric, Sleep, TemperatureReading
from src.models.profile import Profile, UserRole
from src.scheduler import run_garmin_activity_poll, run_hive_temperature_poll, run_wake_check
from src.seeds import MARK_GARMIN_USER_PROFILE_PK
from src.services.environment_sync import HiveClient, HivePayloads
from src.services.garmin_sync import (
    GarminActivityPayloads,
    GarminConnectClient,
    GarminDailyPayloads,
)
from src.services.job_runs import JobResult, JobStatus
from src.services.morning_inputs import MorningInputPresence
from src.services.morning_pipeline import MorningBriefPipeline, sync_garmin_daily
from src.services.retry import retry_sync
from src.services.wake_detection import WAKE_CHECK_ANALYSIS_TYPE, WakeDecision
from tests.test_environment_sync import open_meteo_payload

FIXTURES = Path(__file__).parent / "fixtures"
MARK = MARK_GARMIN_USER_PROFILE_PK
LONDON = ZoneInfo("Europe/London")
DAY = date(2026, 6, 18)
HIVE_HOME = "aa1fbb37-6b65-4622-b609-5d75534fafd3"


def _fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


def _marks_day() -> GarminDailyPayloads:
    sleep = _fixture("garmin/sleep.json")
    sleep["dailySleepDTO"]["userProfilePK"] = MARK
    return GarminDailyPayloads(
        training_readiness=_fixture("garmin/training_readiness.json"),
        sleep=sleep,
        hrv=_fixture("garmin/hrv.json"),
        body_battery=_fixture("garmin/body_battery.json"),
        rhr=_fixture("garmin/rhr.json"),
        weigh_ins=_fixture("garmin/weigh_ins.json"),
        max_metrics_vo2=_fixture("garmin/max_metrics_vo2.json"),
        training_status=_fixture("garmin/training_status.json"),
        stress=_fixture("garmin/stress.json"),
    )


def _marks_activities() -> GarminActivityPayloads:
    summaries = _fixture("garmin/activities.json")
    for summary in summaries:
        summary["ownerId"] = MARK
    return GarminActivityPayloads(summaries=summaries)


def _hive_payloads() -> HivePayloads:
    return HivePayloads(
        get_all=_fixture("hive/getAll.json"),
        products=_fixture("hive/getProducts.json"),
        devices=_fixture("hive/getDevices.json"),
    )


def _on_the_event_loop() -> bool:
    """True on a thread that is running an event loop: the one the whole API shares."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


class _Calls:
    """Where each external call ran, and whether a transaction was open as it did."""

    def __init__(self, holding: Callable[[], bool]) -> None:
        self.holding = holding
        self.seen: list[tuple[bool, bool]] = []

    def note(self) -> None:
        self.seen.append((_on_the_event_loop(), self.holding()))

    def all_off_the_loop_with_nothing_open(self) -> bool:
        return bool(self.seen) and all(seen == (False, False) for seen in self.seen)


class _Session:
    """Stands in for an ``AsyncSession`` and holds a transaction the way one does.

    Any read or write begins one and a commit or a rollback ends it, which is all
    these tests need from it: whether one was open when Garmin or Hive was called.
    """

    def __init__(self, profiles: list[Any], *, open_: bool = False) -> None:
        self.profiles = profiles
        self.open = open_

    def in_transaction(self) -> bool:
        return self.open

    def read(self) -> None:
        self.open = True

    async def execute(self, *_a: object, **_k: object) -> MagicMock:
        self.open = True
        result = MagicMock()
        result.scalars.return_value.all.return_value = self.profiles
        return result

    async def scalar(self, *_a: object, **_k: object) -> None:
        self.open = True

    async def get(self, *_a: object, **_k: object) -> None:
        self.open = True

    def add(self, *_a: object, **_k: object) -> None:
        self.open = True

    async def flush(self, *_a: object, **_k: object) -> None:
        self.open = True

    async def refresh(self, *_a: object, **_k: object) -> None:
        self.open = True

    async def commit(self) -> None:
        self.open = False

    async def rollback(self) -> None:
        self.open = False


class _Ctx:
    def __init__(self, session: Any) -> None:
        self.session = session

    async def __aenter__(self) -> Any:
        return self.session

    async def __aexit__(self, *_a: object) -> None:
        return None


def _job_profile(**fields: Any) -> MagicMock:
    profile = MagicMock()
    profile.id = uuid.uuid4()
    profile.timezone = "Europe/London"
    profile.garmin_user_profile_pk = MARK
    profile.latitude = None
    profile.longitude = None
    for name, value in fields.items():
        setattr(profile, name, value)
    return profile


def _writes(session: _Session, value: Any) -> AsyncMock:
    """A service call that writes, so it opens the transaction as a real one would."""

    async def write(*_a: object, **_k: object) -> Any:
        session.read()
        return value

    return AsyncMock(side_effect=write)


# --- the event loop stays free -------------------------------------------------------


async def test_a_blocking_call_leaves_the_event_loop_free() -> None:
    """A fake Garmin call sleeps for 0.3 s; another coroutine keeps ticking meanwhile."""
    ticks = 0
    stop = asyncio.Event()

    async def tick() -> None:
        nonlocal ticks
        while not stop.is_set():
            ticks += 1
            await asyncio.sleep(0.01)

    def slow_garmin_call() -> str:
        time.sleep(0.3)
        return "sleep data"

    ticker = asyncio.create_task(tick())
    await asyncio.sleep(0)
    before = ticks
    answer = await retry_sync(slow_garmin_call)
    during = ticks - before
    stop.set()
    await ticker

    assert answer == "sleep data"
    # About 30 ticks fit in 0.3 s; on the loop the call allowed none.
    assert during >= 10


async def test_a_retry_runs_each_attempt_off_the_loop() -> None:
    attempts: list[bool] = []

    def flaky() -> str:
        attempts.append(_on_the_event_loop())
        if len(attempts) < 3:
            raise ConnectionError("Garmin 503")
        return "ok"

    assert await retry_sync(flaky, attempts=3, delay_sec=0.0) == "ok"
    assert attempts == [False, False, False]


# --- no transaction is open while Garmin or Hive answers ---------------------------------


async def test_the_hive_poll_calls_hive_off_the_loop_with_nothing_open() -> None:
    profile = _job_profile(hive_home_id=HIVE_HOME)
    session = _Session([profile])
    calls = _Calls(session.in_transaction)
    payloads = _hive_payloads()

    def fetch() -> HivePayloads:
        calls.note()
        return payloads

    hive = MagicMock()
    hive.fetch_payloads = MagicMock(side_effect=fetch)
    service = MagicMock()
    service.sync_hive_temperatures = _writes(session, MagicMock(temperature_readings_synced=1))

    with (
        patch("src.scheduler.AsyncSessionLocal", return_value=_Ctx(session)),
        patch("src.scheduler.HiveClient", return_value=hive),
        patch("src.scheduler.EnvironmentSyncService", return_value=service),
    ):
        result = await run_hive_temperature_poll()

    assert result.status is JobStatus.succeeded
    assert calls.all_off_the_loop_with_nothing_open(), calls.seen
    # The same reading is stored from the same payloads, and committed.
    assert service.sync_hive_temperatures.await_args.args[:2] == (profile.id, payloads)
    assert session.in_transaction() is False


async def test_the_wake_check_calls_garmin_off_the_loop_with_nothing_open() -> None:
    profile = _job_profile()
    session = _Session([profile])
    calls = _Calls(session.in_transaction)

    def fetch_sleep(_day: date) -> dict[str, Any]:
        calls.note()
        return {}

    garmin = MagicMock()
    garmin.fetch_sleep = MagicMock(side_effect=fetch_sleep)
    record = _writes(session, None)

    async def active_profiles(_session: object) -> list[Any]:
        session.read()
        return [profile]

    with ExitStack() as stack:
        enter = stack.enter_context
        enter(patch("src.scheduler.AsyncSessionLocal", return_value=_Ctx(session)))
        enter(patch("src.scheduler._active_profiles", AsyncMock(side_effect=active_profiles)))
        enter(
            patch(
                "src.scheduler.morning_input_presence",
                _writes(session, MorningInputPresence(daily_metrics=False, sleep=False)),
            )
        )
        enter(
            patch(
                "src.scheduler._profile_now",
                lambda _profile: datetime(2026, 6, 24, 8, 5, tzinfo=LONDON),
            )
        )
        enter(patch("src.scheduler.GarminConnectClient", return_value=garmin))
        enter(patch("src.scheduler._last_seen_sleep_end", _writes(session, None)))
        enter(
            patch(
                "src.scheduler.is_morning_ready",
                MagicMock(return_value=WakeDecision("wait", None, "awaiting_stability")),
            )
        )
        enter(patch("src.scheduler._record_wake_check", record))
        enter(patch("src.scheduler.run_wake_nudge", AsyncMock(return_value=JobResult.succeeded())))
        result = await run_wake_check()

    assert result.status is JobStatus.succeeded
    assert calls.all_off_the_loop_with_nothing_open(), calls.seen
    record.assert_awaited_once()


async def test_the_activity_poll_fetches_each_profile_with_nothing_open() -> None:
    """The second profile is the case a single poll-wide transaction got wrong: its
    fetch started with the first profile's writes still open."""
    first, second = _job_profile(), _job_profile()
    session = _Session([first, second])
    calls = _Calls(session.in_transaction)

    def fetch(*_a: object, **_k: object) -> GarminActivityPayloads:
        calls.note()
        return _marks_activities()

    garmin = MagicMock()
    garmin.fetch_activity_payloads = MagicMock(side_effect=fetch)
    sync_service = MagicMock()
    sync_service.sync_activities = _writes(
        session, MagicMock(activities_synced=1, timeseries_samples_synced=0)
    )
    pending = MagicMock()
    for method in (
        "pending_ride_activities",
        "pending_flexibility_activities",
        "pending_strength_activities",
        "pending_walk_activities",
    ):
        setattr(pending, method, _writes(session, []))

    with ExitStack() as stack:
        enter = stack.enter_context
        enter(patch("src.scheduler.AsyncSessionLocal", return_value=_Ctx(session)))
        enter(patch("src.scheduler.GarminConnectClient", return_value=garmin))
        enter(patch("src.scheduler.GarminSyncService", return_value=sync_service))
        for name in (
            "PostWorkoutAnalysisService",
            "PostFlexibilityAnalysisService",
            "PostStrengthAnalysisService",
            "PostWalkAnalysisService",
        ):
            enter(patch(f"src.scheduler.{name}", return_value=pending))
        enter(patch("src.scheduler.NudgeAlertService", return_value=MagicMock()))
        result = await run_garmin_activity_poll()

    assert result.status is JobStatus.succeeded
    assert len(calls.seen) == 2
    assert calls.all_off_the_loop_with_nothing_open(), calls.seen
    assert [call.args[0] for call in sync_service.sync_activities.await_args_list] == [
        first.id,
        second.id,
    ]
    assert result.counters["activities"] == 2
    assert session.in_transaction() is False


async def test_the_morning_sync_calls_out_with_nothing_open() -> None:
    """Weather first, inside the caller's profile read; then four Garmin days."""
    profile = _job_profile()
    session = _Session([profile], open_=True)  # the caller has just read the profile
    calls = _Calls(session.in_transaction)
    weather_calls = _Calls(session.in_transaction)

    async def weather(_request: object) -> dict[str, object]:
        weather_calls.note()
        return open_meteo_payload()

    meteo = MagicMock()
    meteo.fetch_daily_payload = AsyncMock(side_effect=weather)

    def fetch_day(_day: date) -> GarminDailyPayloads:
        calls.note()
        return _marks_day()

    garmin = MagicMock()
    garmin.fetch_daily_payloads = MagicMock(side_effect=fetch_day)
    weather_service = MagicMock()
    weather_service.sync_weather_daily = _writes(session, MagicMock(weather_days_synced=2))
    garmin_service = MagicMock()
    garmin_service.sync_daily = _writes(session, MagicMock(daily_metrics_synced=1, sleep_synced=1))

    with (
        patch("src.services.morning_pipeline.EnvironmentSyncService", return_value=weather_service),
        patch("src.services.morning_pipeline.GarminSyncService", return_value=garmin_service),
        patch("src.services.morning_pipeline.profile_today", return_value=DAY),
    ):
        result = await MorningBriefPipeline(session).sync_inputs(
            [profile], garmin_client=garmin, weather_client=meteo
        )

    assert (result.weather_days, result.daily_metrics, result.failures) == (2, 4, 0)
    # On the loop is fine for the weather: it is an async client, it never blocked.
    assert [held for _loop, held in weather_calls.seen] == [False]
    assert len(calls.seen) == 4
    assert calls.all_off_the_loop_with_nothing_open(), calls.seen


async def test_a_reload_after_a_failed_step_is_ended_before_garmin_is_called() -> None:
    """A failed weather step rolls back and expires the profile; the reload that
    follows opens a transaction, which must not still be open when Garmin is."""
    profile = _job_profile()
    session = _Session([profile])
    calls = _Calls(session.in_transaction)

    async def reload(_session: object, *_instances: object) -> None:
        session.read()

    def fetch_day(_day: date) -> GarminDailyPayloads:
        calls.note()
        return _marks_day()

    garmin = MagicMock()
    garmin.fetch_daily_payloads = MagicMock(side_effect=fetch_day)
    service = MagicMock()
    service.sync_daily = _writes(session, MagicMock(daily_metrics_synced=1, sleep_synced=1))

    with (
        patch("src.services.morning_pipeline.restore_after_rollback", side_effect=reload),
        patch("src.services.morning_pipeline.GarminSyncService", return_value=service),
        patch("src.services.morning_pipeline.profile_today", return_value=DAY),
    ):
        result = await sync_garmin_daily(session, [profile], client=garmin)

    assert (result.daily_metrics, result.failures) == (4, 0)
    assert calls.all_off_the_loop_with_nothing_open(), calls.seen


# --- one call at a time -----------------------------------------------------------------


class _Spans:
    """Records when each fake call started and ended, to see whether any overlapped."""

    def __init__(self) -> None:
        self.spans: list[tuple[float, float]] = []
        self._lock = threading.Lock()

    def call(self, seconds: float = 0.2) -> None:
        start = time.monotonic()
        time.sleep(seconds)
        with self._lock:
            self.spans.append((start, time.monotonic()))

    def overlapped(self) -> bool:
        ordered = sorted(self.spans)
        return any(later[0] < earlier[1] for earlier, later in zip(ordered, ordered[1:]))


def _garmin_client(spans: _Spans) -> GarminConnectClient:
    """A real client whose login already holds a fake garminconnect session."""
    api = MagicMock()
    api.get_sleep_data = MagicMock(side_effect=lambda _day: spans.call())
    api.upload_workout = MagicMock(side_effect=lambda _workout: spans.call() or {"workoutId": "1"})
    api.schedule_workout = MagicMock(return_value={"workoutScheduleId": "2"})
    client = GarminConnectClient()
    client._client = api
    return client


async def test_overlapping_garmin_calls_run_one_after_the_other() -> None:
    """A workout delivery is under way in its worker thread when the wake check
    polls, each from its own client, as the app builds them. Before Batch 312 the
    poll ran on the loop beside the delivery's thread, and both reached Garmin."""
    spans = _Spans()
    delivery, poll = _garmin_client(spans), _garmin_client(spans)

    await asyncio.gather(
        asyncio.to_thread(delivery.upload_and_schedule_workout, {"workoutName": "Z2"}, DAY),
        retry_sync(lambda: poll.fetch_sleep(DAY)),
    )

    assert len(spans.spans) == 2
    assert not spans.overlapped(), spans.spans


async def test_overlapping_hive_calls_run_one_after_the_other() -> None:
    spans = _Spans()

    def hive_client() -> HiveClient:
        api = MagicMock()
        api.getAll = MagicMock(side_effect=lambda: spans.call())
        client = HiveClient()
        client._api = api
        return client

    first, second = hive_client(), hive_client()
    await asyncio.gather(
        asyncio.to_thread(first.fetch_payloads),
        asyncio.to_thread(second.fetch_payloads),
    )

    assert len(spans.spans) == 2
    assert not spans.overlapped(), spans.spans


# --- the real database (CI) ---------------------------------------------------------------


@contextmanager
def _recorded_sessions(db_conn: AsyncConnection) -> Iterator[tuple[Callable[[], Any], list[Any]]]:
    sessions: list[AsyncSession] = []

    def factory() -> AsyncSession:
        session = AsyncSession(bind=db_conn, expire_on_commit=False)
        sessions.append(session)
        return session

    yield factory, sessions


def _any_open(sessions: list[AsyncSession]) -> Callable[[], bool]:
    return lambda: any(session.in_transaction() for session in sessions)


async def _seed(db_conn: AsyncConnection, **fields: Any) -> uuid.UUID:
    user_id = uuid.uuid4()
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add(
            Profile(
                id=user_id,
                display_name=f"Batch 312 {user_id.hex[:8]}",
                role=UserRole.admin,
                timezone="Europe/London",
                is_active=True,
                **fields,
            )
        )
        await session.commit()
    return user_id


async def _count(db_conn: AsyncConnection, model: Any, user_id: uuid.UUID) -> int:
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        return int(
            await session.scalar(
                select(func.count()).select_from(model).where(model.user_id == user_id)
            )
            or 0
        )


@pytest.mark.asyncio
async def test_the_hive_poll_stores_the_reading_with_nothing_open(
    db_conn: AsyncConnection,
) -> None:
    user_id = await _seed(db_conn, hive_home_id=HIVE_HOME)
    with _recorded_sessions(db_conn) as (factory, sessions):
        calls = _Calls(_any_open(sessions))

        def fetch() -> HivePayloads:
            calls.note()
            return _hive_payloads()

        hive = MagicMock()
        hive.fetch_payloads = MagicMock(side_effect=fetch)
        with (
            patch("src.scheduler.AsyncSessionLocal", new=factory),
            patch("src.scheduler.HiveClient", return_value=hive),
        ):
            result = await run_hive_temperature_poll()

    assert result.status is JobStatus.succeeded
    assert calls.all_off_the_loop_with_nothing_open(), calls.seen
    assert await _count(db_conn, TemperatureReading, user_id) == 1


@pytest.mark.asyncio
async def test_the_activity_poll_stores_marks_ride_with_nothing_open(
    db_conn: AsyncConnection,
) -> None:
    first = await _seed(db_conn, garmin_user_profile_pk=MARK)
    second = await _seed(db_conn, garmin_user_profile_pk=MARK)
    with _recorded_sessions(db_conn) as (factory, sessions):
        calls = _Calls(_any_open(sessions))

        def fetch(*_a: object, **_k: object) -> GarminActivityPayloads:
            calls.note()
            return _marks_activities()

        garmin = MagicMock()
        garmin.fetch_activity_payloads = MagicMock(side_effect=fetch)
        # The rows under test are the activities; nothing here is pending a check-in.
        pending = MagicMock()
        for method in (
            "pending_ride_activities",
            "pending_flexibility_activities",
            "pending_strength_activities",
            "pending_walk_activities",
        ):
            setattr(pending, method, AsyncMock(return_value=[]))
        with ExitStack() as stack:
            enter = stack.enter_context
            enter(patch("src.scheduler.AsyncSessionLocal", new=factory))
            enter(patch("src.scheduler.GarminConnectClient", return_value=garmin))
            for name in (
                "PostWorkoutAnalysisService",
                "PostFlexibilityAnalysisService",
                "PostStrengthAnalysisService",
                "PostWalkAnalysisService",
            ):
                enter(patch(f"src.scheduler.{name}", return_value=pending))
            enter(patch("src.scheduler.NudgeAlertService", return_value=MagicMock()))
            result = await run_garmin_activity_poll()

    assert result.status is JobStatus.succeeded
    assert len(calls.seen) == 2
    assert calls.all_off_the_loop_with_nothing_open(), calls.seen
    # The fixture's one ride, stored once for each profile that names Mark's account.
    assert await _count(db_conn, Activity, first) == 1
    assert await _count(db_conn, Activity, second) == 1


@pytest.mark.asyncio
async def test_the_wake_check_records_the_poll_with_nothing_open(
    db_conn: AsyncConnection,
) -> None:
    user_id = await _seed(db_conn, garmin_user_profile_pk=MARK)
    with _recorded_sessions(db_conn) as (factory, sessions):
        calls = _Calls(_any_open(sessions))

        def fetch_sleep(_day: date) -> dict[str, Any]:
            calls.note()
            return {
                "dailySleepDTO": {
                    "calendarDate": "2026-06-24",
                    "sleepStartTimestampGMT": "2026-06-23T23:00:00",
                    "sleepEndTimestampGMT": "2026-06-24T07:00:00",
                    "sleepTimeSeconds": 28800,
                    "sleepScores": {"overall": {"value": 80, "qualifierKey": "good"}},
                }
            }

        garmin = MagicMock()
        garmin.fetch_sleep = MagicMock(side_effect=fetch_sleep)
        with (
            patch("src.scheduler.AsyncSessionLocal", new=factory),
            patch("src.scheduler.GarminConnectClient", return_value=garmin),
            patch(
                "src.scheduler._profile_now",
                lambda _profile: datetime(2026, 6, 24, 8, 5, tzinfo=LONDON),
            ),
            patch("src.scheduler.run_wake_nudge", AsyncMock(return_value=JobResult.succeeded())),
        ):
            await run_wake_check()

    assert calls.all_off_the_loop_with_nothing_open(), calls.seen
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        recorded = await session.scalar(
            select(func.count())
            .select_from(Analysis)
            .where(
                Analysis.user_id == user_id,
                Analysis.analysis_type == WAKE_CHECK_ANALYSIS_TYPE,
            )
        )
    assert recorded == 1


@pytest.mark.asyncio
async def test_the_morning_sync_stores_the_day_with_nothing_open(
    db_conn: AsyncConnection,
) -> None:
    user_id = await _seed(db_conn, garmin_user_profile_pk=MARK)
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        profile = await session.get(Profile, user_id)  # the caller's read, still open
        assert profile is not None
        assert session.in_transaction()
        calls = _Calls(session.in_transaction)
        weather_calls = _Calls(session.in_transaction)

        async def weather(_request: object) -> dict[str, object]:
            weather_calls.note()
            return open_meteo_payload()

        meteo = MagicMock()
        meteo.fetch_daily_payload = AsyncMock(side_effect=weather)

        def fetch_day(_day: date) -> GarminDailyPayloads:
            calls.note()
            return _marks_day()

        garmin = MagicMock()
        garmin.fetch_daily_payloads = MagicMock(side_effect=fetch_day)
        with patch("src.services.morning_pipeline.profile_today", return_value=DAY):
            result = await MorningBriefPipeline(session).sync_inputs(
                [profile], garmin_client=garmin, weather_client=meteo
            )

    assert (result.weather_days, result.daily_metrics, result.failures) == (2, 4, 0)
    assert [held for _loop, held in weather_calls.seen] == [False]
    assert len(calls.seen) == 4
    assert calls.all_off_the_loop_with_nothing_open(), calls.seen
    # Today's morning reading and three settled days; the one night the fixture holds.
    assert await _count(db_conn, DailyMetric, user_id) == 4
    assert await _count(db_conn, Sleep, user_id) == 1
