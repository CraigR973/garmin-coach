"""Batch 336.2 — a test is ridden as planned or moved, never eased or picked (CI330-03).

On a tired morning the engine eased the ramp test (every step above 75% down 13 points,
capped at 94%) or offered it as easy Zone 2 or tempo. Ridden that way to "the step you
can't hold", the test gives a meaningless FTP (197 W on his numbers), and the plan's
targets for the next block are set from it. Coaching practice is to test fresh or move
the test, so a test session's actions are now:

* **as planned** on a Green morning;
* **move it** (``move_test``: move it to a fresher day this week, otherwise ride it as
  planned) wherever the engine would have eased, picked or held it: Amber, a tired
  Amber, Green with the targets held, and a planned light week;
* Red, the floors and what follows a symptom are unchanged. They replace hard work on
  a day it is ruled out (Red-never-VO2), which is not an eased test.

From now on only: graded mornings store ``references.testMovedNotEased``; a morning
stored before it replays without the rule.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest

from src.services.morning_verdict import GRADED_TEST_MOVE_LINE, graded_plan_adjustments
from src.services.todays_call import (
    LOOK_ADJUST,
    STATE_TEST_DAY,
    TEST_DAY,
    TEST_DAY_LINE,
    todays_call,
)
from src.services.verdict_grading import (
    ACTION_MOVE_TEST,
    RIDE_TRANSFORMS,
    classify_planned_workout,
    classify_session,
    grade,
    ride_transform,
)
from src.services.verdict_replay import (
    FORCEABLE_RULES,
    RULE_FLAGS,
    _planned_workouts_from_packet,
    _with_rules,
    _without_rules,
)
from tests.test_batch_295_verdict_grading import Z2, _inputs

RAMP_STEPS = [
    {"durationSec": 60, "powerStartPct": 50 + 6 * i, "powerEndPct": 50 + 6 * i} for i in range(17)
]

TEST = classify_session(
    session_id="test",
    title="FTP Ramp Test",
    workout_type="bike_threshold",
    planned_minutes=40,
    ir={"steps": RAMP_STEPS},
    is_test=True,
)
#: The same ride, not marked as a test: what every other hard session still gets.
HARD = replace(TEST, id="hard", title="Hard", is_test=False)


def _action(inputs: Any, session_id: str = "test") -> str:
    [action] = [a for a in grade(inputs).actions if a.session_id == session_id]
    return action.action


# -- the engine knows a test --------------------------------------------------------------


def test_a_plan_row_marked_as_a_test_classes_as_one() -> None:
    """The plan row marks a test only by its structured workout (``"test": "ramp"``)."""
    row = SimpleNamespace(
        id="row",
        title="FTP Ramp Test",
        workout_type="bike_threshold",
        planned_duration_min=40,
        structured_workout={"format": "bike", "test": "ramp", "steps": []},
        intensity_target="Ramp test",
    )
    assert classify_planned_workout(row).is_test is True
    assert classify_planned_workout(replace_row(row, structured_workout={})).is_test is False


def replace_row(row: SimpleNamespace, **changes: Any) -> SimpleNamespace:
    return SimpleNamespace(**{**vars(row), **changes})


# -- the actions --------------------------------------------------------------------------


def test_a_green_morning_rides_the_test_as_planned() -> None:
    assert _action(_inputs(sessions=(TEST, Z2))) == "as_planned"


@pytest.mark.parametrize(
    ("label", "kwargs", "before"),
    [
        ("Amber", {"week": 42.5}, "ease_hard"),
        ("tired Amber", {"sleep_score": 55}, "pick_zone2_or_tempo"),
        ("Green held", {"week": 44.5}, "move_or_hold"),
    ],
)
def test_a_test_is_moved_where_it_was_eased_picked_or_held(
    label: str, kwargs: dict[str, Any], before: str
) -> None:
    inputs = _inputs(sessions=(TEST, HARD), **kwargs)
    assert _action(inputs) == ACTION_MOVE_TEST, label
    # Any other hard session still takes the ordinary action.
    assert _action(inputs, "hard") == before
    # And a morning stored before the rule replays as it was.
    assert _action(replace(inputs, test_moved_not_eased=False)) == before


def test_a_light_week_moves_the_test_instead_of_holding_it() -> None:
    inputs = replace(
        _inputs(sessions=(TEST, HARD), week=44.5),
        recovery_class_block=True,
        light_week="taper",
    )
    assert _action(inputs) == ACTION_MOVE_TEST
    assert _action(inputs, "hard") == "hold_targets"


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        # Red: an easy spin replaces hard work (Red-never-VO2).
        ({"week": 42.5, "sleep_score": 55, "feel": 3}, "recovery"),
        # A floor: off the bike.
        ({"overnight": "illness"}, "off_the_bike"),
    ],
)
def test_red_and_the_floors_are_unchanged(kwargs: dict[str, Any], expected: str) -> None:
    inputs = _inputs(sessions=(TEST, Z2), **kwargs)
    assert _action(inputs) == expected
    assert _action(replace(inputs, test_moved_not_eased=False)) == expected


def test_moving_a_test_changes_nothing_on_zwift_until_he_moves_it() -> None:
    """No easing: the planned test stays on Zwift, and the swap offer moves it."""
    assert ACTION_MOVE_TEST not in RIDE_TRANSFORMS
    assert ride_transform("Amber", graded=True, action=ACTION_MOVE_TEST) is None


def test_the_detail_says_why() -> None:
    [action] = [a for a in grade(_inputs(sessions=(TEST,), week=42.5)).actions]
    assert action.detail == (
        "A test: ride it as planned or move it to a fresher day this week; ridden eased "
        "or tired it gives a false FTP."
    )


# -- the words ----------------------------------------------------------------------------


def _row(status: str = "planned") -> SimpleNamespace:
    return SimpleNamespace(
        id="test",
        title="FTP Ramp Test",
        workout_type="bike_threshold",
        status=status,
        planned_duration_min=40,
        structured_workout={"test": "ramp"},
    )


def test_the_plan_line_names_the_test() -> None:
    graded = grade(_inputs(sessions=(TEST,), week=42.5))
    lines = graded_plan_adjustments(
        graded,
        [_row()],
        acute={},
        is_rest_day=False,
        has_vo2=True,  # type: ignore[list-item]
    )
    assert GRADED_TEST_MOVE_LINE.format(title="FTP Ramp Test") in lines
    assert not any("Ease the hard intervals" in line for line in lines)


def _packet(action: str, status: str = "Amber") -> dict[str, Any]:
    return {
        "verdict": {
            "status": status,
            "engine": "graded",
            "graded": {
                "actions": [
                    {
                        "plannedWorkoutId": "test",
                        "workoutType": "bike_threshold",
                        "isHard": True,
                        "isKey": True,
                        "action": action,
                    }
                ]
            },
        },
        "plannedWorkouts": [{"id": "test", "status": "planned", "workoutType": "bike_threshold"}],
        "restDay": {"isRestDay": False, "insidePlanWeek": True},
    }


@pytest.mark.parametrize("status", ["Amber", "Green"])
def test_todays_call_is_the_test_day(status: str) -> None:
    call = todays_call(_packet(ACTION_MOVE_TEST, status))
    assert (call.state, call.key, call.headline, call.line, call.look) == (
        STATE_TEST_DAY,
        "test_day",
        TEST_DAY,
        TEST_DAY_LINE,
        LOOK_ADJUST,
    )


# -- from now on only ---------------------------------------------------------------------


def test_the_rule_is_stored_so_the_replay_grades_a_morning_as_it_was() -> None:
    inputs = _inputs(sessions=(TEST,))
    assert grade(inputs).references["testMovedNotEased"] is True
    stored_before = replace(inputs, test_moved_not_eased=False)
    assert grade(stored_before).references["testMovedNotEased"] is False


def test_the_replay_names_and_can_force_the_rule() -> None:
    assert RULE_FLAGS["test_moved_not_eased"] == "Batch 336, a test moved, never eased"
    assert "test_moved_not_eased" in FORCEABLE_RULES
    stored_before = replace(_inputs(sessions=(TEST,)), test_moved_not_eased=False)
    forced_on = _with_rules(stored_before, ["test_moved_not_eased"])
    assert forced_on.test_moved_not_eased is True
    assert _without_rules(forced_on, ["test_moved_not_eased"]).test_moved_not_eased is False


def test_the_replay_sees_a_test_in_a_stored_morning() -> None:
    """Stored packets carry the structured workout, so the replay knows a test (20 Oct)."""
    packet = {
        "plannedWorkouts": [
            {
                "id": str(uuid.uuid4()),
                "title": "FTP Ramp Test",
                "workoutType": "bike_threshold",
                "status": "planned",
                "version": 1,
                "plannedDurationMin": 40,
                "structuredWorkout": {"format": "bike", "test": "ramp", "steps": []},
            }
        ]
    }
    [row] = _planned_workouts_from_packet(date(2026, 10, 20), packet["plannedWorkouts"])
    assert classify_planned_workout(row).is_test is True
