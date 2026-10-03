"""Batch 306 — a tired morning lets Mark pick a shorter, easier ride.

A graded Amber eased a hard session a zone at full length whatever made it Amber, so
VO2 at 119% became 94% after a very poor night, and a long ride was never shortened
though on 16 and 30 Aug, tired, he asked for shorter ones. Craig's calls (3 Oct 2026):
on an Amber with sleep or how he feels clearly off,

* **he picks how to ride the hard session**: easy Zone 2 (nothing above 75% FTP) or
  tempo (nothing above 85%), full length either way, by one of two buttons on Home;
* **a long ride is offered shorter** in one tap, at 75% of its length, Zone 2 kept;
* until he picks, **the planned session stays on Zwift**, as it already does for every
  eased ride, which waits for his Approve.

Red is still never longer or harder than Amber (Batch 243). The words are signed off by
Craig on Mark's behalf.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import date
from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.models.profile import Profile
from src.services.executable_coaching import ExecutableCoachingService
from src.services.morning_analysis import (
    GRADED_VERDICT_RULE,
    PICK_RIDE_CHOICES,
    build_today_actions,
)
from src.services.morning_verdict import (
    GRADED_OFFER_SHORTER_LINE,
    GRADED_PICK_LINE,
    graded_plan_adjustments,
    graded_verdict_adjustment_packet,
    offered_shorter_minutes,
)
from src.services.verdict_grading import (
    ACTION_AS_PLANNED,
    ACTION_EASE_HARD,
    ACTION_OFFER_SHORTER,
    ACTION_PICK_ZONE2_OR_TEMPO,
    ACTION_RECOVERY,
    ACTION_SHORTENED_Z2,
    GradingInputs,
    classify_planned_workout,
    grade,
    ride_transform,
)
from src.services.verdict_scaling import (
    ENDURANCE_CEILING_PCT,
    TEMPO_CAP_PCT,
    TRANSFORM_SHORTER,
    TRANSFORM_TIRED_TEMPO,
    TRANSFORM_TIRED_ZONE2,
    adjust_ir_for_verdict,
)
from src.services.weekly_mix import DROPPING_ACTIONS
from src.services.workout_delivery import build_structured_workout_ir
from tests.test_batch_295_verdict_grading import _inputs
from tests.test_executable_coaching import (
    VO2_STRUCTURED,
    _FakeIntervalsClient,
    _planned_workout,
    _seed_bike,
)

LONG_Z2_STRUCTURED = {
    "format": "bike",
    "steps": [
        {"label": "Warm-up", "minutes": 10, "target": "easy spin"},
        {"label": "Long Z2", "minutes": 100, "target": "65-70% FTP 85rpm"},
        {"label": "Cool-down", "minutes": 10, "target": "easy spin"},
    ],
}


def _vo2() -> Any:
    return _planned_workout(VO2_STRUCTURED)


def _long_ride() -> Any:
    ride = _planned_workout(LONG_Z2_STRUCTURED)
    ride.title = "Long Z2"
    ride.workout_type = "bike_endurance"
    ride.planned_duration_min = 120
    ride.intensity_target = "65-70% FTP"
    return ride


def _short_z2() -> Any:
    ride = _planned_workout(
        {
            "format": "bike",
            "steps": [{"label": "Z2", "minutes": 60, "target": "65-70% FTP 85rpm"}],
        }
    )
    ride.title = "Z2"
    ride.workout_type = "bike_endurance"
    ride.planned_duration_min = 60
    return ride


def _morning(workouts: list[Any], **morning: Any) -> GradingInputs:
    return replace(
        _inputs(**morning),
        sessions=tuple(classify_planned_workout(workout) for workout in workouts),
    )


def _actions(inputs: GradingInputs) -> list[str]:
    return [item.action for item in grade(inputs).actions]


# -- what a tired morning offers --------------------------------------------------------


@pytest.mark.parametrize(
    "tired",
    [
        pytest.param({"sleep_score": 55}, id="very_poor_night"),
        pytest.param({"feel": 5}, id="feels_well_below_par"),
        # Garmin's own 55, lifted to 63 by the age credit, still counts (as in Batch 300).
        pytest.param({"sleep_score": 63, "raw_offset": 8}, id="garmins_score_under_60"),
    ],
)
def test_a_tired_morning_offers_the_pick_and_the_shorter_long_ride(tired: dict[str, Any]) -> None:
    inputs = _morning([_vo2(), _long_ride(), _short_z2()], **tired)
    assert grade(inputs).status == "Amber"
    assert _actions(inputs) == [ACTION_PICK_ZONE2_OR_TEMPO, ACTION_OFFER_SHORTER, ACTION_AS_PLANNED]


@pytest.mark.parametrize(
    "not_tired",
    [
        # Clearly off, but not sleep or feel: the ordinary graded Amber.
        pytest.param({"rhr_rise": 5}, id="resting_hr_up_5"),
        pytest.param({"acwr": 1.6}, id="load_ratio_high"),
        # Two mild concerns, nothing marked.
        pytest.param({"sleep_score": 70, "week": 44.5}, id="two_mild"),
    ],
)
def test_an_amber_that_is_not_tiredness_eases_as_before(not_tired: dict[str, Any]) -> None:
    inputs = _morning([_vo2(), _long_ride()], **not_tired)
    assert grade(inputs).status == "Amber"
    assert _actions(inputs) == [ACTION_EASE_HARD, ACTION_AS_PLANNED]


def test_a_light_week_offers_the_pick_on_a_tired_morning() -> None:
    inputs = replace(
        _morning([_vo2()], sleep_score=55),
        recovery_class_block=True,
        light_week="taper",
    )
    assert _actions(inputs) == [ACTION_PICK_ZONE2_OR_TEMPO]


def test_red_and_the_floors_are_unchanged() -> None:
    two_marked = _morning([_vo2(), _long_ride()], sleep_score=55, acwr=1.6)
    assert grade(two_marked).status == "Red"
    assert _actions(two_marked) == [ACTION_RECOVERY, ACTION_SHORTENED_Z2]
    rough = _morning([_vo2()], feel=3)
    assert _actions(rough) == [ACTION_RECOVERY]
    fever = _morning([_vo2()], symptoms="fever_aches")
    assert grade(fever).status == "Red"


def test_without_the_flag_a_tired_morning_eases_as_it_did() -> None:
    inputs = replace(_morning([_vo2(), _long_ride()], sleep_score=55), tired_morning_choices=False)
    assert _actions(inputs) == [ACTION_EASE_HARD, ACTION_AS_PLANNED]
    assert grade(inputs).references["tiredMorningChoices"] is False
    assert grade(replace(inputs, tired_morning_choices=True)).references["tiredMorningChoices"]


# -- the rides themselves ---------------------------------------------------------------


def _powers(ir: dict[str, Any]) -> list[int]:
    return [max(int(step["powerStartPct"]), int(step["powerEndPct"])) for step in ir["steps"]]


@pytest.mark.parametrize(
    ("transform", "cap"),
    [(TRANSFORM_TIRED_ZONE2, ENDURANCE_CEILING_PCT), (TRANSFORM_TIRED_TEMPO, TEMPO_CAP_PCT)],
)
def test_each_pick_caps_every_step_at_full_length(transform: str, cap: int) -> None:
    base = build_structured_workout_ir(_vo2(), ftp_watts=280)
    assert max(_powers(base)) > TEMPO_CAP_PCT
    ridden = adjust_ir_for_verdict(base, transform, graded=True)
    assert max(_powers(ridden)) <= cap
    assert ridden["totalDurationSec"] == base["totalDurationSec"]
    assert ridden["adjustment"]["changed"] is True


def test_the_shorter_long_ride_keeps_its_zone_2_at_three_quarters_of_its_length() -> None:
    base = build_structured_workout_ir(_long_ride(), ftp_watts=280)
    shorter = adjust_ir_for_verdict(base, TRANSFORM_SHORTER, graded=True)
    assert shorter["totalDurationSec"] == round(base["totalDurationSec"] * 0.75)
    assert max(_powers(shorter)) == max(_powers(base))
    assert offered_shorter_minutes(_long_ride()) == (90, 120)


def test_red_is_never_longer_or_harder_than_a_tired_amber() -> None:
    """Batch 243's invariant, for every version a tired morning offers."""
    vo2 = build_structured_workout_ir(_vo2(), ftp_watts=280)
    red_hard = adjust_ir_for_verdict(vo2, "Red", graded=True)
    for transform in (TRANSFORM_TIRED_ZONE2, TRANSFORM_TIRED_TEMPO):
        amber = adjust_ir_for_verdict(vo2, transform, graded=True)
        assert red_hard["totalDurationSec"] <= amber["totalDurationSec"]
        assert max(_powers(red_hard)) <= max(_powers(amber))
    long_ride = build_structured_workout_ir(_long_ride(), ftp_watts=280)
    red_long = adjust_ir_for_verdict(long_ride, "Red", graded=True)
    shorter = adjust_ir_for_verdict(long_ride, TRANSFORM_SHORTER, graded=True)
    assert red_long["totalDurationSec"] <= shorter["totalDurationSec"]
    assert max(_powers(red_long)) <= max(_powers(shorter))


