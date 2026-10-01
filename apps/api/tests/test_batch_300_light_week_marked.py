"""Batch 300 — in a light week, only a mild concern holds the session.

Since Batch 296 a consolidation, taper, recovery or rest week held every bike session on
an Amber or held morning, so in W12 (5–11 Oct 2026) and W13 (12–18 Oct) only a Red or a
floor changed a ride: Thursday 8 Oct's "Sweet Spot (1 × 30 min @ 89%)" would have been
ridden in full after a sub-60 night, which Mark's own June protocol makes a Red day.

The rule (Craig, 1 Oct 2026, amending Decisions #366 and #367): in a light week a
morning with nothing clearly off holds the session as before, including an Amber made of
two mild concerns; a morning with any marked domain takes the ordinary graded action,
the hard work eased a zone at full length and Zone 2 as planned. Red and the floors are
unchanged. A domain marked on Garmin's own sleep score counts even when the age credit
lifts it, so the credit is never the only thing between easing and holding.

It adds no new words (``docs/drafts/2026-10-01-batch-298-wording.md``, §7): a clearly-off
morning shows the ordinary Amber lines, every other light-week concern the hold.
"""

from __future__ import annotations

import itertools
import uuid
from dataclasses import replace
from datetime import date, timedelta
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from src.models.coaching import PlanBlock, PlannedWorkout
from src.models.profile import Profile, UserRole
from src.services.daily_loop_envelope import _light_week_hold
from src.services.executable_coaching import MorningContext, morning_ir
from src.services.morning_analysis import MorningAnalysisService
from src.services.morning_verdict import (
    GRADED_EASE_HARD_LINE,
    GRADED_LIGHT_WEEK_LINE,
    GRADED_ZONE_TWO_LINE,
    graded_plan_adjustments,
)
from src.services.verdict_grading import (
    ACTION_AS_PLANNED,
    ACTION_EASE_HARD,
    ACTION_HOLD_TARGETS,
    ACTION_NO_TRAINING,
    ACTION_OFF_THE_BIKE,
    ACTION_RECOVERY,
    ACTION_SHORTENED_Z2,
    GradedVerdict,
    GradingInputs,
    classify_planned_workout,
    grade,
)
from src.services.workout_delivery import build_structured_workout_ir
from tests.test_batch_295_verdict_grading import _inputs, _load_fixture, _replayed
from tests.test_batch_296_graded_colour import _seed_one_poor_night

# Mark's real W12 and W13 sessions, as production holds them (read-only, 1 Oct 2026).
_WARM_UP: list[dict[str, Any]] = [
    {"ramp": [55, 80], "label": "Warm-up ramp 55→80%", "minutes": 8},
    {
        "label": "Primer 2×30s @100% / 55%",
        "target": "100%",
        "pattern": "2 x 30s / 30s @55%",
        "cadenceRpm": 95,
    },
    {"label": "Warm-up @72%", "target": "72%", "minutes": 3},
    {"label": "Warm-up @55%", "target": "55%", "minutes": 2},
]
W12_SWEET_SPOT: dict[str, Any] = {
    "format": "bike",
    "steps": [
        *_WARM_UP,
        {"label": "Sweet Spot 1×30 min @89%", "target": "89%", "minutes": 30, "cadenceRpm": 90},
        {"label": "Recover @60%", "target": "60%", "minutes": 3},
        {"ramp": [70, 45], "label": "Cool-down ramp", "minutes": 10},
    ],
}
W13_VO2_PRIMER: dict[str, Any] = {
    "format": "bike",
    "steps": [
        {"ramp": [55, 80], "label": "Warm-up ramp 55→80%", "minutes": 8},
        {"label": "Primer 2×30s @100%", "target": "100%", "minutes": 1, "cadenceRpm": 95},
        {"label": "Warm-up @72%", "target": "72%", "minutes": 2},
        {"label": "Warm-up @55%", "target": "55%", "minutes": 2},
        {"label": "VO₂ 3×1min @120%", "target": "120%", "pattern": "3 x 1min / 2min @60%"},
        {"ramp": [70, 45], "label": "Cool-down ramp", "minutes": 8},
    ],
}
W13_SWEET_SPOT_PRIMER: dict[str, Any] = {
    "format": "bike",
    "steps": [
        *_WARM_UP,
        {"label": "Sweet Spot 1×12 min @89%", "target": "89%", "minutes": 12, "cadenceRpm": 90},
        {"ramp": [70, 45], "label": "Cool-down ramp", "minutes": 8},
    ],
}
W12_Z2: dict[str, Any] = {
    "format": "bike",
    "steps": [
        {"ramp": [50, 65], "label": "Warm-up ramp", "minutes": 10},
        {"label": "Zone 2 @68%", "target": "68%", "minutes": 40, "cadenceRpm": 88},
        {"ramp": [60, 45], "label": "Cool-down ramp", "minutes": 10},
    ],
}

