"""Batch 340: strength he can do and the app can see.

340.1 Dumbbells A and B reach his watch as Garmin strength workouts, on his tap (a fake
client: nothing is written to Garmin); 340.2 no loaded legs the day before VO2 or the test
in a generated plan, and each session says how long it really takes; 340.3 a small
bone-loading element; 340.4 the post-strength read sees what he lifted and tells lifting
from a circuit. Each failed on ``main`` first.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from src.models.coaching import PlannedWorkout
from src.models.profile import Profile, UserRole
from src.services import post_strength_analysis
from src.services.garmin_strength_export import (
    MOVES_A,
    MOVES_B,
    build_garmin_strength_workout,
    dose_from,
    moves_for,
)
from src.services.garmin_sync import GarminScheduledWorkout
from src.services.next_plan import (
    BONE_LINE,
    LEGS_LINE,
    OWN_ROUTINES_LINE,
    PLAN_NO_2_RHYTHM,
    WeeklyRhythm,
    _dose,
    legs_rested,
    strength,
    strength_minutes,
)
from src.services.post_strength_analysis import SESSION_LOAD_RULE, session_load
from src.services.strength_watch import StrengthWatchService, watch_name
from tests.test_batch_302_stored_morning import _savepoint_session

REPO = Path(__file__).resolve().parents[3]
DRAFT = REPO / "docs" / "drafts" / "2026-10-29-batch-340-wording.md"


# -- 340.2: legs are never loaded the day before VO2 or the test -----------------------------


def test_plan_no_2s_week_moves_the_legs_session_off_the_day_before_vo2() -> None:
    assert (PLAN_NO_2_RHYTHM.strength_a + 1) % 7 == PLAN_NO_2_RHYTHM.vo2  # Monday, Tuesday
    rested = legs_rested(PLAN_NO_2_RHYTHM)
    assert rested.strength_a == PLAN_NO_2_RHYTHM.sweet_spot  # Thursday, after the ride
    assert (rested.strength_a + 1) % 7 != rested.vo2
    assert rested.is_valid()


def test_a_week_already_clear_is_left_alone_and_a_swap_is_the_fallback() -> None:
    clear = WeeklyRhythm(strength_a=3, strength_b=5)
    assert legs_rested(clear) == clear
    # Sweet spot the day before VO2 too: the swap with B is what is left.
    tight = WeeklyRhythm(
        strength_a=0, vo2=1, zone2=2, sweet_spot=0, rest=4, sprints=5, strength_b=5, long_ride=6
    )
    assert tight.is_valid()
    swapped = legs_rested(tight)
    assert (swapped.strength_a, swapped.strength_b) == (5, 0)


def test_each_session_says_how_long_it_really_takes() -> None:
    assert strength_minutes("3 × 12") == 40  # B, the longer: eight moves
    assert strength_minutes("4 × 8 on the first three moves, 3 × 8 on the rest") >= 30
    assert strength_minutes("2 × 12") < strength_minutes("3 × 12")
    session = strength(_dose("3 × 12", "2 reps in reserve"), session="A")
    assert session.minutes == 25  # the table's planned minutes, Craig's call to change
    assert "about 40 minutes in all" in session.structured_workout["summary"]


# -- 340.3: a little impact, graded to its evidence ------------------------------------------


def test_the_legs_session_ends_with_low_hops() -> None:
    summary = strength(_dose("3 × 10", "2 reps in reserve"), session="A").structured_workout
    assert "low hops (2 × 10, soft landings)" in summary["summary"]
    assert MOVES_A[-1].category == "PLYO" and MOVES_A[-1].fixed_sets == 2
    assert "modest" in BONE_LINE  # the evidence, said plainly


# -- 340.1: his watch -------------------------------------------------------------------------


def test_a_dumbbell_session_is_a_garmin_strength_workout_of_its_sets() -> None:
    payload = build_garmin_strength_workout(
        name="Dumbbells A · Mon 02 Nov",
        moves=MOVES_A,
        intensity_target="Dumbbells 4 × 8 on the first three moves, 3 × 8 on the rest",
    )
    assert payload["sportType"]["sportTypeKey"] == "strength_training"
    groups = payload["workoutSegments"][0]["workoutSteps"]
    assert len(groups) == len(MOVES_A)
    assert [group["numberOfIterations"] for group in groups] == [4, 4, 4, 3, 3, 3, 2]
    squat, rest = groups[0]["workoutSteps"]
    assert (squat["category"], squat["exerciseName"], squat["endConditionValue"]) == (
        "SQUAT",
        "GOBLET_SQUAT",
        8,
    )
    assert rest["stepType"]["stepTypeKey"] == "rest"
    plank = groups[5]["workoutSteps"][0]
    assert plank["endCondition"]["conditionTypeKey"] == "time"
    assert dose_from("Dumbbells 3 × 6–8") == (3, 3, 8)
    assert moves_for("Dumbbells B (upper body)") is MOVES_B
    assert moves_for("Daily Bodyweight Workout") is None


class _FakeGarmin:
    def __init__(self, names: set[str], fail: str | None = None) -> None:
        self.names = names
        self.fail = fail
        self.uploads: list[tuple[str, date]] = []

    def workout_names(self) -> set[str]:
        return set(self.names)

    def upload_and_schedule_workout(
        self, workout_json: dict[str, object], calendar_date: date
    ) -> GarminScheduledWorkout:
        name = str(workout_json["workoutName"])
        if name == self.fail:
            raise RuntimeError("Garmin said no")
        self.uploads.append((name, calendar_date))
        self.names.add(name)
        return GarminScheduledWorkout(workout_id="w1", schedule_id="s1", raw={})


@pytest.mark.asyncio
async def test_on_postgres_one_tap_puts_this_weeks_a_and_b_on_his_watch_once(
    db_conn: AsyncConnection,
) -> None:
    today = date(2026, 11, 2)
    async with _savepoint_session(db_conn) as session:
        player = Profile(
            id=uuid.uuid4(),
            display_name="Strength",
            role=UserRole.admin,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(player)
        await session.flush()
        for offset, title in (
            (0, "Dumbbells A (legs and back)"),
            (5, "Dumbbells B (upper body)"),
            (9, "Dumbbells A (legs and back)"),
            (1, "VO2 Max 30/30"),
        ):
            session.add(
                PlannedWorkout(
                    user_id=player.id,
                    workout_date=today + timedelta(days=offset),
                    version=1,
                    title=title,
                    workout_type="strength_maintenance" if "Dumbbells" in title else "bike_vo2",
                    status="planned",
                    is_active=True,
                    planned_duration_min=25,
                    intensity_target="Dumbbells 3 × 10",
                    structured_workout={"format": "strength"},
                    source="test",
                )
            )
        await session.commit()

        fake = _FakeGarmin(names={"Dumbbell Workout"})
        first = await StrengthWatchService(session).put_on_watch(player, today=today, client=fake)
        assert first.placed == ["Dumbbells A · Mon 02 Nov", "Dumbbells B · Sat 07 Nov"]
        assert [day for _name, day in fake.uploads] == [today, today + timedelta(days=5)]
        # A second tap uploads nothing: both are already in his Garmin library.
        again = await StrengthWatchService(session).put_on_watch(player, today=today, client=fake)
        assert (again.placed, len(again.already_there)) == ([], 2)
        # A failure is reported, never hidden.
        failing = _FakeGarmin(names=set(), fail="Dumbbells B · Sat 07 Nov")
        reported = await StrengthWatchService(session).put_on_watch(
            player, today=today, client=failing
        )
        assert reported.failed == ["Dumbbells B · Sat 07 Nov"]


def test_the_watch_name_carries_the_day() -> None:
    row = PlannedWorkout(title="Dumbbells A (legs and back)", workout_date=date(2026, 11, 2))
    assert watch_name(row) == "Dumbbells A · Mon 02 Nov"


# -- 340.4: what he lifted ---------------------------------------------------------------------


def test_the_read_tells_a_lifting_session_from_a_circuit() -> None:
    lifting = session_load(
        "Dumbbell Workout",
        [
            {
                "category": "SHOULDER_PRESS",
                "subCategory": "DUMBBELL_SHOULDER_PRESS",
                "sets": 3,
                "reps": 30,
                "maxWeight": 0,
            },
            {"category": "CARDIO", "sets": 1, "reps": 0, "maxWeight": 0},
        ],
    )
    assert lifting["kind"] == "lifting"
    assert [item["exercise"] for item in lifting["exercises"]] == ["DUMBBELL_SHOULDER_PRESS"]
    assert lifting["weightsRecorded"] is False
    circuit = session_load(
        "Daily Bodyweight Workout", [{"category": "PUSH_UP", "sets": 2, "reps": 20}]
    )
    assert circuit["kind"] == "circuit"
    assert "movement maintenance, never strength building" in SESSION_LOAD_RULE
    assert SESSION_LOAD_RULE in post_strength_analysis.SYSTEM_PROMPT
    assert post_strength_analysis.PROMPT_VERSION == "post-strength-analysis-v8-2026-10-29"


# -- the words ---------------------------------------------------------------------------------


def test_every_new_line_is_in_the_draft() -> None:
    draft = DRAFT.read_text(encoding="utf-8")
    for words in (BONE_LINE, OWN_ROUTINES_LINE, LEGS_LINE.split("{day}")[0]):
        assert words in draft, words


def test_no_generated_week_loads_his_legs_the_day_before_vo2_or_the_test() -> None:
    from datetime import UTC, datetime

    from src.services.next_plan import next_plan_draft

    plan = next_plan_draft(
        start_date=date(2026, 11, 2),
        ftp_watts=280,
        athlete_name="Mark",
        generated_at_utc=datetime(2026, 10, 29, tzinfo=UTC).replace(tzinfo=None),
        rhythm=legs_rested(PLAN_NO_2_RHYTHM),
    )
    for week in plan["weeks"]:
        workouts = week["workouts"]
        legs = {w["workoutDate"] for w in workouts if str(w["title"]).startswith("Dumbbells A")}
        hard = {
            w["workoutDate"]
            for w in workouts
            if w.get("workoutType") == "bike_vo2" or "ramp" in str(w["title"]).lower()
        }
        for day in legs:
            assert (date.fromisoformat(day) + timedelta(days=1)).isoformat() not in hard
    assert LEGS_LINE.split(" is on")[0] in " ".join(plan["whyThisPlan"])
