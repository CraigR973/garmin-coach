"""Batch 384 — tomorrow's planned sessions reach the morning brief.

The brief was given only the day's own sessions, so a check-in asking about swapping today's
ride with tomorrow's could not be answered from it (7 Nov). The packet gains
``tomorrowsPlannedWorkouts`` in the shape of ``plannedWorkouts``. Every title and figure here
is invented.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from src.models.coaching import DailyMetric, PlannedWorkout, Sleep
from src.models.profile import Profile, UserRole
from src.services.brief_check import MISS_INTERNAL_WORDS, check_brief
from src.services.coach_policy import facts_missing_basis
from src.services.internal_words import internal_words, known_names
from src.services.morning_analysis import MorningAnalysisService
from tests.test_batch_318_brief_leads import GOOD, PACKET

DAY = date(2026, 3, 4)  # a Wednesday, inside no plan block of its own


def _session(user_id: uuid.UUID, day: date, title: str, **fields: Any) -> PlannedWorkout:
    values: dict[str, Any] = {
        "user_id": user_id,
        "workout_date": day,
        "version": 1,
        "title": title,
        "workout_type": "bike_endurance",
        "status": "planned",
        "is_active": True,
        "planned_duration_min": 90,
        "intensity_target": "Zone 2",
        "structured_workout": {"format": "bike"},
        "source": "today_card_swap",
    }
    values.update(fields)
    return PlannedWorkout(**values)


async def _packet(
    db_conn: AsyncConnection, sessions: list[tuple[date, str, dict[str, Any]]]
) -> dict[str, Any]:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()
    async with session_factory() as session:
        player = Profile(
            id=user_id,
            display_name=f"Tomorrow Test {user_id.hex[:8]}",
            role=UserRole.admin,
            timezone="Europe/London",
            latitude=55.6045,
            longitude=-4.5249,
            is_active=True,
        )
        session.add(player)
        await session.flush()
        session.add_all(
            [
                DailyMetric(
                    user_id=user_id,
                    calendar_date=DAY,
                    recorded_at_utc=datetime(2026, 3, 4, 6, 20),
                    readiness_score=70,
                    readiness_level="Good",
                    hrv_weekly_avg_ms=50,
                    hrv_status="Balanced",
                    hrv_baseline_low_ms=43,
                    hrv_baseline_high_ms=57,
                    resting_heart_rate_bpm=45,
                    raw_payload={},
                ),
                Sleep(
                    user_id=user_id,
                    calendar_date=DAY,
                    score=80,
                    raw_payload={},
                    factors_json={},
                ),
                *[_session(user_id, day, title, **extra) for day, title, extra in sessions],
            ]
        )
        await session.commit()
        return await MorningAnalysisService(session).assemble_context_packet(player, DAY)


async def test_the_packet_carries_the_next_days_sessions_in_todays_shape(
    db_conn: AsyncConnection,
) -> None:
    packet = await _packet(
        db_conn,
        [
            (DAY, "Invented steady ride", {}),
            (DAY + timedelta(days=1), "Invented long ride", {"planned_duration_min": 150}),
            (DAY + timedelta(days=2), "Invented day-after ride", {}),
            (
                DAY + timedelta(days=1),
                "Invented withdrawn ride",
                {"is_active": False, "version": 2},
            ),
        ],
    )

    (today,) = packet["plannedWorkouts"]
    (tomorrow,) = packet["tomorrowsPlannedWorkouts"]
    assert today["title"] == "Invented steady ride"
    assert tomorrow["title"] == "Invented long ride"
    assert tomorrow["workoutDate"] == (DAY + timedelta(days=1)).isoformat()
    assert tomorrow["plannedDurationMin"] == 150
    # The same shape, including the plain-words basis for where the session came from.
    assert set(tomorrow) == set(today)
    assert tomorrow["basis"] == today["basis"]


async def test_no_session_tomorrow_is_an_empty_list_not_a_missing_key(
    db_conn: AsyncConnection,
) -> None:
    packet = await _packet(db_conn, [(DAY, "Invented steady ride", {})])
    assert packet["tomorrowsPlannedWorkouts"] == []


async def test_a_session_tomorrow_does_not_move_todays_colour_or_plan(
    db_conn: AsyncConnection,
) -> None:
    """Context for a question only: today's colour, today's sessions and the rest-day
    reading are the same with and without a session tomorrow. (The week's counts do move,
    as they always did: they count the whole week's plan.)"""
    without = await _packet(db_conn, [(DAY, "Invented steady ride", {})])
    with_tomorrow = await _packet(
        db_conn,
        [
            (DAY, "Invented steady ride", {}),
            (DAY + timedelta(days=1), "Invented hard ride", {"workout_type": "bike_vo2"}),
        ],
    )
    assert with_tomorrow["verdict"]["status"] == without["verdict"]["status"]
    assert with_tomorrow["verdict"]["graded"]["status"] == without["verdict"]["graded"]["status"]
    assert with_tomorrow["restDay"] == without["restDay"]
    assert [row["title"] for row in with_tomorrow["plannedWorkouts"]] == [
        row["title"] for row in without["plannedWorkouts"]
    ]
    assert without["tomorrowsPlannedWorkouts"] == []
    assert len(with_tomorrow["tomorrowsPlannedWorkouts"]) == 1


def test_tomorrows_sessions_must_say_how_they_reached_the_calendar() -> None:
    bare = {"tomorrowsPlannedWorkouts": [{"title": "Z2", "source": "today_card_swap"}]}
    assert facts_missing_basis(bare) == ("tomorrows_planned_workout",)
    said = {"tomorrowsPlannedWorkouts": [{"title": "Z2", "basis": "imported from your plan"}]}
    assert facts_missing_basis(said) == ()
    assert facts_missing_basis({"tomorrowsPlannedWorkouts": []}) == ()


# -- 382's check would catch the new name if it ever reached a written brief -------------------

KEYED_PACKET: dict[str, Any] = {**PACKET, "tomorrowsPlannedWorkouts": [{"title": "Z2"}]}


def test_the_new_field_name_is_one_the_internal_word_check_knows() -> None:
    assert "tomorrowsPlannedWorkouts" in known_names(KEYED_PACKET)
    found = internal_words("Looking at tomorrowsPlannedWorkouts, a ride is on.", KEYED_PACKET)
    assert found.names == ("tomorrowsPlannedWorkouts",)


def test_a_written_brief_that_names_the_field_fails_the_brief_check() -> None:
    leaky = GOOD.replace(
        "the session is on as written.",
        "the session is on as written. Per tomorrowsPlannedWorkouts there is a ride tomorrow.",
    )
    check = check_brief(KEYED_PACKET, leaky)
    assert MISS_INTERNAL_WORDS in check.misses
    assert check.internal_words == ("tomorrowsPlannedWorkouts",)
    assert MISS_INTERNAL_WORDS not in check_brief(KEYED_PACKET, GOOD).misses