THU_8_OCT = date(2026, 10, 8)
HOLD_LINE = GRADED_LIGHT_WEEK_LINE.format(week="consolidation")


def _ride(
    structured: dict[str, Any],
    *,
    title: str,
    workout_type: str,
    minutes: int,
    day: date = THU_8_OCT,
) -> PlannedWorkout:
    return PlannedWorkout(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        workout_date=day,
        version=1,
        title=title,
        workout_type=workout_type,
        status="planned",
        is_active=True,
        planned_duration_min=minutes,
        intensity_target="see prescription",
        structured_workout=structured,
        source="plan_no2_import",
    )


def _sweet_spot() -> PlannedWorkout:
    return _ride(
        W12_SWEET_SPOT,
        title="Sweet Spot (1 × 30 min @ 89%)",
        workout_type="bike_sweet_spot",
        minutes=58,
    )


def _z2() -> PlannedWorkout:
    return _ride(W12_Z2, title="Z2", workout_type="bike_endurance", minutes=60)


def _light(
    workouts: list[PlannedWorkout], *, block: str = "consolidation", **morning: Any
) -> GradingInputs:
    """One W12 or W13 morning: the engine's grid inputs, inside a light week."""
    return replace(
        _inputs(**morning),
        recovery_class_block=True,
        light_week=block,
        sessions=tuple(classify_planned_workout(workout) for workout in workouts),
    )


def _actions(verdict: GradedVerdict) -> list[str]:
    return [action.action for action in verdict.actions]


def _plan_lines(verdict: GradedVerdict, workouts: list[PlannedWorkout]) -> list[str]:
    return graded_plan_adjustments(verdict, workouts, is_rest_day=False, acute={}, has_vo2=False)


# -- 300.2: a marked domain eases, anything milder holds ------------------------------------


def test_w12s_sweet_spot_eases_after_a_very_poor_night() -> None:
    """A 55 sleep score is one clearly-off domain: Amber, and the hard work eases a zone."""
    ride = _sweet_spot()
    verdict = grade(_light([ride], sleep_score=55))

    assert verdict.status == "Amber"
    assert [item.domain for item in verdict.domains if item.rating == "marked"] == ["sleep"]
    assert _actions(verdict) == [ACTION_EASE_HARD]
    assert verdict.actions[0].detail == "Amber: hard work eased a zone."
    # The week is still his consolidation week; it just no longer holds this session.
    assert verdict.references["lightWeek"] == "consolidation"


def test_one_mild_concern_holds_it() -> None:
    ride = _sweet_spot()
    verdict = grade(_light([ride], yesterday="hard"))

    assert verdict.label == "Green (held)"
    assert _actions(verdict) == [ACTION_HOLD_TARGETS]
    assert _plan_lines(verdict, [ride]) == [HOLD_LINE]


def test_two_mild_concerns_and_nothing_marked_hold_it() -> None:
    """Craig, 1 Oct: an Amber made of two mild concerns still holds the session."""
    ride, easy = _sweet_spot(), _z2()
    verdict = grade(_light([ride, easy], week=44.5, yesterday="hard"))

    assert verdict.status == "Amber"
    assert not [item for item in verdict.domains if item.rating == "marked"]
    assert _actions(verdict) == [ACTION_HOLD_TARGETS, ACTION_HOLD_TARGETS]
    assert _plan_lines(verdict, [ride, easy]) == [HOLD_LINE]


def test_a_zone_two_ride_is_as_planned_on_a_clearly_off_morning() -> None:
    """4 Jul 2026's shape: a consolidation week, a very poor night, an easy spin.

    The ride is the same one a hold would have kept; the day reads as any other Amber.
    """
    easy = _z2()
    verdict = grade(_light([easy], sleep_score=55))

    assert verdict.status == "Amber"
    assert _actions(verdict) == [ACTION_AS_PLANNED]
    assert verdict.actions[0].detail == "Amber: Zone 2 kept at full length."
    assert _plan_lines(verdict, [easy]) == [GRADED_ZONE_TWO_LINE]


