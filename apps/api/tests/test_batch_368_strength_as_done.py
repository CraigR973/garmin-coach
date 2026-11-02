"""Batch 368 — strength he does, recorded as he does it.

On 21 and 26 Oct 2026 "Dumbbells A (legs and back)" was completed by his own upper-body
"Dumbbell Workout" (shoulder press, flye, lateral raise, row, curl, triceps): two weeks with
no leg session, recorded and reported as done (FC360-01). The plan asked for "one weight up"
three times with 5 and 10 kg dumbbells (FC360-02); the strength numbers counted his circuits
as strength sessions (FC360-04); an off-the-bike morning left loaded legs as planned
(FC360-05 = CI359-04); and the watch push kept no record (FC360-07).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.models.coaching import Activity, Analysis, PlannedWorkout
from src.models.profile import Profile, UserRole
from src.services.garmin_sync import GarminScheduledWorkout
from src.services.morning_verdict import (
    BIKE_REST_MOBILITY_LINE,
    BIKE_REST_PLAN_LINE,
    FEVER_MOBILITY_LINE,
    MOBILITY_INSTEAD_LINE,
    graded_plan_adjustments,
)
from src.services.next_plan import DUMBBELLS_KG, WEEKS
from src.services.strength_brief import StrengthSession, compute_strength_rollup
from src.services.strength_watch import (
    AUDIT_TYPE,
    STATUS_PLACED,
    STATUS_REMOVED,
    StrengthWatchService,
    watch_name_for,
)
from src.services.verdict_grading import (
    ACTION_MOBILITY_INSTEAD,
    FLOOR_BIKE_REST,
    GradedVerdict,
    SessionAction,
    _session_action,
    classify_session,
)
from src.services.workout_match import strength_material_difference

REPO = Path(__file__).resolve().parents[3]
DRAFT = REPO / "docs" / "drafts" / "2026-11-02-batch-368-wording.md"

UPPER_BODY_ROUTINE = ["CARDIO", "CURL", "FLYE", "LATERAL_RAISE", "PLANK", "ROW",
                      "SHOULDER_PRESS", "TRICEPS_EXTENSION"]  # fmt: skip
CIRCUIT = ["BANDED_EXERCISES", "CARDIO", "HIP_STABILITY", "PLANK", "PUSH_UP", "SQUAT"]
WATCH_A = ["CALF_RAISE", "DEADLIFT", "LUNGE", "PLANK", "ROW", "SQUAT"]  # 2 Nov, from the watch


def _planned(title: str, summary: str = "") -> PlannedWorkout:
    return PlannedWorkout(
        id=uuid.uuid4(),
        title=title,
        workout_type="strength_maintenance",
        intensity_target="Dumbbells 3 × 10",
        structured_workout={"summary": summary, "steps": []},
        status="planned",
    )


def _activity(name: str, categories: list[str] | None) -> Activity:
    summary: dict[str, Any] = {}
    if categories is not None:
        summary["summarizedExerciseSets"] = [{"category": item} for item in categories]
    return Activity(id=uuid.uuid4(), activity_name=name, raw_summary=summary)


# -- 368.1: the matcher reads the exercises -----------------------------------------------


def test_his_upper_body_routine_never_completes_dumbbells_a() -> None:
    """21 and 26 Oct's shape: the same modality by name, none of A's exercises."""
    a = _planned("Dumbbells A (legs and back)")
    deviation = strength_material_difference(a, _activity("Dumbbell Workout", UPPER_BODY_ROUTINE))
    assert deviation is not None and deviation["kind"] == "exercise_mismatch"
    assert deviation["prescribed"]["signature"] == ["DEADLIFT", "LUNGE"]


def test_a_circuit_never_completes_a_and_its_squat_is_not_enough() -> None:
    a = _planned("Dumbbells A (legs and back)")
    # By name (Batch 278) and, named neutrally, by its exercises: SQUAT alone is the circuit's.
    assert strength_material_difference(a, _activity("Daily Bodyweight Workout", CIRCUIT))
    assert strength_material_difference(a, _activity("Strength", CIRCUIT)) is not None


def test_the_real_dumbbells_a_completes_a_with_or_without_its_hops() -> None:
    hops = "… side plank (30 s each side), low hops (2 × 10, soft landings). 3 × 10 …"
    for row in (
        _planned("Dumbbells A (legs and back)"),
        _planned("Dumbbells A (legs and back)", hops),
    ):
        assert (
            strength_material_difference(row, _activity("Dumbbells A · Thu 12 Nov", WATCH_A))
            is None
        )


def test_b_is_completed_by_a_press_and_a_session_with_no_exercises_is_left_alone() -> None:
    b = _planned("Dumbbells B (upper body)")
    assert (
        strength_material_difference(b, _activity("Dumbbell Workout", UPPER_BODY_ROUTINE)) is None
    )
    assert strength_material_difference(b, _activity("Dumbbell Workout", ["SQUAT", "LUNGE"]))
    a = _planned("Dumbbells A (legs and back)")
    assert strength_material_difference(a, _activity("Dumbbell Workout", None)) is None
    # Any other strength session has no signature to check.
    other = _planned("Strength Maintenance")
    assert strength_material_difference(other, _activity("Dumbbell Workout", CIRCUIT)) is None


# -- 368.2: progress within his kit --------------------------------------------------------


def test_the_plan_never_asks_for_a_weight_he_does_not_have() -> None:
    assert DUMBBELLS_KG == (5, 10)
    doses = " ".join(f"{week.strength}" for week in WEEKS).lower()
    assert "one weight up" not in doses
    assert "easier weight" not in doses
    assert "10 kg" in doses and "lower each rep over 3 seconds" in doses
    assert "harder version" in doses


# -- 368.3: circuits counted apart ----------------------------------------------------------


def test_the_rollup_counts_loaded_sessions_and_circuits_apart() -> None:
    as_of = date(2026, 11, 1)

    def session(name: str, days_ago: int) -> StrengthSession:
        return StrengthSession(uuid.uuid4(), name, "strength_training",
                               as_of - timedelta(days=days_ago), 12, None)  # fmt: skip

    rollup = compute_strength_rollup(
        [session("Daily Bodyweight Workout", n) for n in (1, 3, 5, 8, 10, 12, 15)]
        + [session("Dumbbell Workout", 6), session("Dumbbells A · Mon 02 Nov", 0)],
        as_of_date=as_of,
    )
    window = rollup.window_4w
    assert (window.session_count, window.loaded_sessions, window.circuit_sessions) == (9, 2, 7)


# -- 368.4: an off-the-bike morning loads no legs -----------------------------------------


def _strength_session() -> Any:
    return classify_session(
        session_id="a", title="Dumbbells A (legs and back)", workout_type="strength_maintenance",
        planned_minutes=30, ir=None,
    )  # fmt: skip


def _verdict(**fields: Any) -> GradedVerdict:
    base: dict[str, Any] = {
        "status": "Amber", "held": False, "domains": (), "floor": None, "reasons": ()
    }  # fmt: skip
    return GradedVerdict(**(base | fields))


def test_on_an_off_the_bike_morning_loaded_strength_is_mobility() -> None:
    verdict = _verdict(floor=FLOOR_BIKE_REST)
    action, _reason = _session_action(verdict, _strength_session(), False)
    assert action == ACTION_MOBILITY_INSTEAD


WORKOUT_ID = uuid.uuid4()


def _plan_lines(verdict: GradedVerdict, acute: dict[str, Any]) -> list[str]:
    workout = PlannedWorkout(
        id=WORKOUT_ID, title="Dumbbells A (legs and back)",
        workout_type="strength_maintenance", status="planned",
    )  # fmt: skip
    return graded_plan_adjustments(
        verdict, [workout], is_rest_day=False, acute=acute, has_vo2=False
    )


def test_each_mobility_swap_says_its_own_reason() -> None:
    mobility = (
        SessionAction(
            session_id=str(WORKOUT_ID), title="Dumbbells A",
            workout_type="strength_maintenance",
            is_key=False, is_hard=False, action=ACTION_MOBILITY_INSTEAD, detail="",
        ),
    )  # fmt: skip
    bike_rest = _verdict(floor=FLOOR_BIKE_REST, actions=mobility)
    assert _plan_lines(bike_rest, {"requiresBikeRest": True}) == [
        BIKE_REST_PLAN_LINE,
        BIKE_REST_MOBILITY_LINE,
    ]
    fever = _verdict(easing="fever_follow_up", actions=mobility)
    chest = _verdict(easing="chest_follow_up", actions=mobility)
    assert FEVER_MOBILITY_LINE in _plan_lines(fever, {})
    assert MOBILITY_INSTEAD_LINE in _plan_lines(chest, {})


# -- 368.5: the watch keeps a record, and a moved session leaves one copy --------------------


class _FakeWatch:
    def __init__(self) -> None:
        self.names: set[str] = set()
        self.uploads: list[tuple[str, date]] = []
        self.deleted: list[tuple[str | None, str | None]] = []

    def workout_names(self) -> set[str]:
        return set(self.names)

    def upload_and_schedule_workout(
        self, workout_json: dict[str, object], calendar_date: date
    ) -> GarminScheduledWorkout:
        name = str(workout_json["workoutName"])
        self.names.add(name)
        self.uploads.append((name, calendar_date))
        return GarminScheduledWorkout(
            workout_id=f"w-{len(self.uploads)}", schedule_id=f"s-{len(self.uploads)}", raw={}
        )

    def delete_scheduled_workout(self, workout_id: str | None, schedule_id: str | None) -> None:
        self.deleted.append((workout_id, schedule_id))


@pytest.mark.asyncio
async def test_on_postgres_each_upload_is_recorded_and_a_moved_session_comes_off_the_watch(
    db_conn: AsyncConnection,
) -> None:
    monday = date(2026, 8, 3)
    async with AsyncSession(
        bind=db_conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
    ) as session:
        player = Profile(
            id=uuid.uuid4(), display_name=f"Watch {uuid.uuid4().hex[:6]}",
            role=UserRole.admin, timezone="Europe/London", is_active=True,
        )  # fmt: skip
        session.add(player)
        await session.flush()
        a_monday = PlannedWorkout(
            user_id=player.id, workout_date=monday, version=1,
            title="Dumbbells A (legs and back)", workout_type="strength_maintenance",
            status="planned", is_active=True, planned_duration_min=35,
            intensity_target="Dumbbells 3 × 10",
            structured_workout={"summary": "Goblet squat … 3 × 10."}, source="test",
        )  # fmt: skip
        session.add(a_monday)
        await session.commit()
        watch = _FakeWatch()
        service = StrengthWatchService(session)

        first = await service.put_on_watch(player, today=monday, client=watch)
        assert first.placed == [watch_name_for("Dumbbells A (legs and back)", monday)]

        # He moves A to Thursday: the Monday row goes inactive, a Thursday row appears.
        thursday = monday + timedelta(days=3)
        a_monday.is_active = False
        session.add(
            PlannedWorkout(
                user_id=player.id,
                workout_date=thursday,
                version=2,
                title="Dumbbells A (legs and back)",
                workout_type="strength_maintenance",
                status="planned",
                is_active=True,
                planned_duration_min=35,
                intensity_target="Dumbbells 3 × 10",
                structured_workout={"summary": "Goblet squat … 3 × 10."},
                source="test",
            )  # fmt: skip
        )
        await session.commit()
        second = await service.put_on_watch(player, today=monday, client=watch)
        rows = (
            (
                await session.execute(
                    select(Analysis.context_packet).where(
                        Analysis.user_id == player.id, Analysis.analysis_type == AUDIT_TYPE
                    )
                )
            )
            .scalars()
            .all()
        )

    assert second.removed == [watch_name_for("Dumbbells A (legs and back)", monday)]
    assert watch.deleted == [("w-1", "s-1")]
    assert second.placed == [watch_name_for("Dumbbells A (legs and back)", thursday)]
    statuses = sorted(row["status"] for row in rows)
    assert statuses == [STATUS_PLACED, STATUS_PLACED, STATUS_REMOVED]


# -- 368.6: the words ------------------------------------------------------------------------


def test_every_new_line_is_in_the_draft() -> None:
    from src.services.next_plan import HARDER_VERSIONS

    draft = " ".join(DRAFT.read_text(encoding="utf-8").replace("\n> ", " ").split())
    for words in (
        BIKE_REST_MOBILITY_LINE,
        FEVER_MOBILITY_LINE,
        "light: stop each set with 3–4 reps in reserve",
        "the 10 kg dumbbells if 5 kg felt easy in week 2; 2 reps in reserve",
        "the same weight; lower each rep over 3 seconds",
        f"{HARDER_VERSIONS}; 2 reps in reserve",
        "the harder versions, lowering over 3 seconds; 1–2 reps in reserve",
    ):
        assert " ".join(words.split()) in draft, words
