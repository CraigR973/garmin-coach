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
from copy import deepcopy
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from src.models.coaching import (
    Activity,
    Analysis,
    DailyMetric,
    KnowledgeBase,
    ManualEntry,
    MetricBaseline,
    PlannedWorkout,
    Sleep,
    TemperatureReading,
    WeatherDaily,
)
from src.models.profile import Profile, UserRole
from src.services.chat_context import (
    _DROP_ORDER,
    APP_STATE_CHAR_BUDGET,
    KNOWLEDGE_BASE_MEANING,
    ORIGIN_KINDS,
    SINCE_READ_TRIM_FLOOR,
    ChatContextService,
    CoachOrigin,
    _apply_char_budget,
    _night_for,
    _packet_check_in_versions,
    app_state_length,
)
from src.services.holiday_pause import KB_SECTION as HOLIDAY_KB_SECTION

#: Mark's coordinates; ``weather_daily`` stores them NOT NULL.
KILMARNOCK_LAT = 55.6045
KILMARNOCK_LONG = -4.5249

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


def test_char_budget_preserves_named_field_truncations() -> None:
    state = _state(
        latestReviews=[{"conclusions": "x..."}],
        sinceThisRead={
            "anythingChangedSinceRead": True,
            "planChangesSinceRead": [{"summary": "changed..."}],
        },
        omittedForLength=[
            "latestReviews.conclusions(truncated)",
            "sinceThisRead.planChangesSinceRead.summary(truncated)",
        ],
    )

    _apply_char_budget(state)

    assert state["omittedForLength"] == [
        "latestReviews.conclusions(truncated)",
        "sinceThisRead.planChangesSinceRead.summary(truncated)",
    ]
    assert "Trimmed to fit the prompt" in state["omittedForLengthMeaning"]


def test_char_budget_never_drops_the_week_or_the_since_read_delta() -> None:
    week = {"window": {"kind": "week_ahead_from_today"}, "days": _filler(7, _EIGHTH)}
    since = {"anythingChangedSinceRead": True, "activitiesIngestedSinceRead": _filler(5, _EIGHTH)}
    # Batch 255: compared against a snapshot rather than against the same object.
    # `_state(sinceThisRead=since)` stores the identical dict, so the old
    # `state["sinceThisRead"] == since` compared it to itself and passed no
    # matter what `_apply_char_budget` did to it — including the trimming this
    # batch added underneath it.
    week_before = deepcopy(week)
    state = _state(
        weekAhead=week,
        sinceThisRead=since,
        recentActivities=_filler(4, _QUARTER),
        latestReviews=_filler(4, _QUARTER),
        sleepHistory=_filler(4, _QUARTER),
        trends={"bucket": "month", "recentWindows": _filler(6, _EIGHTH), "yearOnYear": {}},
    )

    _apply_char_budget(state)

    assert state["weekAhead"] == week_before
    # The delta survives as a section — it is trimmed, never dropped whole, so
    # "has anything changed since this read" is always answerable.
    assert state["sinceThisRead"]["anythingChangedSinceRead"] is True
    assert state["sinceThisRead"]["activitiesIngestedSinceRead"]
    # The trend series is trimmed oldest-first only after the droppable
    # sections have gone, and at least one window always survives.
    trend_windows = state["trends"]["recentWindows"]  # type: ignore[index]
    assert len(trend_windows) >= 1
    assert trend_windows[-1]["id"] == "5"


def test_char_budget_trims_the_stale_delta_before_the_history_mark_asks_about() -> None:
    """The inversion Batch 255 fixes, in one assertion.

    ``sinceThisRead`` is sized by how *stale the anchor is*, not by how much Mark
    has done: 960 characters against a nine-minute-old brief and 8,835 against a
    six-day-old review. Exempting it from the budget meant the stalest anchor
    bought its own bulk by evicting everything else — in production, on
    2026-09-05, it evicted the fortnight of nights out of an answer about REM.
    """
    since = {
        "anythingChangedSinceRead": True,
        "activitiesIngestedSinceRead": _filler(10, _EIGHTH),
        "checkInsSinceRead": _filler(10, 200),
    }
    state = _state(
        sinceThisRead=since,
        sleepHistory=_filler(14, 200),
        trends={"bucket": "month", "recentWindows": _filler(6, 200), "yearOnYear": {}},
    )
    assert app_state_length(state) > APP_STATE_CHAR_BUDGET

    _apply_char_budget(state)

    assert app_state_length(state) <= APP_STATE_CHAR_BUDGET
    # The stale delta gave way; the nights Mark was asking about did not.
    assert len(since["activitiesIngestedSinceRead"]) < 10
    assert state["sleepHistory"] != []
    assert "sinceThisRead.activitiesIngestedSinceRead(oldest)" in state["omittedForLength"]
    assert "sleepHistory" not in state["omittedForLength"]


