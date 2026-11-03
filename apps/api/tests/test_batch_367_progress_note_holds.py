"""Batch 367.1 — the progress note holds in light weeks and near a test, and counts key
sessions only.

The note's first live firing, in the 1 Nov 2026 weekly review, rested on 27 Oct (VO₂ 30/30),
29 Oct (sweet spot 2 × 30) and 31 Oct (a Zone 2 ride with six 12-second sprints), and offered
"a ramp test, or one small step up" into the recovery week (2–8 Nov) the same review said
needed no changes, 12 days after his 20 Oct ramp test (CI359-02). Sun 8 Nov's review could
offer it again. These tests replay that shape.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.models.coaching import Activity, Analysis, PlanBlock, PlannedWorkout
from src.models.profile import Profile, UserRole
from src.services.progress_signal import (
    HOLD_LIGHT_WEEK,
    HOLD_NEAR_TEST,
    KEY_SESSION_TYPES,
    READY_NOTE,
    TEST_QUIET_DAYS,
    hard_sessions_from_packets,
    last_ramp_test,
    progress_hold,
    progress_signal,
)
from src.services.reviews import ReviewService

REVIEW_DAY = date(2026, 11, 1)  # Sunday; the week ahead, 2–8 Nov, is a recovery week
RAMP_TEST = date(2026, 10, 20)


def _interval(target: float, adherence: str = "on", label: str | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {
        "durationSec": 30,
        "avgPowerWatts": 300,
        "avgHeartRateBpm": 130,
        "pctFtp": target,
        "targetPctFtpLow": target,
        "targetPctFtpHigh": target,
        "adherence": adherence,
    }
    if label is not None:
        item["label"] = label
    return item


#: 1 Nov's rides as stored: (day, intervals, the session's planned workout type).
NOV_1_RIDES: list[tuple[date, Any, str | None]] = [
    (date(2026, 10, 20), [_interval(110, "under", "Ramp step 10 @104%")], "bike_threshold"),
    (date(2026, 10, 22), [_interval(89), _interval(89)], "bike_sweet_spot"),
    (date(2026, 10, 27), [_interval(130)] * 22, "bike_vo2"),
    (date(2026, 10, 29), [_interval(89)] * 4, "bike_sweet_spot"),
    (date(2026, 10, 31), [_interval(185)] * 6, "bike_endurance"),  # Z2 + sprints
]
#: Every morning Green except 23 Oct, the morning after 22 Oct's sweet spot.
NOV_1_MORNINGS = {date(2026, 10, 21) + timedelta(days=offset): "Green" for offset in range(12)} | {
    date(2026, 10, 23): "Amber"
}


def test_a_zone_2_ride_with_sprints_is_not_a_key_session() -> None:
    assert {"bike_vo2", "bike_threshold", "bike_sweet_spot"} == KEY_SESSION_TYPES
    sessions = hard_sessions_from_packets(NOV_1_RIDES, NOV_1_MORNINGS)
    assert [s.day for s in sessions] == [
        date(2026, 10, 22),
        date(2026, 10, 27),
        date(2026, 10, 29),
    ]
    # A ride whose type the read did not record is not counted either.
    assert hard_sessions_from_packets([(REVIEW_DAY, [_interval(130)], None)], {}) == []


def test_on_1_nov_key_sessions_alone_bring_no_note() -> None:
    """CI359-02, proved: without the sprint ride the third session back had an Amber."""
    signal = progress_signal(
        [], hard_sessions_from_packets(NOV_1_RIDES, NOV_1_MORNINGS), as_of=REVIEW_DAY
    )
    assert (signal["readyToProgress"], signal["note"]) == (False, None)


def test_the_note_holds_in_a_light_week_and_within_four_weeks_of_a_test() -> None:
    assert TEST_QUIET_DAYS == 28
    clear = progress_hold(as_of=REVIEW_DAY, light_week=False)
    assert clear is None
    assert progress_hold(as_of=REVIEW_DAY, light_week=True) == HOLD_LIGHT_WEEK
    assert progress_hold(as_of=REVIEW_DAY, light_week=False, last_test=RAMP_TEST) == (
        HOLD_NEAR_TEST
    )
    # Sun 8 Nov: 19 days after the test, still held; Sun 22 Nov: 33 days, not by the test.
    assert progress_hold(as_of=date(2026, 11, 8), light_week=False, last_test=RAMP_TEST) == (
        HOLD_NEAR_TEST
    )
    assert progress_hold(as_of=date(2026, 11, 22), light_week=False, last_test=RAMP_TEST) is None
    # A test planned within four weeks holds it too.
    assert (
        progress_hold(as_of=REVIEW_DAY, light_week=False, next_test=REVIEW_DAY + timedelta(20))
        == HOLD_NEAR_TEST
    )
    assert last_ramp_test(NOV_1_RIDES) == RAMP_TEST


def test_a_held_note_says_why_for_the_record_and_never_reaches_mark() -> None:
    sessions = hard_sessions_from_packets(
        [
            (date(2026, 10, 27), [_interval(130)] * 22, "bike_vo2"),
            (date(2026, 10, 29), [_interval(89)] * 4, "bike_sweet_spot"),
            (date(2026, 10, 30), [_interval(89)] * 4, "bike_sweet_spot"),
        ],
        {date(2026, 10, 28): "Green", date(2026, 10, 30): "Green", date(2026, 10, 31): "Green"},
        # Batch 367.2: his efforts (27 and 29 Oct were 6 of 10).
        {date(2026, 10, 27): 6, date(2026, 10, 29): 6, date(2026, 10, 30): 6},
    )
    ready = progress_signal([], sessions, as_of=REVIEW_DAY)
    assert (ready["readyToProgress"], ready["note"], ready["heldBecause"]) == (
        True,
        READY_NOTE,
        None,
    )
    held = progress_signal([], sessions, as_of=REVIEW_DAY, hold=HOLD_LIGHT_WEEK)
    assert (held["readyToProgress"], held["note"], held["heldBecause"]) == (
        False,
        None,
        HOLD_LIGHT_WEEK,
    )


# -- on Postgres: the review's own read of 1 Nov's shape -------------------------------------


async def _ride(
    session: AsyncSession, user_id: uuid.UUID, day: date, intervals: Any, workout_type: str
) -> Analysis:
    """A stored post-ride read, with the ride it reads (the review keeps one per ride)."""
    activity = Activity(
        user_id=user_id,
        garmin_activity_id=int(day.strftime("%Y%m%d")),
        activity_name="Zwift ride",
        activity_type="virtual_ride",
        start_utc=datetime.combine(day, datetime.min.time()) + timedelta(hours=10),
        duration_sec=3600,
        exclude_from_recovery=False,
        raw_summary={},
    )
    session.add(activity)
    await session.flush()
    return Analysis(
        user_id=user_id,
        activity_id=activity.id,
        analysis_type="post_workout",
        subject_date=day,
        generated_at_utc=datetime.combine(day, datetime.min.time()) + timedelta(hours=18),
        prompt_version="test",
        verdict=None,
        context_packet={
            "intervals": intervals,
            "plannedWorkoutIr": {"workoutType": workout_type},
            "postRideCheckIn": {"rpe": 6},
        },
        output_markdown="read",
        raw_response={},
    )


def _morning(user_id: uuid.UUID, day: date, colour: str) -> Analysis:
    return Analysis(
        user_id=user_id,
        activity_id=None,
        analysis_type="morning",
        subject_date=day,
        generated_at_utc=datetime.combine(day, datetime.min.time()) + timedelta(hours=7),
        prompt_version="test",
        verdict=colour,
        context_packet={"verdict": {"status": colour, "engine": "graded"}},
        output_markdown="brief",
        raw_response={},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("recovery_week_ahead", [True, False])
async def test_on_postgres_the_1_nov_review_holds_the_note(
    db_conn: AsyncConnection, recovery_week_ahead: bool
) -> None:
    async with AsyncSession(
        bind=db_conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
    ) as session:
        player = Profile(
            id=uuid.uuid4(),
            display_name=f"Progress Hold {uuid.uuid4().hex[:6]}",
            role=UserRole.admin,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(player)
        await session.flush()
        # Three clean key sessions with Green mornings after, as the note asks for.
        for day, intervals, kind in (
            (date(2026, 10, 27), [_interval(130)] * 22, "bike_vo2"),
            (date(2026, 10, 29), [_interval(89)] * 4, "bike_sweet_spot"),
            (date(2026, 10, 30), [_interval(89)] * 4, "bike_sweet_spot"),
            (date(2026, 10, 31), [_interval(185)] * 6, "bike_endurance"),
        ):
            session.add(await _ride(session, player.id, day, intervals, kind))
        for offset in range(5):
            session.add(_morning(player.id, date(2026, 10, 28) + timedelta(offset), "Green"))
        session.add(
            PlanBlock(
                user_id=player.id,
                name="Week 4",
                block_type="recovery" if recovery_week_ahead else "build",
                start_date=date(2026, 11, 2),
                end_date=date(2026, 11, 8),
                goals_json={},
            )
        )
        await session.flush()
        signal = await ReviewService(session)._progress_signal(player.id, REVIEW_DAY)

    assert [s["date"] for s in signal["hardWork"]["sessions"]] == [
        "2026-10-27",
        "2026-10-29",
        "2026-10-30",
    ]
    if recovery_week_ahead:
        assert (signal["readyToProgress"], signal["note"], signal["heldBecause"]) == (
            False,
            None,
            HOLD_LIGHT_WEEK,
        )
    else:
        # A build week ahead, no test near: the note is due.
        assert (signal["readyToProgress"], signal["note"]) == (True, READY_NOTE)


@pytest.mark.asyncio
async def test_on_postgres_a_planned_test_within_four_weeks_holds_the_note(
    db_conn: AsyncConnection,
) -> None:
    async with AsyncSession(
        bind=db_conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
    ) as session:
        player = Profile(
            id=uuid.uuid4(),
            display_name=f"Progress Test {uuid.uuid4().hex[:6]}",
            role=UserRole.admin,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(player)
        await session.flush()
        session.add(
            PlannedWorkout(
                user_id=player.id,
                workout_date=REVIEW_DAY + timedelta(days=15),
                version=1,
                title="FTP Ramp Test",
                workout_type="bike_threshold",
                status="planned",
                is_active=True,
                planned_duration_min=30,
                structured_workout={"test": "ramp"},
                source="test",
            )
        )
        await session.flush()
        assert await ReviewService(session)._next_test(player.id, REVIEW_DAY) == (
            REVIEW_DAY + timedelta(days=15)
        )