def test_red_is_unchanged_in_a_light_week() -> None:
    ride, easy = _sweet_spot(), _z2()
    two_marked = grade(_light([ride, easy], sleep_score=55, acwr=1.6))
    rough = grade(_light([ride, easy], feel=3))

    for verdict in (two_marked, rough):
        assert verdict.status == "Red"
        assert _actions(verdict) == [ACTION_RECOVERY, ACTION_SHORTENED_Z2]


def test_the_floors_are_unchanged_in_a_light_week() -> None:
    ride = _sweet_spot()
    off_the_bike = grade(_light([ride], overnight="illness"))
    no_training = grade(_light([ride], symptoms="fever_aches"))

    assert (off_the_bike.floor, _actions(off_the_bike)) == ("bike_rest", [ACTION_OFF_THE_BIKE])
    assert (no_training.floor, _actions(no_training)) == ("no_training", [ACTION_NO_TRAINING])


def test_outside_a_light_week_nothing_changes() -> None:
    ride = _sweet_spot()
    for morning, expected in (
        ({"sleep_score": 55}, ACTION_EASE_HARD),
        ({"week": 44.5, "yesterday": "hard"}, ACTION_EASE_HARD),
        ({"yesterday": "hard"}, "move_or_hold"),
        ({}, ACTION_AS_PLANNED),
    ):
        inputs = replace(_light([ride], **morning), recovery_class_block=False, light_week=None)
        assert _actions(grade(inputs)) == [expected]


# -- the age credit is never the only thing between easing and holding ----------------------


def test_a_sub_60_night_on_garmins_score_eases_whatever_the_age_credit() -> None:
    """Garmin shows him 55; an 8-point credit makes it 63, a fair night on its own.

    The day is Amber because the credit may never be the only thing between Amber and
    Green (Batches 170 and 201), and the reason he reads says "clearly off". The action
    follows the same score, or the session would stand beside that reason.
    """
    ride = _sweet_spot()
    verdict = grade(_light([ride], sleep_score=63, raw_offset=8))

    assert verdict.status == "Amber"
    assert verdict.age_credit_guard_applied is True
    assert verdict.summary == "One thing is clearly off: a very poor night's sleep (score 55)."
    assert _actions(verdict) == [ACTION_EASE_HARD]


def test_a_second_mild_concern_never_turns_that_easing_back_into_a_hold() -> None:
    """The same night with one more thing a little off is a worse morning, not a better one."""
    ride = _sweet_spot()
    verdict = grade(_light([ride], sleep_score=61, raw_offset=4, yesterday="hard"))

    assert verdict.status == "Amber"
    assert verdict.age_credit_guard_applied is False
    assert not [item for item in verdict.domains if item.rating == "marked"]
    assert _actions(verdict) == [ACTION_EASE_HARD]


def test_two_mild_concerns_on_garmins_score_still_hold() -> None:
    """Raw 70 is a fair night, and yesterday was hard: two mild concerns, nothing marked."""
    ride = _sweet_spot()
    verdict = grade(_light([ride], sleep_score=76, raw_offset=6, yesterday="hard"))

    assert verdict.status == "Amber"
    assert verdict.age_credit_guard_applied is True
    assert verdict.summary.startswith("Two things are a little off:")
    assert _actions(verdict) == [ACTION_HOLD_TARGETS]


#: How far each action moves a hard session from the plan, least first.
CAUTION = {
    ACTION_AS_PLANNED: 0,
    ACTION_HOLD_TARGETS: 1,
    "move_or_hold": 1,
    ACTION_EASE_HARD: 2,
    ACTION_RECOVERY: 3,
    ACTION_OFF_THE_BIKE: 4,
    ACTION_NO_TRAINING: 5,
}
#: Levels for each input, from best to worst, with the age credit as its own input.
LIGHT_WEEK_LEVELS: dict[str, list[Any]] = {
    "week": [47.0, 44.5, 42.5],
    "overnight": ["none", "capped", "illness"],
    "sleep_score": [80, 70, 63, 55],
    "raw_offset": [0, 8],
    "acwr": [1.0, 1.6],
    "yesterday": ["easy", "hard"],
    "feel": [8, 5, 3],
    "readiness": ["HIGH", "LOW"],
}


