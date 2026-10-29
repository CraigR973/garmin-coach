"""Dumbbells A and B as Garmin strength workouts, for his watch (Batch 340, FC331-01).

Mark lifts from named Garmin watch workouts (Decision #108 withdrew the in-app players for
that reason), and Plan No. 3's two dumbbell sessions had no route there: the delivery rail
is bike-only, so the legs session would be skipped and his old upper-body routine ticked
in its place. This builds a Garmin strength-training workout from a plan row: each move a
repeat of its sets, each set a reps step (or a timed hold) and a rest.

The exercise ids are Garmin's categories as his own recordings name them
(``summarizedExerciseSets``: SQUAT, DEADLIFT, LUNGE, ROW, CALF_RAISE, PLANK, SHOULDER_PRESS,
...). **Provisional:** a move whose exact Garmin exercise name is not on record carries its
category only; the first real upload, on Craig's go, confirms them. Pure and DB-free, like
``garmin_workout_export``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Final

SPORT_TYPE_STRENGTH: Final = {
    "sportTypeId": 5,
    "sportTypeKey": "strength_training",
    "displayOrder": 5,
}
_STEP_INTERVAL: Final = {"stepTypeId": 3, "stepTypeKey": "interval", "displayOrder": 3}
_STEP_REST: Final = {"stepTypeId": 5, "stepTypeKey": "rest", "displayOrder": 5}
_STEP_REPEAT: Final = {"stepTypeId": 6, "stepTypeKey": "repeat", "displayOrder": 6}
_END_REPS: Final = {"conditionTypeId": 10, "conditionTypeKey": "reps", "displayOrder": 10}
_END_TIME: Final = {"conditionTypeId": 2, "conditionTypeKey": "time", "displayOrder": 2}
_END_ITERATIONS: Final = {
    "conditionTypeId": 7,
    "conditionTypeKey": "iterations",
    "displayOrder": 7,
}
REST_SECONDS: Final = 60
_MAX_NAME_LEN: Final = 80


@dataclass(frozen=True, slots=True)
class Move:
    """One move of a dumbbell session, as Garmin names it."""

    label: str
    category: str
    exercise_name: str | None = None
    #: A timed hold in seconds instead of reps (the side plank).
    hold_seconds: int | None = None
    #: Fixed reps whatever the week's dose (the hops).
    fixed_reps: int | None = None
    fixed_sets: int | None = None


#: Plan No. 3's sessions (``next_plan._STRENGTH_A_MOVES`` / ``_STRENGTH_B_MOVES``).
MOVES_A: Final[tuple[Move, ...]] = (
    Move("Goblet squat", "SQUAT", "GOBLET_SQUAT"),
    Move("Romanian deadlift", "DEADLIFT", "DUMBBELL_ROMANIAN_DEADLIFT"),
    Move("Reverse lunge (each leg)", "LUNGE"),
    Move("One-arm row (each arm)", "ROW", "ONE_ARM_BENT_OVER_ROW"),
    Move("Calf raise", "CALF_RAISE"),
    Move("Side plank (30 s each side)", "PLANK", "SIDE_PLANK", hold_seconds=60),
    Move("Low hops, soft landings", "PLYO", fixed_reps=10, fixed_sets=2),
)
MOVES_B: Final[tuple[Move, ...]] = (
    Move("Shoulder press", "SHOULDER_PRESS", "DUMBBELL_SHOULDER_PRESS"),
    Move("Reverse-grip row", "ROW"),
    Move("Floor press", "BENCH_PRESS"),
    Move("Pullover", "FLYE"),
    Move("Curl", "CURL"),
    Move("Triceps extension", "TRICEPS_EXTENSION"),
    Move("Step-up (each leg)", "LUNGE"),
    Move("Dead bug", "CORE"),
)


def moves_for(title: str | None) -> tuple[Move, ...] | None:
    """A or B from the plan row's title, or ``None`` for any other strength session."""

    lowered = (title or "").lower()
    if lowered.startswith("dumbbells a"):
        return MOVES_A
    if lowered.startswith("dumbbells b"):
        return MOVES_B
    return None


def dose_from(intensity_target: str | None) -> tuple[int, int, int]:
    """``(sets on the first three moves, sets on the rest, reps)`` from "Dumbbells 3 × 10"."""

    found = re.findall(r"(\d+) × (\d+)(?:–(\d+))?", intensity_target or "")
    if not found:
        raise ValueError(f"no sets and reps in {intensity_target!r}")
    first_sets, low, high = found[0]
    rest_sets = found[1][0] if len(found) > 1 else first_sets
    return int(first_sets), int(rest_sets), int(high or low)


def _step(order: int, move: Move, reps: int) -> dict[str, Any]:
    step: dict[str, Any] = {
        "type": "ExecutableStepDTO",
        "stepOrder": order,
        "stepType": _STEP_INTERVAL,
        "description": move.label,
        "category": move.category,
        "exerciseName": move.exercise_name,
    }
    if move.hold_seconds is not None:
        step.update({"endCondition": _END_TIME, "endConditionValue": move.hold_seconds})
    else:
        step.update({"endCondition": _END_REPS, "endConditionValue": reps})
    return step


def build_garmin_strength_workout(
    *, name: str, moves: tuple[Move, ...], intensity_target: str | None
) -> dict[str, Any]:
    """A Garmin strength-training workout: each move its sets of reps, each set a rest."""

    first_sets, rest_sets, reps = dose_from(intensity_target)
    steps: list[dict[str, Any]] = []
    order = 0
    for index, move in enumerate(moves):
        sets = move.fixed_sets or (first_sets if index < 3 else rest_sets)
        order += 1
        group_order = order
        order += 1
        work = _step(order, move, move.fixed_reps or reps)
        order += 1
        rest = {
            "type": "ExecutableStepDTO",
            "stepOrder": order,
            "stepType": _STEP_REST,
            "endCondition": _END_TIME,
            "endConditionValue": REST_SECONDS,
        }
        steps.append(
            {
                "type": "RepeatGroupDTO",
                "stepOrder": group_order,
                "stepType": _STEP_REPEAT,
                "numberOfIterations": sets,
                "endCondition": _END_ITERATIONS,
                "endConditionValue": sets,
                "smartRepeat": False,
                "workoutSteps": [work, rest],
            }
        )
    return {
        "workoutName": name[:_MAX_NAME_LEN],
        "sportType": SPORT_TYPE_STRENGTH,
        "workoutSegments": [
            {"segmentOrder": 1, "sportType": SPORT_TYPE_STRENGTH, "workoutSteps": steps}
        ],
    }