def test_the_rail_offers_the_easy_zone_2_version_first() -> None:
    assert ride_transform("Amber", graded=True, action=ACTION_PICK_ZONE2_OR_TEMPO) == (
        TRANSFORM_TIRED_ZONE2
    )
    assert ride_transform("Amber", graded=True, action=ACTION_OFFER_SHORTER) == TRANSFORM_SHORTER


def test_neither_pick_keeps_the_hard_work_so_the_week_counts_it_as_missed() -> None:
    assert ACTION_PICK_ZONE2_OR_TEMPO in DROPPING_ACTIONS
    assert ACTION_OFFER_SHORTER not in DROPPING_ACTIONS


# -- the words, signed off by Craig on Mark's behalf (3 Oct 2026) ------------------------


def test_the_plan_lines() -> None:
    vo2, long_ride = _vo2(), _long_ride()
    graded = grade(_morning([vo2, long_ride], sleep_score=51))
    lines = graded_plan_adjustments(
        graded, [vo2, long_ride], is_rest_day=False, acute={}, has_vo2=True
    )
    assert lines == [
        "Short on sleep or feeling flat, so pick how to ride VO2 Max 30/30 today: easy Zone 2 "
        "(nothing above 75% FTP) or tempo (nothing above 85%), full length either way.",
        "Keep your Zone 2 ride at full length, or ride a shorter version if you'd rather "
        "(90 min instead of 120).",
    ]
    assert GRADED_PICK_LINE.format(title="VO2 Max 30/30") == lines[0]
    assert GRADED_OFFER_SHORTER_LINE.format(short=90, full=120) == lines[1]


