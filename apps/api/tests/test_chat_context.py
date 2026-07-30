"""Tests for Batch 178 — chat context assembled at ask-time from live app state.

Mark reported on 2026-07-30 that the conversations feel "almost disconnected"
from the app. Two causes, both covered here:

  178.2 — the chat saw one document frozen at generation, so a ride completed
          after the morning brief was invisible to that brief's chat
  178.3 — everything else the app computes (week ahead, trend series, latest
          review conclusions, recent sessions, sleep history) was not in the
          conversation at all, so a question whose answer is rendered one tab
          away got an honest refusal
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from src.models.coaching import (
    Activity,
    Analysis,
    DailyMetric,
    ManualEntry,
    PlannedWorkout,
    Sleep,
)
from src.models.profile import Profile, UserRole
from src.services.chat_context import (
    APP_STATE_CHAR_BUDGET,
    ChatContextService,
    _apply_char_budget,
    _packet_check_in_versions,
    app_state_length,
)

ASKED_AT = datetime(2026, 7, 30, 9, 0)
TODAY = date(2026, 7, 30)
READ_AT = datetime(2026, 7, 30, 6, 30)


# ---------------------------------------------------------------------------
# Pure: token budget and check-in versions
# ---------------------------------------------------------------------------


def _state(**overrides: object) -> dict[str, object]:
    state: dict[str, object] = {
        "version": 1,
        "todayLocalDate": TODAY.isoformat(),
        "sinceThisRead": {"anythingChangedSinceRead": True},
        "today": {"localDate": TODAY.isoformat(), "plannedWorkouts": []},
        "weekAhead": {"window": {"kind": "week_ahead_from_today"}, "days": []},
        "trends": {"bucket": "month", "recentWindows": [], "yearOnYear": {}},
        "latestReviews": [],
        "recentActivities": [],
        "sleepHistory": [],
        "omittedForLength": [],
    }
    state.update(overrides)
    return state


def _filler(count: int, size: int) -> list[dict[str, str]]:
    return [{"id": str(index), "blob": "x" * size} for index in range(count)]


#: Sized against the budget rather than in absolute characters, so raising the
#: budget cannot quietly stop these tests exercising the truncation path.
_EIGHTH = APP_STATE_CHAR_BUDGET // 8
_QUARTER = APP_STATE_CHAR_BUDGET // 4


def test_char_budget_drops_the_least_load_bearing_sections_first() -> None:
    state = _state(
        recentActivities=_filler(10, _QUARTER),
        latestReviews=_filler(2, 400),
        sleepHistory=_filler(14, 200),
    )
    assert app_state_length(state) > APP_STATE_CHAR_BUDGET

    _apply_char_budget(state)

    assert app_state_length(state) <= APP_STATE_CHAR_BUDGET
    # Sessions go first; sleep history survives because dropping the two larger
    # sections already brought the block under budget.
    assert state["recentActivities"] == []
    assert state["omittedForLength"] == ["recentActivities"]
    assert state["sleepHistory"] != []


def test_char_budget_names_everything_it_dropped_so_a_trim_is_not_an_absence() -> None:
    """A silent omission would recreate the defect this batch removes."""
    state = _state(
        recentActivities=_filler(4, _QUARTER),
        latestReviews=_filler(4, _QUARTER),
        sleepHistory=_filler(4, _QUARTER),
    )

    _apply_char_budget(state)

    assert state["omittedForLength"] == ["recentActivities", "latestReviews", "sleepHistory"]
    meaning = str(state["omittedForLengthMeaning"])
    assert "not absent from the app" in meaning
    assert "not in front of you" in meaning


def test_char_budget_never_drops_the_week_or_the_since_read_delta() -> None:
    week = {"window": {"kind": "week_ahead_from_today"}, "days": _filler(7, _EIGHTH)}
    since = {"anythingChangedSinceRead": True, "activitiesCompletedSinceRead": _filler(5, _EIGHTH)}
    state = _state(
        weekAhead=week,
        sinceThisRead=since,
        recentActivities=_filler(4, _QUARTER),
        latestReviews=_filler(4, _QUARTER),
        sleepHistory=_filler(4, _QUARTER),
        trends={"bucket": "month", "recentWindows": _filler(6, _EIGHTH), "yearOnYear": {}},
    )

    _apply_char_budget(state)

    assert state["weekAhead"] == week
    assert state["sinceThisRead"] == since
    # The trend series is trimmed oldest-first only after the droppable
    # sections have gone, and at least one window always survives.
    trend_windows = state["trends"]["recentWindows"]  # type: ignore[index]
    assert len(trend_windows) >= 1
    assert trend_windows[-1]["id"] == "5"


def test_packet_check_in_versions_reads_both_read_shapes() -> None:
    """One notion of which check-in a read reflects, across packet shapes.

    The morning packet carries a ``manualEntries`` list; the post-session
    packets carry a single check-in node. Both stamp ``entryAtUtc`` the way
    Batch 159's ``manual_entry_input_version`` builds it.
    """
    morning = {"manualEntries": [{"entryAtUtc": "2026-07-30T06:10:00Z", "rpe": None}]}
    post_ride = {"postRideCheckIn": {"entryAtUtc": "2026-07-30T18:40:00Z", "rpe": 6.0}}

    assert _packet_check_in_versions(morning) == frozenset({"2026-07-30T06:10:00Z"})
    assert _packet_check_in_versions(post_ride) == frozenset({"2026-07-30T18:40:00Z"})
    assert _packet_check_in_versions({}) == frozenset()
    assert _packet_check_in_versions(None) == frozenset()


# ---------------------------------------------------------------------------
# DB-backed assembly
# ---------------------------------------------------------------------------


async def _make_profile(session: AsyncSession, name: str = "Context Test") -> Profile:
    user = Profile(
        id=uuid.uuid4(),
        display_name=name,
        role=UserRole.admin,
        timezone="Europe/London",
        is_active=True,
    )
    session.add(user)
    await session.commit()
    return user


async def _make_read(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    context_packet: dict[str, object] | None = None,
    analysis_type: str = "morning",
    subject_date: date = TODAY,
    generated_at_utc: datetime = READ_AT,
    output_markdown: str = "Green today.",
) -> Analysis:
    analysis = Analysis(
        id=uuid.uuid4(),
        user_id=user_id,
        analysis_type=analysis_type,
        subject_date=subject_date,
        generated_at_utc=generated_at_utc,
        prompt_version="morning-x",
        verdict="Green",
        context_packet=context_packet or {},
        output_markdown=output_markdown,
        raw_response={},
    )
    session.add(analysis)
    await session.commit()
    return analysis


@pytest.mark.asyncio
async def test_trend_question_is_answerable_from_the_real_series(
    db_conn: AsyncConnection,
) -> None:
    """178.3: "has my HRV been trending down?" is already computed by the app.

    Before this batch the chat had no access to the Trends series at all, so the
    only honest answer was a refusal for something rendered one tab away.
    """
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        user = await _make_profile(session)
        # Two monthly windows, HRV falling. Both start after the HRV
        # reliability boundary (DECISIONS #45) so nothing is excluded.
        for day_offset in range(18):
            session.add(
                DailyMetric(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    calendar_date=date(2026, 6, 12) + timedelta(days=day_offset),
                    hrv_last_night_avg_ms=60,
                    readiness_score=70,
                    resting_heart_rate_bpm=50,
                    raw_payload={},
                )
            )
        for day_offset in range(18):
            session.add(
                DailyMetric(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    calendar_date=date(2026, 7, 5) + timedelta(days=day_offset),
                    hrv_last_night_avg_ms=48,
                    readiness_score=62,
                    resting_heart_rate_bpm=53,
                    raw_payload={},
                )
            )
        await session.commit()
        analysis = await _make_read(session, user.id)

        context = await ChatContextService(session).build(user, analysis, asked_at_utc=ASKED_AT)

    trends = context.app_state["trends"]
    keys = [window["key"] for window in trends["recentWindows"]]
    assert keys[-2:] == ["2026-06", "2026-07"]
    by_key = {window["key"]: window for window in trends["recentWindows"]}

    def _hrv_mean(window_key: str) -> float:
        metrics = {metric["metricKey"]: metric for metric in by_key[window_key]["metrics"]}
        return float(metrics["hrv_ms"]["mean"])

    assert _hrv_mean("2026-06") == 60.0
    assert _hrv_mean("2026-07") == 48.0
    assert _hrv_mean("2026-07") < _hrv_mean("2026-06")
    assert trends["bucket"] == "month"
    assert trends["yearOnYear"]["bucket"] == "month"


@pytest.mark.asyncio
async def test_activity_completed_after_the_read_is_visible_to_that_reads_chat(
    db_conn: AsyncConnection,
) -> None:
    """178.2: the packet froze at 06:30, the ride happened at 17:00."""
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        user = await _make_profile(session)
        analysis = await _make_read(session, user.id)
        session.add(
            Activity(
                id=uuid.uuid4(),
                user_id=user.id,
                garmin_activity_id=987654321,
                activity_name="Sweet spot intervals",
                activity_type="indoor_cycling",
                start_utc=datetime(2026, 7, 30, 17, 0),
                duration_sec=3600,
                avg_power_watts=196,
                normalized_power_watts=205,
                training_load=88.0,
                raw_summary={},
            )
        )
        await session.commit()

        context = await ChatContextService(session).build(user, analysis, asked_at_utc=ASKED_AT)

    since = context.app_state["sinceThisRead"]
    assert since["anythingChangedSinceRead"] is True
    assert [row["title"] for row in since["activitiesCompletedSinceRead"]] == [
        "Sweet spot intervals"
    ]
    assert since["activitiesCompletedSinceRead"][0]["normalizedPowerWatts"] == 205
    assert since["readGeneratedAtUtc"] == "2026-07-30T06:30:00Z"


@pytest.mark.asyncio
async def test_check_in_after_the_read_marks_it_as_no_longer_reflecting_the_latest(
    db_conn: AsyncConnection,
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        user = await _make_profile(session)
        analysis = await _make_read(
            session,
            user.id,
            context_packet={"manualEntries": [{"entryAtUtc": "2026-07-30T06:10:00Z"}]},
        )
        session.add(
            ManualEntry(
                id=uuid.uuid4(),
                user_id=user.id,
                entry_date=TODAY,
                entry_at_utc=datetime(2026, 7, 30, 7, 45),
                subjective_score=6,
                notes="Slept badly after all",
                actual_workout_json={},
                supplements_json={},
                food_json={},
            )
        )
        await session.commit()

        context = await ChatContextService(session).build(user, analysis, asked_at_utc=ASKED_AT)

    since = context.app_state["sinceThisRead"]
    assert since["readReflectsLatestCheckIn"] is False
    assert [row["subjectiveScore"] for row in since["checkInsSinceRead"]] == [6]
    # Mark's own words stay marked as data, never instructions (Decision #243).
    assert since["checkInsSinceRead"][0]["contentRole"] == "untrusted_user_data"


@pytest.mark.asyncio
async def test_week_ahead_is_forward_looking_and_future_days_are_planned_not_missed(
    db_conn: AsyncConnection,
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        user = await _make_profile(session)
        analysis = await _make_read(session, user.id)
        session.add_all(
            [
                PlannedWorkout(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    workout_date=TODAY + timedelta(days=2),
                    title="VO2 Max",
                    workout_type="bike_vo2",
                    status="planned",
                    is_active=True,
                    structured_workout={"format": "bike"},
                ),
                PlannedWorkout(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    workout_date=TODAY + timedelta(days=5),
                    title="Long endurance",
                    workout_type="bike_endurance",
                    status="planned",
                    is_active=True,
                    structured_workout={"format": "bike"},
                ),
            ]
        )
        await session.commit()

        context = await ChatContextService(session).build(user, analysis, asked_at_utc=ASKED_AT)

    week = context.app_state["weekAhead"]
    assert week["window"]["kind"] == "week_ahead_from_today"
    assert week["window"]["startDate"] == TODAY.isoformat()
    assert week["window"]["endDate"] == (TODAY + timedelta(days=6)).isoformat()
    by_date = {day["date"]: day for day in week["days"]}
    ahead = by_date[(TODAY + timedelta(days=2)).isoformat()]
    assert [item["title"] for item in ahead["planned"]] == ["VO2 Max"]
    # A day still ahead of Mark is planned, never a gap in the record.
    assert ahead["dayStatus"] == "planned"
    assert by_date[(TODAY + timedelta(days=5)).isoformat()]["dayStatus"] == "planned"


@pytest.mark.asyncio
async def test_latest_review_conclusions_and_sleep_history_reach_the_conversation(
    db_conn: AsyncConnection,
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        user = await _make_profile(session)
        analysis = await _make_read(session, user.id)
        session.add(
            Analysis(
                id=uuid.uuid4(),
                user_id=user.id,
                analysis_type="weekly_review",
                subject_date=date(2026, 7, 20),
                generated_at_utc=datetime(2026, 7, 27, 8, 0),
                prompt_version="review-x",
                context_packet={},
                output_markdown="Sleep held up; endurance volume was the win.",
                raw_response={},
            )
        )
        for day_offset in range(3):
            session.add(
                Sleep(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    calendar_date=TODAY - timedelta(days=day_offset),
                    score=78 - day_offset,
                    age_adjusted_score=82 - day_offset,
                    qualifier="GOOD",
                    duration_sec=27000,
                    rem_sleep_sec=4800,
                    avg_overnight_hrv_ms=55,
                    factors_json={},
                    raw_payload={},
                )
            )
        await session.commit()

        context = await ChatContextService(session).build(user, analysis, asked_at_utc=ASKED_AT)

    reviews = context.app_state["latestReviews"]
    assert [row["period"] for row in reviews] == ["weekly"]
    assert "endurance volume was the win" in reviews[0]["conclusions"]
    nights = context.app_state["sleepHistory"]
    assert [row["calendarDate"] for row in nights] == [
        TODAY.isoformat(),
        (TODAY - timedelta(days=1)).isoformat(),
        (TODAY - timedelta(days=2)).isoformat(),
    ]
    assert nights[0]["score"] == 78
    assert nights[0]["ageAdjustedScore"] == 82
    assert nights[0]["timeAsleepMin"] == 450


@pytest.mark.asyncio
async def test_live_workout_ids_exclude_a_ride_closed_after_the_read(
    db_conn: AsyncConnection,
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        user = await _make_profile(session)
        done = PlannedWorkout(
            id=uuid.uuid4(),
            user_id=user.id,
            workout_date=TODAY,
            title="Sweet spot",
            workout_type="bike_sweet_spot",
            status="completed",
            is_active=True,
            structured_workout={"format": "bike"},
        )
        still_open = PlannedWorkout(
            id=uuid.uuid4(),
            user_id=user.id,
            workout_date=TODAY,
            title="Core",
            workout_type="strength_core",
            status="planned",
            is_active=True,
            structured_workout={},
        )
        session.add_all([done, still_open])
        await session.commit()
        analysis = await _make_read(session, user.id)

        context = await ChatContextService(session).build(user, analysis, asked_at_utc=ASKED_AT)

    assert context.workout_is_live(still_open.id)
    assert not context.workout_is_live(done.id)
    closed = context.app_state["sinceThisRead"]["subjectDateWorkoutsClosedSinceRead"]
    assert [row["title"] for row in closed] == ["Sweet spot"]
