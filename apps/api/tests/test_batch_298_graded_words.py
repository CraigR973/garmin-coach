"""Batch 298 — the words follow the graded verdict.

On 1 Oct 2026, the first graded morning, the notice and the brief told Mark a low HRV
night "caps today at Amber" while the reason said two things were a little off. Replayed,
5 of 102 mornings would have shown "Good to go — hold your targets" beside the same cap.
These tests pin one story under the graded engine: the acute notices, reasons and the
floor's rule say what the graded verdict did; the brief's prompt no longer tells it the
day is capped; a light week's hold names the week; "yesterday was a hard day" is no
longer his commonest criticism; the coach sees a held morning as held. The ladder's words
and its v50 prompt stay exactly as they were, for the rollback.

Mark-facing wording signed off by Craig on Mark's behalf on 1 Oct 2026
(``docs/drafts/2026-10-01-batch-298-wording.md``).
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.dialects import postgresql

from src.models.coaching import DailyMetric, PlanBlock, PlannedWorkout
from src.services.bulk_history_reads import select_morning_calls
from src.services.coaching_state import (
    LADDER_AMBER_CONSTRAINT,
    LADDER_RED_CONSTRAINT,
    TRAINING_PLAN_AMBER_CONSTRAINT,
    TRAINING_PLAN_RED_CONSTRAINT,
    _training_plan_content,
)
from src.services.daily_loop_envelope import _light_week_hold
from src.services.morning_analysis import (
    GRADED_PROMPT_VERSION,
    GRADED_SYSTEM_PROMPT,
    LADDER_PROMPT_VERSION,
    LADDER_SYSTEM_PROMPT,
)
from src.services.morning_verdict import (
    GRADED_LIGHT_WEEK_LINE,
    HRV_HOLD_PLAN_LINE,
    LADDER_ONLY_ACUTE_FIELDS,
    _acute_physiology_rail,
    graded_acute_physiology,
    graded_plan_adjustments,
    graded_verdict_packet,
)
from src.services.recent_mornings import (
    MORNING_CALL_ADJUSTED,
    MORNING_CALL_HELD,
    MORNING_CALL_UNCHANGED,
    MorningCall,
    build_recent_mornings,
)
from src.services.verdict_grading import (
    DOMAIN_LOAD,
    GradingInputs,
    PlannedSession,
    SignalReading,
    grade,
    light_week_name,
    mark_facing_phrase,
)
from src.services.verdict_replay import _planned_workouts_from_packet
from tests.test_batch_295_verdict_grading import _load_fixture, _replayed
from tests.test_executable_coaching import SWEET_SPOT_STRUCTURED, _planned_workout

CAP_WORDS = re.compile(r"\bcap(s|ped)?\b|\bceiling\b", re.IGNORECASE)

#: 1 Oct 2026's stored acute rail, as production wrote it (read-only, 1 Oct). The
#: notice, the reason and the floor's rule all say the day is capped.
ONE_OCT_ACUTE: dict[str, Any] = {
    "status": "triggered",
    "symptoms": {
        "floor": None,
        "label": "None",
        "words": None,
        "answer": "none",
        "reason": None,
        "source": "answer",
        "applied": False,
        "answered": True,
        "planLine": None,
        "triggered": False,
        "escalation": None,
        "verdictImpact": "none",
        "requiresBikeRest": False,
        "statusBeforeFloor": "Amber",
        "requiresTrainingRest": False,
    },
    "escalations": [
        {
            "kind": "overnight_hrv",
            "level": "ease",
            "message": (
                "Your overnight HRV is 38 ms this morning against a usual 47 ms — lower than "
                "most nights for you. Dips like this usually come from a short night, a drink, "
                "a busy week or a hard day before. On its own it caps today at Amber: an eased "
                "session, not a day off the bike."
            ),
        }
    ],
    "overnightHrv": {
        "reason": (
            "Overnight HRV sets an Amber ceiling: 38 ms is below the acute personal floor of "
            "39.9 ms."
        ),
        "currentMs": 38,
        "triggered": True,
        "escalation": (
            "Your overnight HRV is 38 ms this morning against a usual 47 ms — lower than most "
            "nights for you. Dips like this usually come from a short night, a drink, a busy "
            "week or a hard day before. On its own it caps today at Amber: an eased session, "
            "not a day off the bike."
        ),
        "provenance": [
            {
                "rule": (
                    "his own median over the window, minus 1.5 standard deviations of it — a "
                    "personal floor, not a population band, and not Garmin's. Below it the day "
                    "is capped at Amber; it rests the bike only at 2.5 standard deviations or "
                    "30% under the median, or below the floor alongside a raised resting heart "
                    "rate or a reported symptom"
                ),
                "label": "acute personal HRV floor",
                "units": "ms",
                "value": 39.86,
                "figure": "verdict.acutePhysiology.hrvAcuteFloorMs",
            }
        ],
        "acuteFloorMs": 39.86,
        "illnessGrade": False,
        "illnessLineMs": 35.09,
        "verdictImpact": "amber_cap",
        "corroboratedBy": [],
        "baselineMedianMs": 47,
        "baselineStddevMs": 4.76,
        "requiresBikeRest": False,
    },
    "statusAfterCap": "Amber",
    "statusBeforeCap": "Green",
    "requiresBikeRest": False,
    "restingHeartRate": {
        "reason": None,
        "trigger": None,
        "triggered": False,
        "currentBpm": 44,
        "escalation": None,
        "verdictImpact": "amber_cap",
        "requiresBikeRest": False,
        "baselineMedianBpm": 44,
        "deltaFromMedianBpm": 0,
        "baselineUpperQuartileBpm": 45,
    },
    "triggeredSignals": ["overnight_hrv"],
    "verdictCapApplied": True,
    "requiresTrainingRest": False,
    "missingDataFloorApplied": False,
}

ONE_OCT_GRADED_NOTICE = (
    "Your overnight HRV is 38 ms this morning against a usual 47 ms — lower than most nights "
    "for you. Dips like this usually come from a short night, a drink, a busy week or a hard "
    "day before. On its own it is one thing a little off, and today's call already counts "
    "it: not a day off the bike."
)


def _cap_words(acute: dict[str, Any]) -> list[str]:
    """Every cap or ceiling the notices, the rails' reasons and the floor's rule state."""

    found: list[str] = []
    texts = [escalation.get("message") or "" for escalation in acute.get("escalations", [])]
    for rail in ("overnightHrv", "restingHeartRate"):
        section = acute.get(rail) or {}
        texts += [section.get("reason") or "", section.get("escalation") or ""]
        texts += [entry.get("rule") or "" for entry in section.get("provenance") or []]
    for text in texts:
        found += [match.group(0) for match in CAP_WORDS.finditer(text)]
    return found


# -- 298.2: the acute notices, reasons and rule ------------------------------------------


def test_1_oct_under_the_graded_verdict_says_one_thing_a_little_off_not_a_cap() -> None:
    original = copy.deepcopy(ONE_OCT_ACUTE)
    assert _cap_words(original), "the fixture must carry the ladder's cap words"

    graded = graded_acute_physiology(ONE_OCT_ACUTE)

    assert _cap_words(graded) == []
    assert graded["escalations"] == [
        {"kind": "overnight_hrv", "level": "ease", "message": ONE_OCT_GRADED_NOTICE}
    ]
    assert graded["overnightHrv"]["escalation"] == ONE_OCT_GRADED_NOTICE
    assert graded["overnightHrv"]["reason"] == (
        "Overnight HRV 38 ms is below the acute personal floor of 39.9 ms."
    )
    assert graded["gradedWording"] is True
    # The numbers and the floors are untouched; only the words changed.
    assert graded["overnightHrv"]["currentMs"] == 38
    assert graded["overnightHrv"]["acuteFloorMs"] == 39.86
    assert graded["requiresBikeRest"] is False
    # The ladder's own colour never enters a graded packet (Decision #367).
    for key in LADDER_ONLY_ACUTE_FIELDS:
        assert key not in graded
    assert "statusBeforeFloor" not in graded["symptoms"]
    assert graded["overnightHrv"]["verdictImpact"] != "amber_cap"
    # The ladder's packet is a separate object, still in its own words.
    assert ONE_OCT_ACUTE == original


@pytest.fixture(scope="module")
def fixture() -> dict[str, Any]:
    return _load_fixture()


@pytest.fixture(scope="module")
def replayed(fixture: dict[str, Any]) -> dict[date, Any]:
    # The held mornings these tests read (22 and 26 Sep) are Amber under Batch 304's HRV
    # persistence rule, so they are replayed as they were graded when 298 shipped.
    return _replayed(fixture, hrv_persistence=False)


def _graded_packet(replayed: dict[date, Any], fixture: dict[str, Any], day: date) -> Any:
    [morning] = [m for m in fixture["mornings"] if m["subjectDate"] == day.isoformat()]
    planned = _planned_workouts_from_packet(day, morning["plannedWorkouts"])
    return graded_verdict_packet(
        replayed[day].ladder_packet, replayed[day].graded, planned, breathwork_line=None
    )


@pytest.mark.parametrize(
    ("day", "kind"),
    [(date(2026, 9, 22), "overnight_hrv"), (date(2026, 9, 26), "resting_heart_rate")],
)
def test_the_held_mornings_carry_no_cap_beside_hold_your_targets(
    replayed: dict[date, Any], fixture: dict[str, Any], day: date, kind: str
) -> None:
    """Two of the five replayed held mornings with a cap notice are in the fixture."""

    ladder_acute = replayed[day].ladder_packet["acutePhysiology"]
    assert any(
        "caps today at Amber" in escalation["message"] for escalation in ladder_acute["escalations"]
    )
    packet = _graded_packet(replayed, fixture, day)

    assert packet["held"] is True
    assert packet["status"] == "Green"
    acute = packet["acutePhysiology"]
    assert _cap_words(acute) == []
    [escalation] = [item for item in acute["escalations"] if item["kind"] == kind]
    assert escalation["level"] == "ease"
    assert escalation["message"].endswith(
        "On its own it is one thing a little off, and today's call already counts it: not a "
        "day off the bike."
    )
    # The ladder's packet for the same morning keeps the ladder's words (the rollback).
    assert any(
        "caps today at Amber" in escalation["message"]
        for escalation in replayed[day].ladder_packet["acutePhysiology"]["escalations"]
    )


def _hrv_rows(today: date, *, rhr_today: int, rhr_yesterday: int, hrv_today: int) -> Any:
    spread = (40, 42, 44, 46, 47, 48, 50, 52, 54)  # median 47, SD 4.3, as his nights run
    history = [
        DailyMetric(
            calendar_date=today - timedelta(days=offset),
            phase="morning",
            hrv_last_night_avg_ms=spread[offset % len(spread)],
            resting_heart_rate_bpm=44,
        )
        for offset in range(2, 86)
    ]
    history.append(
        DailyMetric(
            calendar_date=today - timedelta(days=1),
            phase="morning",
            hrv_last_night_avg_ms=47,
            resting_heart_rate_bpm=rhr_yesterday,
        )
    )
    morning = DailyMetric(
        calendar_date=today,
        phase="morning",
        hrv_last_night_avg_ms=hrv_today,
        resting_heart_rate_bpm=rhr_today,
    )
    return morning, history


class _Baseline:
    median_value = 44.0
    upper_quartile_value = 45.0
    sample_count = 84
    window_start_date = date(2026, 7, 1)
    window_end_date = date(2026, 9, 30)


def _rail(*, rhr_today: int, rhr_yesterday: int, hrv_today: int) -> dict[str, Any]:
    morning, history = _hrv_rows(
        date(2026, 10, 8), rhr_today=rhr_today, rhr_yesterday=rhr_yesterday, hrv_today=hrv_today
    )
    return _acute_physiology_rail(
        daily_metric=morning,
        sleep=None,
        baselines={"resting_heart_rate_bpm": _Baseline()},  # type: ignore[dict-item]
        recent_daily_metrics=history,
        recent_sleeps=[],
    )


def test_the_off_the_bike_notice_loses_only_the_cap_clause() -> None:
    ladder = _rail(rhr_today=47, rhr_yesterday=46, hrv_today=38)
    assert ladder["overnightHrv"]["requiresBikeRest"] is True
    assert "Either on its own would only cap the day;" in ladder["overnightHrv"]["escalation"]

    graded = graded_acute_physiology(ladder)
    notice = graded["overnightHrv"]["escalation"]
    assert notice == ladder["overnightHrv"]["escalation"].replace(
        "Either on its own would only cap the day;",
        "Either on its own would only be a little off;",
    )
    assert "see your GP if it doesn't" in notice
    assert [item["level"] for item in graded["escalations"]] == [
        item["level"] for item in ladder["escalations"]
    ]
    assert _cap_words(graded) == []


def test_the_two_morning_resting_hr_notice_and_the_illness_grade_night() -> None:
    rhr = _rail(rhr_today=47, rhr_yesterday=46, hrv_today=50)
    assert rhr["restingHeartRate"]["trigger"] == "consecutive_q3"
    graded = graded_acute_physiology(rhr)
    assert graded["restingHeartRate"]["escalation"] == (
        "Your resting heart rate is 47 this morning against a usual 44 — a little above your "
        "usual range, as it was yesterday. Small rises like this usually come from travel, a "
        "short night, a busy week or a hard day before. On its own it is one thing a little "
        "off, and today's call already counts it: not a day off the bike."
    )
    assert _cap_words(graded) == []

    illness = _rail(rhr_today=44, rhr_yesterday=44, hrv_today=30)
    assert illness["overnightHrv"]["illnessGrade"] is True
    graded_illness = graded_acute_physiology(illness)
    # The illness-grade notice and its GP line are unchanged.
    assert graded_illness["overnightHrv"]["escalation"] == illness["overnightHrv"]["escalation"]
    assert _cap_words(graded_illness) == []


def test_the_ladder_rail_keeps_its_words_for_the_rollback() -> None:
    ladder = _rail(rhr_today=44, rhr_yesterday=44, hrv_today=38)
    assert ladder["overnightHrv"]["escalation"].endswith(
        "On its own it caps today at Amber: an eased session, not a day off the bike."
    )
    assert ladder["overnightHrv"]["reason"].startswith("Overnight HRV sets an Amber ceiling:")
    [entry] = ladder["overnightHrv"]["provenance"]
    assert "Below it the day is capped at Amber;" in entry["rule"]
    assert "gradedWording" not in ladder


# -- 298.3: the graded prompt --------------------------------------------------------------


def test_the_graded_prompt_carries_neither_ladder_line_and_the_ladder_keeps_both() -> None:
    assert GRADED_PROMPT_VERSION == "morning-analysis-v55-2026-10-02"
    assert LADDER_PROMPT_VERSION == "morning-analysis-v50-2026-09-28"
    for ladder_line in (
        "argue down an RHR/HRV Amber cap",
        "a capped drop on its own is an eased day",
    ):
        assert ladder_line.replace(" ", "") in LADDER_SYSTEM_PROMPT.replace("\n", "").replace(
            " ", ""
        )
        assert ladder_line.replace(" ", "") not in GRADED_SYSTEM_PROMPT.replace("\n", "").replace(
            " ", ""
        )
    flat = " ".join(GRADED_SYSTEM_PROMPT.split())
    assert "never call it a cap, and never say it caps the day on its own" in flat
    assert "is one thing a little off, already counted in the graded colour" in flat
    assert "verdict.graded.references.lightWeek" in flat


# -- 298.4: a light week's hold names the week ---------------------------------------------


def _blocks() -> list[PlanBlock]:
    return [
        PlanBlock(
            name="PN2 W11 PEAK VO₂",
            block_type="build",
            start_date=date(2026, 9, 28),
            end_date=date(2026, 10, 4),
        ),
        PlanBlock(
            name="PN2 W12 CONSOLIDATION",
            block_type="consolidation",
            start_date=date(2026, 10, 5),
            end_date=date(2026, 10, 11),
        ),
        PlanBlock(
            name="PN2 W13 TAPER",
            block_type="taper",
            start_date=date(2026, 10, 12),
            end_date=date(2026, 10, 18),
        ),
        PlanBlock(
            name="PN2 W09 RECOVERY",
            block_type="recovery",
            start_date=date(2026, 9, 14),
            end_date=date(2026, 9, 20),
        ),
    ]


def test_the_light_week_is_named_as_his_plan_names_it() -> None:
    blocks = _blocks()
    assert light_week_name(date(2026, 10, 8), blocks) == "consolidation"
    assert light_week_name(date(2026, 10, 15), blocks) == "taper"
    assert light_week_name(date(2026, 9, 17), blocks) == "recovery"
    assert light_week_name(date(2026, 10, 1), blocks) is None
    assert light_week_name(date(2026, 11, 1), blocks) is None


SWEET_SPOT = PlannedSession(
    id="8f1c2d3e-4b5a-4c6d-8e7f-9a0b1c2d3e4f",
    title="Sweet Spot (1 × 30 min @ 89%)",
    workout_type="bike_sweet_spot",
    planned_minutes=60,
    is_bike=True,
    is_hard=True,
    has_vo2=False,
    is_key=True,
)


def _w12_inputs(**overrides: Any) -> GradingInputs:
    base: dict[str, Any] = dict(
        subject_date=date(2026, 10, 8),
        acute={},
        recovery_class_block=True,
        light_week="consolidation",
        yesterday_load="hard",
        sessions=(SWEET_SPOT,),
    )
    base.update(overrides)
    return GradingInputs(**base)


def _sweet_spot_workout() -> PlannedWorkout:
    workout = _planned_workout(SWEET_SPOT_STRUCTURED)
    workout.title = SWEET_SPOT.title
    workout.workout_type = "bike_sweet_spot"
    return workout


def test_a_held_light_week_session_names_the_week_on_the_plan_line() -> None:
    workout = _sweet_spot_workout()
    verdict = grade(_w12_inputs(sessions=(replace(SWEET_SPOT, id=str(workout.id)),)))
    assert verdict.held is True
    assert [action.action for action in verdict.actions] == ["hold_targets"]
    assert verdict.actions[0].detail == (
        "A planned consolidation week is already light: hold the session."
    )
    assert verdict.references["lightWeek"] == "consolidation"

    lines = graded_plan_adjustments(verdict, [workout], is_rest_day=False, acute={}, has_vo2=False)
    assert lines == [
        "This is your planned consolidation week, so today's session stays as planned: hold "
        "the targets."
    ]
    assert HRV_HOLD_PLAN_LINE not in lines
    assert GRADED_LIGHT_WEEK_LINE.format(week="taper").startswith("This is your planned taper week")


def test_the_envelope_names_the_light_week_only_when_it_held_the_session() -> None:
    verdict = grade(_w12_inputs())
    packet = {"graded": verdict.to_packet()}
    assert _light_week_hold(packet) == "consolidation"

    eased = grade(_w12_inputs(recovery_class_block=False, light_week=None))
    assert _light_week_hold({"graded": eased.to_packet()}) is None
    # A packet stored before the week was named keeps the usual headline.
    old = verdict.to_packet()
    del old["references"]["lightWeek"]
    assert _light_week_hold({"graded": old}) is None
    assert _light_week_hold({}) is None


def test_the_replay_names_the_week_the_morning_sat_in(replayed: dict[date, Any]) -> None:
    # 19 Sep sat in W09 RECOVERY; the replay builds its inputs the way production does.
    graded = replayed[date(2026, 9, 19)].graded
    assert graded.references["lightWeek"] == "recovery"
    assert replayed[date(2026, 9, 21)].graded.references["lightWeek"] is None


# -- 298.5: yesterday's hard session is a recovery state, not a criticism -------------------


def test_yesterdays_hard_session_reads_as_recovery_not_criticism() -> None:
    signal = SignalReading(
        domain=DOMAIN_LOAD,
        signal="yesterday_load",
        rating="mild",
        value=None,
        reference=None,
        reason="Yesterday's training was hard, and he is still recovering from it.",
    )
    assert mark_facing_phrase(signal) == "you're still recovering from yesterday's hard session"
    verdict = grade(_w12_inputs(recovery_class_block=False, light_week=None))
    assert verdict.summary == (
        "One thing is a little off: you're still recovering from yesterday's hard session."
    )
    assert "yesterday was a hard day" not in json.dumps(verdict.to_packet()).lower()


# -- 298.6: the coach sees a held morning as held ------------------------------------------


def test_recent_mornings_carry_held_and_each_sessions_action() -> None:
    day = date(2026, 10, 8)
    workouts = [
        {
            "id": SWEET_SPOT.id,
            "title": SWEET_SPOT.title,
            "workoutType": "bike_sweet_spot",
            "basis": "imported from your training plan",
            "plannedDurationMin": 60,
            "intensityTarget": "89% FTP",
        },
        {
            "id": "11111111-2222-4333-8444-555555555555",
            "title": "Mobility",
            "workoutType": "flexibility",
            "basis": "imported from your training plan",
            "plannedDurationMin": 20,
            "intensityTarget": None,
        },
    ]
    call = MorningCall(
        subject_date=day,
        generated_at_utc=datetime(2026, 10, 8, 7, 0),
        verdict="Green",
        reasons=["One thing is a little off: your HRV was low last night."],
        verdict_adjustment=None,
        requires_bike_rest=False,
        rest_day={"isRestDay": False},
        planned_workouts=workouts,
        held=True,
        graded_actions=[
            {"plannedWorkoutId": SWEET_SPOT.id, "action": "hold_targets"},
            {"plannedWorkoutId": workouts[1]["id"], "action": "as_planned"},
        ],
    )
    section = build_recent_mornings(today=day, mornings=[call], audits=[])
    [entry] = [item for item in section["days"] if item["date"] == day.isoformat()]

    assert entry["held"] is True
    ride, mobility = entry["sessions"]
    assert ride["morningCall"] == MORNING_CALL_HELD
    assert ride["gradedAction"] == "hold_targets"
    assert mobility["morningCall"] == MORNING_CALL_UNCHANGED
    assert mobility["gradedAction"] == "as_planned"
    assert "never call it plain Green" in section["meaning"]


def test_an_adjusted_session_stays_adjusted_and_an_old_read_is_unchanged() -> None:
    day = date(2026, 10, 8)
    workout = {
        "id": SWEET_SPOT.id,
        "title": SWEET_SPOT.title,
        "workoutType": "bike_sweet_spot",
        "plannedDurationMin": 60,
    }
    adjusted = MorningCall(
        subject_date=day,
        generated_at_utc=datetime(2026, 10, 8, 7, 0),
        verdict="Amber",
        reasons=[],
        verdict_adjustment={
            "changed": True,
            "plannedWorkoutId": SWEET_SPOT.id,
            "plannedDurationMin": 60,
            "adjustedDurationMin": 60,
            "plannedWorkPowerPct": 89,
            "adjustedWorkPowerPct": 75,
        },
        requires_bike_rest=False,
        rest_day={},
        planned_workouts=[workout],
        graded_actions=[{"plannedWorkoutId": SWEET_SPOT.id, "action": "ease_hard"}],
    )
    [entry] = [
        item
        for item in build_recent_mornings(today=day, mornings=[adjusted], audits=[])["days"]
        if item["date"] == day.isoformat()
    ]
    assert entry["sessions"][0]["morningCall"] == MORNING_CALL_ADJUSTED
    assert entry["sessions"][0]["gradedAction"] == "ease_hard"
    assert "held" not in entry

    old = MorningCall(
        subject_date=day,
        generated_at_utc=datetime(2026, 10, 8, 7, 0),
        verdict="Green",
        reasons=[],
        verdict_adjustment=None,
        requires_bike_rest=False,
        rest_day={},
        planned_workouts=[workout],
    )
    [old_entry] = [
        item
        for item in build_recent_mornings(today=day, mornings=[old], audits=[])["days"]
        if item["date"] == day.isoformat()
    ]
    assert old_entry["sessions"][0]["morningCall"] == MORNING_CALL_UNCHANGED
    assert "gradedAction" not in old_entry["sessions"][0]


def test_the_projection_reads_held_and_the_actions_from_the_one_packet_read() -> None:
    sql = str(select_morning_calls().compile(dialect=postgresql.dialect()))
    assert "AS held" in sql
    assert "AS graded_actions" in sql
    assert sql.count("analyses.context_packet") == 1


# -- 298.7: the knowledge base's constraint (a fresh seed; production by read-modify-write) --


def test_the_seeded_plan_states_the_graded_amber_and_red() -> None:
    constraints = _training_plan_content(date(2026, 7, 20))["constraints"]
    assert TRAINING_PLAN_AMBER_CONSTRAINT in constraints
    assert TRAINING_PLAN_RED_CONSTRAINT in constraints
    assert LADDER_AMBER_CONSTRAINT not in constraints
    assert LADDER_RED_CONSTRAINT not in constraints
    assert "cut duration" not in " ".join(constraints)