def test_in_a_light_week_a_worse_morning_never_takes_a_less_cautious_action() -> None:
    ride = _sweet_spot()
    session = (classify_planned_workout(ride),)
    keys = list(LIGHT_WEEK_LEVELS)
    grid: dict[tuple[int, ...], int] = {}
    for combo in itertools.product(*(range(len(LIGHT_WEEK_LEVELS[key])) for key in keys)):
        morning = {
            key: LIGHT_WEEK_LEVELS[key][index] for key, index in zip(keys, combo, strict=True)
        }
        inputs = replace(
            _inputs(**morning),
            recovery_class_block=True,
            light_week="consolidation",
            sessions=session,
        )
        [action] = grade(inputs).actions
        grid[combo] = CAUTION[action.action]

    violations: list[str] = []
    for combo, caution in grid.items():
        for position, key in enumerate(keys):
            if combo[position] + 1 >= len(LIGHT_WEEK_LEVELS[key]):
                continue
            worse = list(combo)
            worse[position] += 1
            if grid[tuple(worse)] < caution:
                violations.append(f"{key} worse at {combo}: {caution} -> {grid[tuple(worse)]}")
    assert violations == [], violations[:5]
    assert set(grid.values()) == {0, 1, 2, 3, 4}


# -- 300.4: no new words --------------------------------------------------------------------


def test_a_clearly_off_morning_reads_as_any_other_amber() -> None:
    ride = _sweet_spot()
    verdict = grade(_light([ride], sleep_score=55))

    lines = _plan_lines(verdict, [ride])
    assert lines == [GRADED_EASE_HARD_LINE]
    assert not any("hold the targets" in line for line in lines)
    # No session is held, so Home and the brief keep the ordinary Amber headline.
    assert _light_week_hold({"graded": verdict.to_packet()}) is None


def test_a_mild_concern_still_names_the_week_on_every_surface() -> None:
    ride = _sweet_spot()
    verdict = grade(_light([ride], week=44.5, yesterday="hard"))

    assert _plan_lines(verdict, [ride]) == [HOLD_LINE]
    assert _light_week_hold({"graded": verdict.to_packet()}) == "consolidation"


# -- 300.3: the taper primers follow the same rule, and the ride offered is the eased one ---


def _main_set(ir: dict[str, Any], label: str) -> set[int]:
    return {
        int(step["powerStartPct"])
        for step in ir["steps"]
        if str(step["label"]).startswith(label) and "recovery" not in str(step["label"])
    }


@pytest.mark.parametrize(
    ("structured", "title", "workout_type", "minutes", "block", "main_set", "planned", "eased"),
    [
        pytest.param(
            W12_SWEET_SPOT,
            "Sweet Spot (1 × 30 min @ 89%)",
            "bike_sweet_spot",
            58,
            "consolidation",
            "Sweet Spot 1×30 min",
            89,
            76,
            id="w12_sweet_spot",
        ),
        pytest.param(
            W13_VO2_PRIMER,
            "VO₂ Primer (3 × 1 min @ 120%)",
            "bike_vo2",
            30,
            "taper",
            "VO₂ 3×1min",
            120,
            94,
            id="w13_vo2_primer",
        ),
        pytest.param(
            W13_SWEET_SPOT_PRIMER,
            "Sweet Spot Primer (1 × 12 min @ 89%)",
            "bike_sweet_spot",
            35,
            "taper",
            "Sweet Spot 1×12 min",
            89,
            76,
            id="w13_sweet_spot_primer",
        ),
    ],
)
def test_his_real_light_week_sessions_ease_a_zone_at_full_length(
    structured: dict[str, Any],
    title: str,
    workout_type: str,
    minutes: int,
    block: str,
    main_set: str,
    planned: int,
    eased: int,
) -> None:
    ride = _ride(structured, title=title, workout_type=workout_type, minutes=minutes)
    clearly_off = grade(_light([ride], block=block, sleep_score=55))
    a_little_off = grade(_light([ride], block=block, yesterday="hard"))
    assert _actions(clearly_off) == [ACTION_EASE_HARD]
    assert _actions(a_little_off) == [ACTION_HOLD_TARGETS]

    base = build_structured_workout_ir(ride)
    assert base["totalDurationSec"] == minutes * 60
    assert _main_set(base, main_set) == {planned}

    def context(verdict: GradedVerdict) -> MorningContext:
        return MorningContext(
            status=verdict.status,
            graded=True,
            actions={str(ride.id): verdict.actions[0].action},
            seen=frozenset({str(ride.id)}),
        )

    # The rail offers the eased ride on the clearly-off morning, and nothing on the held one.
    assert context(clearly_off).proposal_for(ride) == "Amber"
    assert context(a_little_off).proposal_for(ride) is None
    offered = morning_ir(base, context(clearly_off), ride, companion_session=False)
    assert offered["totalDurationSec"] == base["totalDurationSec"]
    assert _main_set(offered, main_set) == {eased}
    held = morning_ir(base, context(a_little_off), ride, companion_session=False)
    assert _main_set(held, main_set) == {planned}