def test_char_budget_keeps_enough_of_the_delta_to_still_answer_since_when() -> None:
    # Every entry is a whole budget on its own, so trimming can never get under
    # it — which is the only way to observe where the trim *stops*.
    since = {
        "anythingChangedSinceRead": True,
        "activitiesIngestedSinceRead": _filler(10, APP_STATE_CHAR_BUDGET),
    }
    state = _state(sinceThisRead=since)

    _apply_char_budget(state)

    # Trimmed hard, but never to nothing: an empty list would read as "nothing
    # happened since the read", which is the absence-vs-omission failure again.
    assert len(since["activitiesIngestedSinceRead"]) == SINCE_READ_TRIM_FLOOR
    assert state["charBudget"]["status"] == "best_effort_over_budget"


def test_char_budget_drops_the_knowledge_base_last_and_keeps_its_shape() -> None:
    """Batch 256: the only new section big enough to buy anything back.

    It goes after the three list sections because a rule of Mark's is less
    reconstructable than a session he rode, and it empties to a **mapping** —
    the drop loop was written when every droppable section was a list, and
    flipping a dict to ``[]`` would hand the model a shape it has never seen.
    """
    state = _state(
        recentActivities=_filler(4, _QUARTER),
        latestReviews=_filler(4, _QUARTER),
        sleepHistory=_filler(4, _QUARTER),
        knowledgeBase={"sections": _filler(4, _QUARTER), "meaning": "his own rules"},
    )
    assert app_state_length(state) > APP_STATE_CHAR_BUDGET

    _apply_char_budget(state)

    assert app_state_length(state) <= APP_STATE_CHAR_BUDGET
    assert state["omittedForLength"] == [
        "recentActivities",
        "latestReviews",
        "sleepHistory",
        "knowledgeBase",
    ]
    assert state["knowledgeBase"] == {}


def test_the_small_new_sections_are_never_dropped() -> None:
    """677, 767 and 993 characters: dropping them costs a fact and saves nothing.

    Today's readiness, last night's bedroom and his own bands are undroppable
    for the same reason ``today`` is — the trim exists to shed bulk, and these
    are not bulk.

    The membership assertion is the load-bearing half. A behavioural check alone
    would pass whether or not they were in the drop order, because emptying the
    four larger sections already brings any realistic block under budget — so
    the loop would never reach them, and the test would never fail. Batch 255
    found a test in this exact file that could not fail; one is enough.
    """
    assert set(_DROP_ORDER).isdisjoint({"dailyMetrics", "environment", "personalBaselines"})

    state = _state(
        recentActivities=_filler(6, _QUARTER),
        latestReviews=_filler(6, _QUARTER),
        sleepHistory=_filler(6, _QUARTER),
        knowledgeBase={"sections": _filler(6, _QUARTER)},
        dailyMetrics={"today": {"readinessScore": 80}, "meaning": "wake observation"},
        environment={"thermalReview": {"indoorPeakC": 18.7}, "meaning": "bedroom"},
        personalBaselines={"bands": {"sleep_score": {"median": 74}}, "meaning": "his bands"},
    )

    _apply_char_budget(state)

    assert state["dailyMetrics"]["today"]["readinessScore"] == 80
    assert state["environment"]["thermalReview"]["indoorPeakC"] == 18.7
    assert state["personalBaselines"]["bands"]["sleep_score"]["median"] == 74