def _packet(workouts: list[Any], **morning: Any) -> dict[str, Any]:
    graded = grade(_morning(workouts, **morning))
    return {
        "status": graded.status,
        "engine": "graded",
        "verdictAdjustment": graded_verdict_adjustment_packet(graded, workouts),
    }


def test_home_offers_the_pick_with_both_buttons() -> None:
    vo2 = _vo2()
    packet = _packet([vo2], sleep_score=51)
    assert packet["verdictAdjustment"]["choice"]["kind"] == "pick"
    assert packet["verdictAdjustment"]["choice"]["untilPicked"] == "as_planned"
    [action] = build_today_actions(
        verdict=packet, planned_workouts=[vo2], thermal_review={}, recommend_breathwork=False
    )
    assert action == {
        "kind": "pick_ride",
        "title": "How do you want to ride VO2 Max 30/30 today?",
        "detail": "Same length either way. If you pick neither, the planned session stays on "
        "Zwift.",
        "plannedWorkoutId": str(vo2.id),
        "targetDate": None,
        "href": None,
        "choices": [
            {"variant": "zone2", "label": "Easy Zone 2"},
            {"variant": "tempo", "label": "Tempo"},
        ],
    }
    assert [choice["label"] for choice in PICK_RIDE_CHOICES] == ["Easy Zone 2", "Tempo"]


def test_a_titled_session_is_named_by_its_name_alone_on_the_card() -> None:
    vo2 = _vo2()
    vo2.title = "VO₂ (5 × 2:30 @ 119%)"
    [action] = build_today_actions(
        verdict=_packet([vo2], sleep_score=51),
        planned_workouts=[vo2],
        thermal_review={},
        recommend_breathwork=False,
    )
    assert action["title"] == "How do you want to ride VO₂ today?"