# -- 300.5: no fixture morning changes colour or action -------------------------------------

#: The committed September fixture, replayed before this batch (label, then each live
#: session's action). 18–20 Sep sat in W09 RECOVERY.
FIXTURE_MORNINGS: dict[date, tuple[str, list[str]]] = {
    date(2026, 7, 16): ("Amber", []),
    date(2026, 9, 7): ("Amber", ["as_planned"]),
    date(2026, 9, 18): ("Green", []),
    date(2026, 9, 19): ("Green (held)", ["hold_targets"]),
    date(2026, 9, 20): ("Green", ["as_planned"]),
    date(2026, 9, 21): ("Amber", []),
    date(2026, 9, 22): ("Green (held)", ["as_planned", "move_or_hold"]),
    date(2026, 9, 23): ("Green (held)", ["as_planned"]),
    date(2026, 9, 24): ("Amber", ["ease_hard"]),
    date(2026, 9, 25): ("Amber", []),
    date(2026, 9, 26): ("Green (held)", ["as_planned", "as_planned"]),
}


def test_the_replayed_fixture_mornings_keep_their_colour_and_actions() -> None:
    replayed = _replayed(_load_fixture())

    assert {
        day: (morning.graded.label, _actions(morning.graded)) for day, morning in replayed.items()
    } == FIXTURE_MORNINGS


# -- PostgreSQL: the real morning packet (CI) -----------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("block_type", "expected_action"),
    [
        pytest.param("consolidation", ACTION_EASE_HARD, id="light_week_eases"),
        pytest.param("build", ACTION_EASE_HARD, id="build_week_eases"),
    ],
)
async def test_one_very_poor_night_eases_the_hard_session_in_the_real_packet(
    db_conn: AsyncConnection, block_type: str, expected_action: str
) -> None:
    """7 Sep's shape (sleep 53, nothing else off) on a hard day, in and out of a light week."""
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()
    day = date(2026, 9, 7)
    async with session_factory() as session:
        player = Profile(
            id=user_id,
            display_name="Light Week Marked",
            role=UserRole.admin,
            timezone="Europe/London",
            latitude=55.6045,
            longitude=-4.5249,
            is_active=True,
        )
        session.add(player)
        await session.flush()
        session.add(
            PlanBlock(
                user_id=user_id,
                name=f"PN2 W12 {block_type.upper()}",
                version=1,
                sequence_index=12,
                block_type=block_type,
                start_date=day - timedelta(days=3),
                end_date=day + timedelta(days=3),
                goals_json={},
                raw_plan={},
            )
        )
        hard = await _seed_one_poor_night(session, user_id, day)
        await session.commit()

        analysis_service = MorningAnalysisService(session)
        packet = await analysis_service.assemble_context_packet(player, day)

    verdict = packet["verdict"]
    assert verdict["status"] == "Amber"
    graded = verdict["graded"]
    light_week = block_type if block_type == "consolidation" else None
    assert graded["references"]["lightWeek"] == light_week
    assert [(item["plannedWorkoutId"], item["action"]) for item in graded["actions"]] == [
        (str(hard.id), expected_action)
    ]
    lines = verdict["planAdjustments"]
    assert GRADED_EASE_HARD_LINE in lines
    assert not any("stays as planned: hold the targets" in line for line in lines)
    # Batch 299: the eased session is still in the week's mix.
    assert verdict["weeklyMix"]["shortfall"] is None
    assert verdict["weeklyMix"]["eased"]["message"] in lines
    assert _light_week_hold(verdict) is None