def test_only_last_nights_row_is_offered_as_the_thermal_window() -> None:
    """``thermal_review`` takes a sleep window, and a stale one is worse than none.

    The history is newest-first and can begin two days back when Garmin has not
    written last night yet; handing that row over would clip the readings to a
    window they did not fall in and report a peak from the wrong night.
    """
    last_night = Sleep(id=uuid.uuid4(), user_id=uuid.uuid4(), calendar_date=TODAY, score=80)
    older = Sleep(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        calendar_date=TODAY - timedelta(days=2),
        score=70,
    )

    assert _night_for([last_night, older], TODAY) is last_night
    assert _night_for([older], TODAY) is None
    assert _night_for([], TODAY) is None


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
    assert [row["title"] for row in since["activitiesIngestedSinceRead"]] == [
        "Sweet spot intervals"
    ]
    assert since["activitiesIngestedSinceRead"][0]["normalizedPowerWatts"] == 205
    assert since["activitiesIngestedSinceRead"][0]["ingestedAtUtc"] is not None
    assert since["readGeneratedAtUtc"] == "2026-07-30T06:30:00Z"


@pytest.mark.asyncio
async def test_activity_delta_uses_ingest_time_not_activity_start_time(
    db_conn: AsyncConnection,
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        user = await _make_profile(session)
        analysis = await _make_read(session, user.id)
        session.add(
            Activity(
                id=uuid.uuid4(),
                user_id=user.id,
                garmin_activity_id=987654322,
                activity_name="Late-synced morning ride",
                activity_type="indoor_cycling",
                start_utc=datetime(2026, 7, 30, 5, 45),
                created_at=datetime(2026, 7, 30, 7, 5),
                duration_sec=2700,
                raw_summary={},
            )
        )
        await session.commit()

        context = await ChatContextService(session).build(user, analysis, asked_at_utc=ASKED_AT)

    since = context.app_state["sinceThisRead"]
    assert [row["title"] for row in since["activitiesIngestedSinceRead"]] == [
        "Late-synced morning ride"
    ]
    assert since["activitiesIngestedSinceRead"][0]["startUtc"] == "2026-07-30T05:45:00Z"
    assert since["activitiesIngestedSinceRead"][0]["ingestedAtUtc"] == "2026-07-30T07:05:00Z"


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
async def test_adjustable_workout_is_resolved_from_live_plan_rows(
    db_conn: AsyncConnection,
) -> None:
    """Batch 179.3 replaced Batch 178's subject-date liveness set.

    The old mechanism could only *retire* a proposal the frozen packet had
    already offered; this answers the real question — is there a live,
    deliverable bike session on today's plan — so the affordance is right from
    any entry point.
    """
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        user = await _make_profile(session)
        # A split day (Batch 65): two rows on one date, distinguished by
        # incrementing versions the way `plan_import` writes them — the
        # `(user_id, workout_date, version)` unique constraint requires it.
        done = PlannedWorkout(
            id=uuid.uuid4(),
            user_id=user.id,
            workout_date=TODAY,
            version=1,
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
            version=2,
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

    # The completed ride is not adjustable, and the open row is strength, not a
    # deliverable bike session — so there is nothing to propose against.
    assert context.adjustable_workout_id is None
    closed = context.app_state["sinceThisRead"]["subjectDateClosedWorkoutsCurrent"]
    assert [row["title"] for row in closed] == ["Sweet spot"]
    assert "not evidence that the status changed after the read" in closed[0]["meaning"]
    # Listed in plan order, so a split day reads cycle-then-strength.
    today_titles = [row["title"] for row in context.app_state["today"]["plannedWorkouts"]]
    assert today_titles == ["Sweet spot", "Core"]
    assert [row["isLive"] for row in context.app_state["today"]["plannedWorkouts"]] == [False, True]


@pytest.mark.asyncio
async def test_adjustable_workout_is_todays_live_deliverable_ride(
    db_conn: AsyncConnection,
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        user = await _make_profile(session)
        ride = PlannedWorkout(
            id=uuid.uuid4(),
            user_id=user.id,
            workout_date=TODAY,
            version=1,
            title="Sweet spot",
            workout_type="bike_sweet_spot",
            status="planned",
            is_active=True,
            structured_workout={"format": "bike"},
        )
        session.add(ride)
        await session.commit()
        analysis = await _make_read(session, user.id)

        context = await ChatContextService(session).build(user, analysis, asked_at_utc=ASKED_AT)

    assert context.adjustable_workout_id == ride.id


@pytest.mark.asyncio
async def test_today_body_metrics_use_effective_weight_and_vo2max(
    db_conn: AsyncConnection,
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        user = await _make_profile(session)
        session.add_all(
            [
                DailyMetric(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    calendar_date=TODAY - timedelta(days=2),
                    weight_kg=78.4,
                    raw_payload={},
                ),
                DailyMetric(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    calendar_date=TODAY - timedelta(days=12),
                    vo2max=55.0,
                    raw_payload={},
                ),
            ]
        )
        await session.commit()

        context = await ChatContextService(session).build(user, None, asked_at_utc=ASKED_AT)

    body_metrics = context.app_state["today"]["bodyMetrics"]
    assert body_metrics["weightKg"] == 78.4
    assert body_metrics["weightAsOfDate"] == (TODAY - timedelta(days=2)).isoformat()
    assert body_metrics["vo2max"] == 55.0
    assert body_metrics["vo2maxAsOfDate"] == (TODAY - timedelta(days=12)).isoformat()


@pytest.mark.asyncio
async def test_a_holiday_window_leaves_nothing_adjustable(db_conn: AsyncConnection) -> None:
    """An explicit holiday is authoritative even over a stale, un-reversioned row.

    This mirrors ``morning_analysis._rest_day_context``: a plan row inside a
    holiday window can still say ``planned``, and the coach must not offer to
    reshape a session Mark is away for.
    """
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        user = await _make_profile(session)
        session.add(
            PlannedWorkout(
                id=uuid.uuid4(),
                user_id=user.id,
                workout_date=TODAY,
                version=1,
                title="Sweet spot",
                workout_type="bike_sweet_spot",
                status="planned",
                is_active=True,
                structured_workout={"format": "bike"},
            )
        )
        session.add(
            KnowledgeBase(
                id=uuid.uuid4(),
                user_id=user.id,
                section=HOLIDAY_KB_SECTION,
                content={
                    "windows": [
                        {
                            "startDate": (TODAY - timedelta(days=2)).isoformat(),
                            "endDate": (TODAY + timedelta(days=2)).isoformat(),
                            "pausedAtUtc": READ_AT.isoformat(),
                        }
                    ]
                },
                is_active=True,
            )
        )
        await session.commit()
        analysis = await _make_read(session, user.id)

        context = await ChatContextService(session).build(user, analysis, asked_at_utc=ASKED_AT)

    assert context.adjustable_workout_id is None


@pytest.mark.asyncio
async def test_an_unanchored_question_gets_the_state_without_a_read(
    db_conn: AsyncConnection,
) -> None:
    """179.1: Sleep has no ``Analysis`` of its own, and now needs none."""
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        user = await _make_profile(session)
        session.add(
            Sleep(
                id=uuid.uuid4(),
                user_id=user.id,
                calendar_date=TODAY,
                score=78,
                duration_sec=27000,
                raw_payload={},
            )
        )
        await session.commit()

        context = await ChatContextService(session).build(
            user,
            None,
            asked_at_utc=ASKED_AT,
            origin=CoachOrigin(kind="sleep", subject_date=TODAY),
        )

    state = context.app_state
    # No read behind it, so nothing to be "since" — and the block says as much
    # rather than leaving a hole that could read as an absence.
    assert "sinceThisRead" not in state
    assert "readSubjectDate" not in state
    assert "everything you have and all of it is current" in state["meaning"]
    assert state["conversationOpenedFrom"]["surface"] == "his sleep page"
    assert state["conversationOpenedFrom"]["subjectDate"] == TODAY.isoformat()
    # The rest of the app is still all there.
    assert [night["score"] for night in state["sleepHistory"]] == [78]
    assert "weekAhead" in state
    assert "trends" in state


@pytest.mark.asyncio
async def test_todays_check_in_reaches_an_unanchored_question(
    db_conn: AsyncConnection,
) -> None:
    """Batch 255: what Mark wrote today is not a delta, so it cannot need one.

    Check-ins reached the block only through ``sinceThisRead``, which exists only
    when there is a read to be *since* — so "just ask the coach" from Home could
    not see this morning's check-in at all. Measured against production on
    2026-09-05: ``checkInsSinceRead`` absent, today's entry invisible.
    """
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        user = await _make_profile(session)
        session.add(
            ManualEntry(
                id=uuid.uuid4(),
                user_id=user.id,
                entry_date=TODAY,
                entry_at_utc=datetime(2026, 7, 30, 6, 30),
                subjective_score=8,
                feel="Feel good this morning",
                notes="Window openings noted below are for overnight not pre cool.",
                actual_workout_json={},
                supplements_json={},
                food_json={"summary": "25g kettle chips, skyr, and 2 slices toast"},
                sleep_setup_json={"windowCount": 0, "beddingWeight": "quilt"},
            )
        )
        await session.commit()

        context = await ChatContextService(session).build(
            user,
            None,
            asked_at_utc=ASKED_AT,
            origin=CoachOrigin(kind="home", subject_date=TODAY),
        )

    entries = context.app_state["todayCheckIns"]["entries"]
    assert "sinceThisRead" not in context.app_state
    entry = entries[0]
    assert entry["subjectiveScore"] == 8
    # The two fields the chat used to drop. `morning_analysis` has always sent
    # them, so the brief could see the snack and the chat about it could not.
    assert entry["food"] == {"summary": "25g kettle chips, skyr, and 2 slices toast"}
    assert entry["sleepSetup"] == {"windowCount": 0, "beddingWeight": "quilt"}
    # And his prose still says "noted below", which only resolves with the above.
    assert "noted below" in entry["notes"]
    assert entry["contentRole"] == "untrusted_user_data"


@pytest.mark.asyncio
async def test_no_check_in_yet_says_so_rather_than_leaving_a_hole(
    db_conn: AsyncConnection,
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        user = await _make_profile(session)
        await session.commit()
        context = await ChatContextService(session).build(
            user, None, asked_at_utc=ASKED_AT, origin=CoachOrigin(kind="home")
        )

    today_check_ins = context.app_state["todayCheckIns"]
    assert today_check_ins["entries"] == []
    assert "not that he wrote nothing" in today_check_ins["meaning"]


@pytest.mark.asyncio
async def test_a_check_in_since_the_read_carries_its_structured_fields_too(
    db_conn: AsyncConnection,
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        user = await _make_profile(session)
        analysis = await _make_read(session, user.id)
        session.add(
            ManualEntry(
                id=uuid.uuid4(),
                user_id=user.id,
                entry_date=TODAY,
                entry_at_utc=datetime(2026, 7, 30, 7, 45),
                subjective_score=6,
                notes="Hungry overnight",
                actual_workout_json={},
                supplements_json={},
                food_json={"summary": "2 slices toast on top of the usual"},
                sleep_setup_json={"preCoolStartLocal": "18:10"},
            )
        )
        await session.commit()

        context = await ChatContextService(session).build(user, analysis, asked_at_utc=ASKED_AT)

    since = context.app_state["sinceThisRead"]["checkInsSinceRead"]
    assert since[0]["food"] == {"summary": "2 slices toast on top of the usual"}
    assert since[0]["sleepSetup"] == {"preCoolStartLocal": "18:10"}


# ---------------------------------------------------------------------------
# Client/backend origin-kind parity (Batch 193.4 / UX192-04 / CR189-01)
# ---------------------------------------------------------------------------

#: Mirrors `coachOriginKindSchema` in `packages/shared/src/schemas.ts`. There is
#: no shared runtime between the two languages to check this automatically, so
#: this list is deliberately duplicated rather than imported: it must be kept
#: in sync by hand, and this test is what fails the moment it drifts — a
#: backend kind the client cannot render a prompt/unread state for, or a client
#: kind the backend cannot describe to the model.
KNOWN_CLIENT_ORIGIN_KINDS = frozenset(
    {
        "general",
        "home",
        "morning_brief",
        "sleep",
        "week",
        "workout",
        "trends",
        "reviews",
        "weekly_review",
        "state_change",
        "environment",
        "breathwork",
        "strength",
        "walking",
        "check_in",
    }
)


# ---------------------------------------------------------------------------
# Batch 256 — the four sections every question needs, from live rows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_unanchored_question_holds_his_rules_readiness_and_bedroom(
    db_conn: AsyncConnection,
) -> None:
    """256.1: "just ask the coach" from Home used to hold none of these.

    The measurement that opened this batch: of Mark's real 2026-09-05 morning
    packet, 41,757 characters never reached the live block — including his own
    knowledge base, today's readiness and his bedroom climate. So the same
    question answered from Home and from the morning brief got two different
    coaches, and on 09-05 he asked about REM in an explicitly thermal context
    with no ``environment`` in front of it at all.
    """
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        user = await _make_profile(session)
        session.add_all(
            [
                KnowledgeBase(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    section="sleep_protocol",
                    version=3,
                    source="batch_5_seed",
                    content={"bedtimeTarget": "23:15", "preCoolTemperatureC": 17.0},
                    is_active=True,
                ),
                DailyMetric(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    calendar_date=TODAY,
                    readiness_score=80,
                    hrv_last_night_avg_ms=51,
                    resting_heart_rate_bpm=44,
                    body_battery_end=78,
                    raw_payload={},
                ),
                Sleep(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    calendar_date=TODAY,
                    score=78,
                    duration_sec=27000,
                    sleep_start_utc=datetime(2026, 7, 29, 22, 30),
                    sleep_end_utc=datetime(2026, 7, 30, 6, 0),
                    raw_payload={},
                ),
                WeatherDaily(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    calendar_date=TODAY,
                    source="open_meteo",
                    latitude=KILMARNOCK_LAT,
                    longitude=KILMARNOCK_LONG,
                    overnight_low_c=12.7,
                ),
                MetricBaseline(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    metric_key="sleep_score",
                    metric_label="Sleep score",
                    source="garmin",
                    sample_count=90,
                    median_value=74,
                    lower_quartile_value=68,
                    upper_quartile_value=82,
                    window_start_date=TODAY - timedelta(days=90),
                    window_end_date=TODAY,
                ),
            ]
        )
        for offset, celsius in ((0, 19.4), (60, 18.2), (240, 17.9)):
            session.add(
                TemperatureReading(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    captured_at_utc=datetime(2026, 7, 29, 21, 45) + timedelta(minutes=offset),
                    temperature_c=celsius,
                    source="hive",
                )
            )
        await session.commit()

        context = await ChatContextService(session).build(
            user, None, asked_at_utc=ASKED_AT, origin=CoachOrigin(kind="home")
        )

    state = context.app_state
    # His own rules, read live rather than copied off a read he may not be on.
    sections = {row["section"]: row for row in state["knowledgeBase"]["sections"]}
    assert sections["sleep_protocol"]["content"]["bedtimeTarget"] == "23:15"
    assert state["knowledgeBase"]["sleepProtocol"]["preCoolTemperatureC"] == 17.0
    assert state["knowledgeBase"]["meaning"] == KNOWLEDGE_BASE_MEANING
    # Today's readiness.
    assert state["dailyMetrics"]["today"]["readinessScore"] == 80
    assert state["dailyMetrics"]["today"]["hrvLastNightAvgMs"] == 51
    # Last night's bedroom, scoped to the sleep window and using his own target.
    review = state["environment"]["thermalReview"]
    assert review["windowSource"] == "sleep"
    assert review["indoorPeakC"] == 18.2
    assert review["targetPreCoolC"] == 17.0
    assert state["environment"]["weather"]["overnightLowC"] == 12.7
    # And what is normal for him rather than for a population.
    assert state["personalBaselines"]["bands"]["sleep_score"]["median"] == 74


@pytest.mark.asyncio
async def test_the_knowledge_base_is_read_live_not_copied_from_the_read(
    db_conn: AsyncConnection,
) -> None:
    """256.1's reason for building from rows rather than copying the packet.

    A read's packet freezes the knowledge base at generation, and the knowledge
    base is edited *between* reads — the seed fills only missing sections, so
    production is changed by read-modify-write or the wholesale admin PUT. A
    copy would therefore let the coach state a rule Mark has since changed, and
    state it as current.
    """
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        user = await _make_profile(session)
        session.add(
            KnowledgeBase(
                id=uuid.uuid4(),
                user_id=user.id,
                section="sleep_protocol",
                version=4,
                source="batch_5_seed",
                content={"bedtimeTarget": "22:45"},
                is_active=True,
            )
        )
        await session.commit()
        analysis = await _make_read(
            session,
            user.id,
            context_packet={
                "knowledgeBase": {
                    "sections": [
                        {"section": "sleep_protocol", "content": {"bedtimeTarget": "23:15"}}
                    ]
                }
            },
        )

        context = await ChatContextService(session).build(user, analysis, asked_at_utc=ASKED_AT)

    state = context.app_state
    live = {row["section"]: row for row in state["knowledgeBase"]["sections"]}
    assert live["sleep_protocol"]["content"]["bedtimeTarget"] == "22:45"
    # The read keeps its own frozen record untouched — the block is the later of
    # the two, and ``meaning`` already tells the coach which is which.
    frozen = analysis.context_packet["knowledgeBase"]["sections"][0]
    assert frozen["content"]["bedtimeTarget"] == "23:15"


@pytest.mark.asyncio
async def test_a_holiday_leaves_no_bedroom_to_review_but_keeps_the_weather(
    db_conn: AsyncConnection,
) -> None:
    """Batch 113 (#186)'s rule, applied to the conversation.

    Away from home the bedroom is not being slept in, so a thermal review would
    describe an empty room. The weather still travels, exactly as it does in the
    morning packet, because it is true wherever he is — and ``thermalReview`` is
    an explicit ``null`` with a ``meaning`` that says why, never a missing key.
    """
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        user = await _make_profile(session)
        session.add_all(
            [
                KnowledgeBase(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    section=HOLIDAY_KB_SECTION,
                    content={
                        "windows": [
                            {
                                "startDate": (TODAY - timedelta(days=2)).isoformat(),
                                "endDate": (TODAY + timedelta(days=2)).isoformat(),
                                "pausedAtUtc": READ_AT.isoformat(),
                            }
                        ]
                    },
                    is_active=True,
                ),
                WeatherDaily(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    calendar_date=TODAY,
                    source="open_meteo",
                    latitude=KILMARNOCK_LAT,
                    longitude=KILMARNOCK_LONG,
                    overnight_low_c=12.7,
                ),
                TemperatureReading(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    captured_at_utc=datetime(2026, 7, 29, 23, 0),
                    temperature_c=21.5,
                    source="hive",
                ),
            ]
        )
        await session.commit()

        context = await ChatContextService(session).build(
            user, None, asked_at_utc=ASKED_AT, origin=CoachOrigin(kind="home")
        )

    environment = context.app_state["environment"]
    assert environment["thermalReview"] is None
    assert environment["weather"]["overnightLowC"] == 12.7
    assert "away on a holiday" in environment["meaning"]


@pytest.mark.asyncio
async def test_no_reading_yet_today_is_a_null_not_a_missing_section(
    db_conn: AsyncConnection,
) -> None:
    """The rule the whole block is built on: an absence must not read as nothing.

    Garmin has not written a wake observation before Mark's watch syncs, and a
    section that simply vanished would tell the coach the app holds no such
    thing — the failure ``omittedForLength`` exists to prevent, arriving by a
    different door.
    """
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        user = await _make_profile(session)

        context = await ChatContextService(session).build(
            user, None, asked_at_utc=ASKED_AT, origin=CoachOrigin(kind="home")
        )

    state = context.app_state
    assert state["dailyMetrics"]["today"] is None
    assert "not the same as a reading of zero" in state["dailyMetrics"]["meaning"]
    assert state["environment"]["thermalReview"]["sampleCount"] == 0
    assert state["personalBaselines"]["bands"] == {}
    assert state["knowledgeBase"]["sections"] == []


def test_origin_kinds_match_the_client_schema() -> None:
    assert set(ORIGIN_KINDS) == KNOWN_CLIENT_ORIGIN_KINDS