def test_home_offers_the_shorter_long_ride_in_one_tap() -> None:
    long_ride = _long_ride()
    packet = _packet([long_ride], sleep_score=51)
    assert packet["verdictAdjustment"]["choice"]["kind"] == "offer"
    [action] = build_today_actions(
        verdict=packet, planned_workouts=[long_ride], thermal_review={}, recommend_breathwork=False
    )
    assert action == {
        "kind": "approve_ride",
        "title": "Ride a shorter version?",
        "detail": "90 min instead of 120, same Zone 2. Approve to upload it; otherwise ride "
        "as planned.",
        "plannedWorkoutId": str(long_ride.id),
        "targetDate": None,
        "href": None,
    }


def test_the_brief_is_told_both_choices_and_never_to_call_them_done() -> None:
    assert "pick_zone2_or_tempo" in GRADED_VERDICT_RULE
    assert "offer_shorter" in GRADED_VERDICT_RULE
    assert f"nothing above {ENDURANCE_CEILING_PCT}% FTP" in GRADED_VERDICT_RULE
    assert f"nothing above\n{TEMPO_CAP_PCT}%" in GRADED_VERDICT_RULE
    assert "never say the ride is already eased" in GRADED_VERDICT_RULE
    assert "never call it shortened" in GRADED_VERDICT_RULE


# -- the approve endpoint takes his pick (PostgreSQL, CI) --------------------------------


@pytest.mark.asyncio
async def test_picking_tempo_uploads_the_tempo_version(db_conn: AsyncConnection) -> None:
    user_id, workout_id = uuid.uuid4(), uuid.uuid4()
    day = date(2026, 8, 13)
    await _seed_bike(db_conn, user_id, workout_id, workout_date=day)
    fake = _FakeIntervalsClient()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExecutableCoachingService(session, intervals_client=fake)
        await service.reconcile_deliveries(user, start_date=day, end_date=day)
        workout = await service.rail._planned_workout(user_id, workout_id)
        ftp = await service.rail._ftp_watts(user_id)
        base = build_structured_workout_ir(workout, ftp_watts=ftp)
        zone2 = adjust_ir_for_verdict(base, TRANSFORM_TIRED_ZONE2, graded=True)
        await service.rail.propose_from_ir(player=user, workout=workout, ir=zone2, commit=True)

        with pytest.raises(HTTPException) as unknown:
            await service.approve_adjustment(
                user, planned_workout_id=workout_id, variant="threshold"
            )
        assert unknown.value.status_code == 422

        delivered = await service.approve_adjustment(
            user, planned_workout_id=workout_id, variant="tempo"
        )

        uploaded = delivered.structured_workout_ir
        assert uploaded["origin"] == "graded_tired_tempo"
        assert max(_powers(uploaded)) <= TEMPO_CAP_PCT
        assert uploaded["totalDurationSec"] == base["totalDurationSec"]
        assert [eid for eid, _ in fake.updates] == ["evt_123"]


@pytest.mark.asyncio
async def test_a_pick_cannot_be_taken_on_a_ride_that_offered_none(
    db_conn: AsyncConnection,
) -> None:
    user_id, workout_id = uuid.uuid4(), uuid.uuid4()
    day = date(2026, 8, 14)
    await _seed_bike(db_conn, user_id, workout_id, workout_date=day)
    fake = _FakeIntervalsClient()

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExecutableCoachingService(session, intervals_client=fake)
        workout = await service.rail._planned_workout(user_id, workout_id)
        ftp = await service.rail._ftp_watts(user_id)
        eased = adjust_ir_for_verdict(
            build_structured_workout_ir(workout, ftp_watts=ftp), "Amber", graded=True
        )
        await service.rail.propose_from_ir(player=user, workout=workout, ir=eased, commit=True)

        with pytest.raises(HTTPException) as no_choice:
            await service.approve_adjustment(user, planned_workout_id=workout_id, variant="tempo")
        assert no_choice.value.status_code == 409
        assert fake.updates == []
