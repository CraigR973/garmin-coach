"""Batch 294 — symptoms are asked, and only illness takes him off the bike.

Two changes, both from the 28 Sep review (``docs/reviews/verdict-grading-review-2026-09-28.md``):

* **The symptom question.** The colour never asked about symptoms. The check-in now
  asks "Any symptoms today?", and three answers set a floor no other signal can
  override: chest or heart (no training, a doctor today), fever or aches (no training
  until clear), a head cold (Red on the easy path).
* **The overnight-HRV rail.** It fired on 6 of Mark's 75 eligible mornings, three by
  under 1 ms, and told him to stay off the bike each time. It keeps its Amber cap,
  and rests the bike only at an illness-grade drop (2.5 SD or 30% under his median)
  or when the capped drop comes with a second sign.

The HRV series below is his own, read from ``coach.daily_metrics`` (morning phase) on
28-29 Sep 2026. 13 Jul has no morning row.
"""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.models.coaching import (
    DAILY_METRIC_PHASE_MORNING,
    Analysis,
    DailyMetric,
    ManualEntry,
    MetricBaseline,
    PlannedWorkout,
    Sleep,
    WorkoutDeliveryProposal,
)
from src.models.profile import Profile, UserRole
from src.routers.daily_loop_schemas import ManualEntryBody
from src.services.chronic_patterns import (
    RecoveryDay,
    VerdictDay,
    _check_in_training_context,
    _chronic_action_signal,
    _red_day_evidence,
)
from src.services.executable_coaching import ExecutableCoachingService
from src.services.morning_analysis import (
    GRADED_SYMPTOM_FLOOR_RULE,
    LADDER_SYSTEM_PROMPT,
    PROMPT_VERSION,
    SYMPTOM_FLOOR_RULE,
    SYSTEM_PROMPT,
    _manual_entry_packet,
)
from src.services.morning_verdict import (
    ACUTE_BASELINE_MIN_SAMPLES,
    ACUTE_BASELINE_WINDOW_DAYS,
    HRV_HOLD_PLAN_LINE,
    _hrv_rail,
    morning_verdict,
    should_recommend_breathwork,
)
from src.services.recent_mornings import MorningCall, build_recent_mornings
from src.services.symptom_check import (
    SYMPTOM_ANSWERS,
    SYMPTOM_FLOORS,
    SYMPTOMS_CHEST_HEART,
    SYMPTOMS_FEVER_ACHES,
    SYMPTOMS_HEAD_COLD,
    SYMPTOMS_NONE,
)

USER_ID = uuid.uuid4()

HRV_SERIES: tuple[tuple[date, int | None], ...] = (
    (date(2026, 6, 21), 46), (date(2026, 6, 22), None), (date(2026, 6, 23), None),
    (date(2026, 6, 24), None), (date(2026, 6, 25), 53), (date(2026, 6, 26), 38),
    (date(2026, 6, 27), 45), (date(2026, 6, 28), 48), (date(2026, 6, 29), 52),
    (date(2026, 6, 30), 49), (date(2026, 7, 1), 51), (date(2026, 7, 2), 43),
    (date(2026, 7, 3), 59), (date(2026, 7, 4), 50), (date(2026, 7, 5), 46),
    (date(2026, 7, 6), 52), (date(2026, 7, 7), 41), (date(2026, 7, 8), 46),
    (date(2026, 7, 9), 43), (date(2026, 7, 10), 47), (date(2026, 7, 11), 49),
    (date(2026, 7, 12), 56), (date(2026, 7, 14), 52), (date(2026, 7, 15), 45),
    (date(2026, 7, 16), 33), (date(2026, 7, 17), 42), (date(2026, 7, 18), 47),
    (date(2026, 7, 19), 38), (date(2026, 7, 20), 47), (date(2026, 7, 21), 47),
    (date(2026, 7, 22), 46), (date(2026, 7, 23), 46), (date(2026, 7, 24), 46),
    (date(2026, 7, 25), 47), (date(2026, 7, 26), 51), (date(2026, 7, 27), 56),
    (date(2026, 7, 28), 53), (date(2026, 7, 29), 53), (date(2026, 7, 30), 51),
    (date(2026, 7, 31), 52), (date(2026, 8, 1), 35), (date(2026, 8, 2), 43),
    (date(2026, 8, 3), 48), (date(2026, 8, 4), 47), (date(2026, 8, 5), 41),
    (date(2026, 8, 6), 49), (date(2026, 8, 7), 38), (date(2026, 8, 8), 44),
    (date(2026, 8, 9), 49), (date(2026, 8, 10), 52), (date(2026, 8, 11), 43),
    (date(2026, 8, 12), 39), (date(2026, 8, 13), 50), (date(2026, 8, 14), 54),
    (date(2026, 8, 15), 50), (date(2026, 8, 16), 45), (date(2026, 8, 17), 46),
    (date(2026, 8, 18), 42), (date(2026, 8, 19), 54), (date(2026, 8, 20), 44),
    (date(2026, 8, 21), 51), (date(2026, 8, 22), 60), (date(2026, 8, 23), 51),
    (date(2026, 8, 24), 49), (date(2026, 8, 25), 51), (date(2026, 8, 26), 46),
    (date(2026, 8, 27), 47), (date(2026, 8, 28), 43), (date(2026, 8, 29), 48),
    (date(2026, 8, 30), 44), (date(2026, 8, 31), 47), (date(2026, 9, 1), 44),
    (date(2026, 9, 2), 50), (date(2026, 9, 3), 51), (date(2026, 9, 4), 54),
    (date(2026, 9, 5), 51), (date(2026, 9, 6), 49), (date(2026, 9, 7), 48),
    (date(2026, 9, 8), 43), (date(2026, 9, 9), 49), (date(2026, 9, 10), 51),
    (date(2026, 9, 11), 52), (date(2026, 9, 12), 48), (date(2026, 9, 13), 42),
    (date(2026, 9, 14), 47), (date(2026, 9, 15), 42), (date(2026, 9, 16), 44),
    (date(2026, 9, 17), 43), (date(2026, 9, 18), 48), (date(2026, 9, 19), 45),
    (date(2026, 9, 20), 46), (date(2026, 9, 21), 37), (date(2026, 9, 22), 39),
    (date(2026, 9, 23), 45), (date(2026, 9, 24), 47), (date(2026, 9, 25), 44),
    (date(2026, 9, 26), 46), (date(2026, 9, 27), 48), (date(2026, 9, 28), 48),
)  # fmt: skip


def _metric(
    day: date,
    last_night_hrv: int | None,
    *,
    resting_hr: int = 44,
    weekly: int = 47,
    status: str = "BALANCED",
) -> DailyMetric:
    return DailyMetric(
        user_id=USER_ID,
        calendar_date=day,
        phase=DAILY_METRIC_PHASE_MORNING,
        readiness_score=75,
        readiness_level="HIGH",
        hrv_last_night_avg_ms=last_night_hrv,
        hrv_weekly_avg_ms=weekly,
        hrv_baseline_low_ms=44,
        hrv_baseline_high_ms=56,
        hrv_status=status,
        resting_heart_rate_bpm=resting_hr,
        raw_payload={},
    )


def _history(before: date) -> list[DailyMetric]:
    return [_metric(day, value) for day, value in HRV_SERIES if day < before]


def _sleep(day: date) -> Sleep:
    return Sleep(
        user_id=USER_ID,
        calendar_date=day,
        score=84,
        average_spo2_pct=96,
        lowest_spo2_pct=92,
        average_respiration=11,
        factors_json={},
        raw_payload={},
    )


def _baseline(metric_key: str, *, median: float, upper: float, lower: float) -> MetricBaseline:
    return MetricBaseline(
        user_id=USER_ID,
        metric_key=metric_key,
        metric_label=metric_key,
        source="db_history",
        window_start_date=date(2026, 7, 6),
        window_end_date=date(2026, 9, 27),
        sample_count=84,
        excluded_sample_count=0,
        median_value=median,
        lower_quartile_value=lower,
        upper_quartile_value=upper,
    )


# Production's own baselines on 28 Sep 2026.
BASELINES = {
    "resting_heart_rate_bpm": _baseline("resting_heart_rate_bpm", median=44, lower=43, upper=45),
    "readiness_score": _baseline("readiness_score", median=68, lower=55, upper=77),
    "average_spo2_pct": _baseline("average_spo2_pct", median=96, lower=95, upper=97),
    "average_respiration": _baseline("average_respiration", median=11, lower=11, upper=12),
}


def _bike(day: date, *, vo2: bool = False) -> PlannedWorkout:
    steps: list[dict[str, Any]] = (
        [
            {"label": "Warm-up", "minutes": 15, "target": "easy spin"},
            {"label": "VO2 work", "minutes": 12, "target": "110% FTP"},
            {"label": "Cool-down", "minutes": 10, "target": "easy spin"},
        ]
        if vo2
        else [{"label": "Endurance", "minutes": 75, "target": "65-72% FTP"}]
    )
    return PlannedWorkout(
        user_id=USER_ID,
        workout_date=day,
        version=1,
        title="VO2 Max" if vo2 else "Z2 Endurance",
        workout_type="bike_vo2" if vo2 else "bike_endurance",
        status="planned",
        is_active=True,
        source="test",
        structured_workout={"format": "bike", "steps": steps},
    )


def _strength(day: date) -> PlannedWorkout:
    return PlannedWorkout(
        user_id=USER_ID,
        workout_date=day,
        version=2,
        title="Bodyweight",
        workout_type="strength",
        status="planned",
        is_active=True,
        source="test",
        structured_workout={"format": "strength", "focus": "full body"},
    )


def _check_in(day: date, symptoms: str | None, *, feel: int | None = 7) -> ManualEntry:
    return ManualEntry(
        user_id=USER_ID,
        entry_date=day,
        entry_at_utc=datetime.combine(day, datetime.min.time()) + timedelta(hours=7),
        subjective_score=feel,
        symptoms=symptoms,
    )


# A clean morning in every respect but the one under test: 23 Sep's numbers with a
# balanced week, so the ladder alone says Green.
CLEAN_DAY = date(2026, 9, 23)


def _verdict(
    day: date = CLEAN_DAY,
    *,
    symptoms: str | None = None,
    checked_in: bool = True,
    last_night_hrv: int | None = None,
    resting_hr: int = 44,
    prior_resting_hr: int | None = None,
    planned: list[PlannedWorkout] | None = None,
    rest_day: bool = False,
) -> dict[str, Any]:
    overnight = last_night_hrv if last_night_hrv is not None else dict(HRV_SERIES)[day]
    history = _history(day)
    if prior_resting_hr is not None:
        history[-1] = _metric(history[-1].calendar_date, history[-1].hrv_last_night_avg_ms,
                              resting_hr=prior_resting_hr)  # fmt: skip
    return morning_verdict(
        daily_metric=_metric(day, overnight, resting_hr=resting_hr),
        sleep=_sleep(day),
        age_adjusted_sleep_score=84,
        manual_entries=[_check_in(day, symptoms)] if checked_in else [],
        planned_workouts=planned if planned is not None else [_bike(day)],
        baselines=BASELINES,
        yesterday_load={"status": "moderate"},
        rest_day={"isRestDay": True, "reason": "holiday"} if rest_day else None,
        recent_daily_metrics=history,
        recent_sleeps=[],
        enforce_data_sufficiency=True,
    )


_ILLNESS_TALK = re.compile(r"\b(infection|illness|ill|unwell|gp|doctor)\b", re.I)


# -- the question ---------------------------------------------------------------------


def test_the_answers_match_the_column_constraint() -> None:
    """The model, migration 033 and the module list the same four answers."""
    from pathlib import Path

    from src.models.coaching import ManualEntry as Model

    constraint = next(
        str(c.sqltext)  # type: ignore[attr-defined]
        for c in Model.__table__.constraints
        if c.name == "ck_manual_entries_symptoms"
    )
    migration = (
        Path(__file__).resolve().parents[3] / "migrations/versions/033_manual_entry_symptoms.py"
    ).read_text()
    for answer in SYMPTOM_ANSWERS:
        assert f"'{answer}'" in constraint
        assert f"'{answer}'" in migration
    assert set(SYMPTOM_FLOORS) == set(SYMPTOM_ANSWERS) - {SYMPTOMS_NONE}


def test_the_check_in_body_accepts_only_the_four_answers() -> None:
    assert ManualEntryBody(symptoms="head_cold").symptoms == "head_cold"
    assert ManualEntryBody().symptoms is None  # an older client: the stored answer stands
    with pytest.raises(ValidationError):
        ManualEntryBody(symptoms="flu")


def test_the_packet_carries_his_answer() -> None:
    packet = _manual_entry_packet(_check_in(CLEAN_DAY, SYMPTOMS_HEAD_COLD))
    assert packet["symptoms"] == "head_cold"
    assert _manual_entry_packet(_check_in(CLEAN_DAY, None))["symptoms"] is None


# -- the floors -------------------------------------------------------------------------


def test_a_clean_morning_is_green_whatever_none_or_no_answer() -> None:
    answered_none = _verdict(symptoms=SYMPTOMS_NONE)
    unanswered = _verdict(symptoms=None)
    no_check_in = _verdict(checked_in=False)

    for verdict in (answered_none, unanswered, no_check_in):
        assert verdict["status"] == "Green"
        assert verdict["acutePhysiology"]["symptoms"]["triggered"] is False
        assert verdict["acutePhysiology"]["requiresTrainingRest"] is False
        assert verdict["acutePhysiology"]["escalations"] == []
    assert answered_none["planAdjustments"] == unanswered["planAdjustments"]
    # No answer is recorded as no answer, never as "None".
    assert answered_none["acutePhysiology"]["symptoms"]["answered"] is True
    assert unanswered["acutePhysiology"]["symptoms"]["answered"] is False
    assert no_check_in["acutePhysiology"]["symptoms"]["answer"] is None


@pytest.mark.parametrize(
    ("answer", "level", "safety_rule"),
    [
        (SYMPTOMS_CHEST_HEART, "rest", "symptom_no_training_floor"),
        (SYMPTOMS_FEVER_ACHES, "rest", "symptom_no_training_floor"),
    ],
)
def test_chest_heart_and_fever_rule_out_training_of_any_kind(
    answer: str, level: str, safety_rule: str
) -> None:
    floor = SYMPTOM_FLOORS[answer]
    verdict = _verdict(symptoms=answer, planned=[_bike(CLEAN_DAY), _strength(CLEAN_DAY)])
    acute = verdict["acutePhysiology"]

    assert verdict["status"] == "Red"
    assert verdict["reasons"][0] == floor.reason
    # The one no-training line, and nothing that trains: at most the evening breathwork
    # suggestion, which a chest-or-heart morning drops as well.
    assert verdict["planAdjustments"][0] == floor.plan_line
    assert all("breathwork" in line for line in verdict["planAdjustments"][1:]), verdict[
        "planAdjustments"
    ]
    if answer == SYMPTOMS_CHEST_HEART:
        assert verdict["planAdjustments"] == [floor.plan_line]
    assert acute["requiresTrainingRest"] is True
    assert acute["requiresBikeRest"] is True
    assert acute["triggeredSignals"][0] == "symptoms"
    assert acute["escalations"][0] == {"kind": "symptoms", "level": level, "message": floor.notice}
    assert safety_rule in verdict["safetyRulesApplied"]


def test_the_notices_are_the_signed_off_words() -> None:
    # Batch 303 (signed off 2 Oct 2026): the answer also covers unusual breathlessness,
    # and struggling to breathe joins chest pain as a reason to call 999.
    assert SYMPTOM_FLOORS[SYMPTOMS_CHEST_HEART].notice == (
        "You've told me about chest pain, a racing or irregular heartbeat, feeling faint, or "
        "unusual breathlessness. That needs a doctor's view before any training, so no "
        "training of any kind today. Speak to your GP or call 111 today. If you have chest "
        "pain or are struggling to breathe right now, call 999."
    )
    assert SYMPTOM_FLOORS[SYMPTOMS_FEVER_ACHES].notice == (
        "You've told me about a fever, aches or a chest infection. Training through that adds "
        "strain your body doesn't need and usually makes it last longer, so no training of "
        "any kind until the symptoms have gone. When you're clear, build back gradually: a "
        "few easy days before anything hard."
    )
    assert SYMPTOM_FLOORS[SYMPTOMS_HEAD_COLD].notice == (
        "You've told me you have a head cold — symptoms above the neck. Easy riding at most "
        "today, and only if you feel up to it: nothing hard, no intervals and no VO₂. If it "
        "moves below the neck — a fever, aches or a chesty cough — stop training until "
        "you're clear."
    )


def test_a_head_cold_is_red_on_the_easy_path() -> None:
    verdict = _verdict(symptoms=SYMPTOMS_HEAD_COLD)
    acute = verdict["acutePhysiology"]

    assert verdict["status"] == "Red"
    assert verdict["reasons"][0] == SYMPTOM_FLOORS[SYMPTOMS_HEAD_COLD].reason
    assert acute["requiresTrainingRest"] is False
    assert acute["requiresBikeRest"] is False
    assert acute["escalations"][0]["level"] == "ease"
    # The app's ordinary Red ride: a Zone 2 ride stays Zone 2, shorter.
    assert verdict["planAdjustments"][0].startswith("Hold Zone 2")
    assert "symptom_easy_riding_floor" in verdict["safetyRulesApplied"]


def test_a_head_cold_turns_a_vo2_day_into_an_easy_one() -> None:
    verdict = _verdict(symptoms=SYMPTOMS_HEAD_COLD, planned=[_bike(CLEAN_DAY, vo2=True)])

    assert verdict["status"] == "Red"
    assert verdict["planAdjustments"][0] == "Substitute recovery, mobility, or rest."
    assert "Replace VO2 with rest, mobility, or a very easy spin." in verdict["planAdjustments"]
    assert "red_never_vo2" in verdict["safetyRulesApplied"]


def test_a_floor_withdraws_a_hold() -> None:
    """A hold is Green with its targets held; a symptom floor outranks it and says so."""
    day = CLEAN_DAY
    history = _history(day)

    def verdict_with(symptoms: str | None) -> dict[str, Any]:
        return morning_verdict(
            daily_metric=_metric(day, 45, weekly=43, status="UNBALANCED"),
            sleep=_sleep(day),
            age_adjusted_sleep_score=84,
            manual_entries=[_check_in(day, symptoms)],
            planned_workouts=[_bike(day)],
            baselines=BASELINES,
            recent_daily_metrics=history,
            enforce_data_sufficiency=True,
        )

    hold = verdict_with(None)
    assert hold["status"] == "Green"
    assert hold["hrvGradedResponse"]["tier"] == "hold"
    assert HRV_HOLD_PLAN_LINE in hold["planAdjustments"]

    floored = verdict_with(SYMPTOMS_HEAD_COLD)
    assert floored["status"] == "Red"
    assert floored["hrvGradedResponse"]["tier"] == "ease"
    assert floored["hrvGradedResponse"]["heldBackBy"] == "symptom_floor"


def test_a_rest_day_keeps_its_rest_line_under_a_floor() -> None:
    verdict = _verdict(symptoms=SYMPTOMS_FEVER_ACHES, rest_day=True)

    assert verdict["status"] == "Red"
    assert verdict["planAdjustments"][0] == (
        "Today is an intentional rest day; keep paused or skipped sessions paused."
    )
    assert SYMPTOM_FLOORS[SYMPTOMS_FEVER_ACHES].plan_line not in verdict["planAdjustments"]


def test_breathwork_is_not_suggested_on_a_chest_or_heart_morning() -> None:
    chest = _verdict(symptoms=SYMPTOMS_CHEST_HEART)
    fever = _verdict(symptoms=SYMPTOMS_FEVER_ACHES)

    assert not any("breathwork" in line for line in chest["planAdjustments"])
    assert any("breathwork" in line for line in fever["planAdjustments"])
    assert should_recommend_breathwork({"status": "Red", "symptomsAnswer": "chest_heart"}) is False
    assert should_recommend_breathwork({"status": "Red", "symptomsAnswer": "fever_aches"}) is True


def test_a_bike_rest_morning_never_offers_a_very_easy_spin() -> None:
    """Found at /batch-start: a Red morning with VO2 planned appended "a very easy spin"
    after "Take today off the bike"."""
    verdict = _verdict(
        day=date(2026, 9, 22),
        symptoms=SYMPTOMS_HEAD_COLD,
        planned=[_bike(date(2026, 9, 22), vo2=True)],
    )

    assert verdict["status"] == "Red"
    assert verdict["acutePhysiology"]["requiresBikeRest"] is True
    assert verdict["planAdjustments"][0] == (
        "Take today off the bike; do not substitute an eased ride for the acute signal."
    )
    assert not any("easy spin" in line for line in verdict["planAdjustments"])
    assert "red_never_vo2" in verdict["safetyRulesApplied"]


# -- the overnight-HRV rail, replayed on his own series --------------------------------


def _replay() -> tuple[int, list[date], list[date]]:
    eligible = 0
    fired: list[date] = []
    rested: list[date] = []
    for day, value in HRV_SERIES:
        if value is None:
            continue
        start = day - timedelta(days=ACUTE_BASELINE_WINDOW_DAYS)
        prior = [row for row in _history(day) if row.calendar_date >= start]
        rail = _hrv_rail(_metric(day, value), prior)
        if rail["baselineSampleCount"] < ACUTE_BASELINE_MIN_SAMPLES:
            continue
        eligible += 1
        if rail["triggered"]:
            fired.append(day)
        if rail["requiresBikeRest"]:
            rested.append(day)
    return eligible, fired, rested


def test_the_six_firing_mornings_rest_the_bike_on_16_jul_only() -> None:
    eligible, fired, rested = _replay()

    assert eligible == 75
    assert fired == [
        date(2026, 7, 16),
        date(2026, 7, 19),
        date(2026, 8, 1),
        date(2026, 8, 7),
        date(2026, 9, 21),
        date(2026, 9, 22),
    ]
    assert rested == [date(2026, 7, 16)]


def test_22_sep_caps_at_amber_without_bike_rest_or_illness_talk() -> None:
    verdict = _verdict(day=date(2026, 9, 22))
    hrv = verdict["acutePhysiology"]["overnightHrv"]

    assert verdict["status"] == "Amber"
    assert hrv["triggered"] is True
    assert hrv["illnessGrade"] is False
    assert hrv["requiresBikeRest"] is False
    assert verdict["acutePhysiology"]["requiresBikeRest"] is False
    assert verdict["acutePhysiology"]["escalations"] == [
        {
            "kind": "overnight_hrv",
            "level": "ease",
            "message": (
                "Your overnight HRV is 39 ms this morning against a usual 47 ms — lower than "
                "most nights for you. Dips like this usually come from a short night, a "
                "drink, a busy week or a hard day before. On its own it caps today at Amber: "
                "an eased session, not a day off the bike."
            ),
        }
    ]
    assert not _ILLNESS_TALK.search(hrv["escalation"])
    assert not any("off the bike" in line for line in verdict["planAdjustments"])


def test_16_jul_still_rests_the_bike() -> None:
    verdict = _verdict(day=date(2026, 7, 16))
    hrv = verdict["acutePhysiology"]["overnightHrv"]

    assert hrv["illnessGrade"] is True
    assert verdict["acutePhysiology"]["requiresBikeRest"] is True
    assert verdict["acutePhysiology"]["escalations"][0]["level"] == "rest"
    assert "a drop that size in a single night is unusual for you" in hrv["escalation"]
    assert verdict["planAdjustments"] == [
        "Take today off the bike; do not substitute an eased ride for the acute signal."
    ]


def test_a_capped_dip_with_a_resting_hr_rise_rests_the_bike() -> None:
    # Batch 305: a rise of 4 bpm over his median corroborates the dip, though on its own
    # it does not trigger the resting-HR rail at all.
    verdict = _verdict(day=date(2026, 9, 22), resting_hr=48)
    hrv = verdict["acutePhysiology"]["overnightHrv"]

    assert verdict["acutePhysiology"]["restingHeartRate"]["triggered"] is False
    assert verdict["acutePhysiology"]["restingHeartRate"]["requiresBikeRest"] is False
    assert hrv["corroboratedBy"] == ["resting_heart_rate"]
    assert hrv["requiresBikeRest"] is True
    assert hrv["escalation"] == (
        "Your overnight HRV is 39 ms this morning against a usual 47 ms, and your resting "
        "heart rate is up as well. Either on its own would only cap the day; together they "
        "are worth respecting. Take today off the bike. If you feel unwell, rest until it "
        "settles, and see your GP if it doesn't."
    )


def test_a_capped_dip_with_a_head_cold_rests_the_bike_and_the_notices_agree() -> None:
    verdict = _verdict(day=date(2026, 9, 22), symptoms=SYMPTOMS_HEAD_COLD)
    acute = verdict["acutePhysiology"]

    assert verdict["status"] == "Red"
    assert acute["overnightHrv"]["corroboratedBy"] == ["symptom_answer"]
    assert "you've told me you have a head cold" in acute["overnightHrv"]["escalation"]
    assert acute["requiresBikeRest"] is True
    # The cold's own notice says "easy riding at most", so it never contradicts this.
    assert [item["level"] for item in acute["escalations"]] == ["ease", "rest"]
    assert "at most" in acute["escalations"][0]["message"]


def test_the_working_states_the_off_the_bike_line() -> None:
    verdict = _verdict(day=date(2026, 9, 22))
    hrv = verdict["acutePhysiology"]["overnightHrv"]
    (entry,) = hrv["provenance"]

    assert hrv["illnessLineMs"] == 34.6
    assert entry["sources"]["illnessLineMs"] == 34.6
    assert entry["sources"]["illnessStddevsBelowMedian"] == 2.5
    assert entry["sources"]["illnessFractionBelowMedian"] == 0.3
    assert "rests the bike only at 2.5 standard deviations or 30%" in entry["rule"]


# -- every consumer keeps one meaning ---------------------------------------------------


def test_recent_mornings_reads_no_training_for_every_session() -> None:
    day = date(2026, 10, 8)
    call = MorningCall(
        subject_date=day,
        generated_at_utc=datetime(2026, 10, 8, 7, 30),
        verdict="Red",
        reasons=[SYMPTOM_FLOORS[SYMPTOMS_FEVER_ACHES].reason],
        verdict_adjustment=None,
        requires_bike_rest=True,
        rest_day={"isRestDay": False},
        planned_workouts=[
            {"id": str(uuid.uuid4()), "title": "Z2 Endurance", "workoutType": "bike_endurance"},
            {"id": str(uuid.uuid4()), "title": "Bodyweight", "workoutType": "strength"},
        ],
        requires_training_rest=True,
    )
    section = build_recent_mornings(today=day, mornings=[call], audits=[])
    today = section["days"][0]

    assert today["noTrainingAdvised"] is True
    assert [s["morningCall"] for s in today["sessions"]] == [
        "no_training_advised",
        "no_training_advised",
    ]
    assert "no_training_advised" in section["meaning"]


def test_a_bike_rest_morning_still_leaves_strength_unchanged_in_recent_mornings() -> None:
    day = date(2026, 10, 8)
    call = MorningCall(
        subject_date=day,
        generated_at_utc=datetime(2026, 10, 8, 7, 30),
        verdict="Amber",
        reasons=[],
        verdict_adjustment=None,
        requires_bike_rest=True,
        rest_day={"isRestDay": False},
        planned_workouts=[
            {"id": str(uuid.uuid4()), "title": "Z2 Endurance", "workoutType": "bike_endurance"},
            {"id": str(uuid.uuid4()), "title": "Bodyweight", "workoutType": "strength"},
        ],
    )
    today = build_recent_mornings(today=day, mornings=[call], audits=[])["days"][0]

    assert [s["morningCall"] for s in today["sessions"]] == ["no_bike_advised", "unchanged"]
    assert "noTrainingAdvised" not in today


def _recovery_day(day: date) -> RecoveryDay:
    return RecoveryDay(
        calendar_date=day,
        readiness_score=70,
        hrv_7_day_avg_ms=47,
        resting_heart_rate_bpm=44,
        hrv_last_night_avg_ms=47,
        hrv_status="balanced",
        hrv_baseline_low_ms=44,
        hrv_baseline_high_ms=56,
    )


def test_a_tapped_cold_counts_as_illness_for_the_two_reds_rule() -> None:
    first, second = date(2026, 10, 7), date(2026, 10, 8)
    rows = [
        ManualEntry(
            user_id=USER_ID,
            entry_date=first,
            entry_at_utc=datetime(2026, 10, 7, 7),
            notes="Room felt cold from the draught again.",
        ),
        _check_in(second, SYMPTOMS_HEAD_COLD),
    ]
    evidence = _red_day_evidence(
        [_recovery_day(first), _recovery_day(second)], manual_rows=rows, baselines={}
    )

    # Batch 212's bedroom note is still not illness; the tap is.
    assert "illness" not in evidence[first].check_in_reasons
    assert evidence[second].check_in_reasons == ("illness",)

    signal = _chronic_action_signal(
        [],
        [VerdictDay(first, "Red"), VerdictDay(second, "Red")],
        as_of=second,
        red_day_evidence=evidence,
    )
    by_date = {item.calendar_date: item for item in signal.red_morning_qualifications}
    assert by_date[second].classification == "explained_by_acute_check_in"
    assert signal.triggered is False

    (context,) = [
        item for item in _check_in_training_context(rows) if item.source == "symptom_answer"
    ]
    assert context.to_packet() == {
        "startDate": "2026-10-08",
        "endDate": "2026-10-08",
        "reason": "illness",
        "source": "symptom_answer",
        "matchedText": "A head cold, above the neck",
        "basis": "his answer to the check-in's symptom question",
    }


def test_a_chest_or_heart_answer_is_not_an_illness_excuse() -> None:
    day = date(2026, 10, 8)
    evidence = _red_day_evidence(
        [_recovery_day(day)], manual_rows=[_check_in(day, SYMPTOMS_CHEST_HEART)], baselines={}
    )
    assert evidence[day].check_in_reasons == ()


# -- the brief ---------------------------------------------------------------------------


def test_the_brief_is_told_what_the_floors_mean_and_the_version_moved() -> None:
    # The ladder's rollback prompt keeps the rule verbatim; since Batch 298 the graded
    # prompt carries it with its last sentence in the graded verdict's words.
    assert SYMPTOM_FLOOR_RULE in LADDER_SYSTEM_PROMPT
    assert GRADED_SYMPTOM_FLOOR_RULE in SYSTEM_PROMPT
    for text in (SYMPTOM_FLOOR_RULE, GRADED_SYMPTOM_FLOOR_RULE):
        rule = " ".join(text.split())
        assert "requiresTrainingRest" in rule
        assert "never evidence that he is well" in rule
    # A self-healing bump: the next generation writes v50 and nothing is withdrawn.
    # (Batch 296 moved it on again, to v51; Batch 298 to v53.)
    assert PROMPT_VERSION == "morning-analysis-v56-2026-10-03"


# -- the delivery rail (Postgres; CI is its first run) ----------------------------------


@pytest.mark.asyncio
async def test_a_no_training_floor_withholds_the_ride_proposal(db_conn: AsyncConnection) -> None:
    """``regenerate_for_verdict`` only ever proposes bike sessions, so the floor's reach
    there is the day's ride. Driven with the real verdict each answer produces."""
    subject = CLEAN_DAY
    user_id = uuid.uuid4()
    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        session.add(
            Profile(
                id=user_id,
                display_name="Symptom Floors",
                role=UserRole.admin,
                timezone="Europe/London",
                is_active=True,
            )
        )
        await session.flush()
        session.add(
            PlannedWorkout(
                id=uuid.uuid4(),
                user_id=user_id,
                workout_date=subject,
                version=1,
                title="VO2 Max 30/30",
                workout_type="bike_vo2",
                status="planned",
                is_active=True,
                planned_duration_min=60,
                intensity_target="105-110% FTP",
                structured_workout={
                    "format": "bike",
                    "steps": [
                        {"label": "Warm-up", "minutes": 15, "target": "easy spin"},
                        {
                            "label": "Main set",
                            "repeats": 3,
                            "pattern": "5x 30s on / 30s off",
                            "target": "105-110% FTP 95rpm",
                        },
                        {"label": "Cool-down", "minutes": 10, "target": "easy spin"},
                    ],
                },
                source="test",
            )
        )
        await session.commit()

    def morning(answer: str) -> Analysis:
        verdict = _verdict(symptoms=answer, planned=[_bike(subject, vo2=True)])
        return Analysis(
            user_id=user_id,
            analysis_type="morning",
            subject_date=subject,
            generated_at_utc=datetime(2026, 9, 23, 7, 30),
            prompt_version="morning-analysis-test",
            verdict=verdict["status"],
            context_packet={"verdict": verdict},
            output_markdown="Red verdict",
            raw_response={},
        )

    async with AsyncSession(bind=db_conn, expire_on_commit=False) as session:
        user = await session.get(Profile, user_id)
        assert user is not None
        service = ExecutableCoachingService(session)

        for answer in (SYMPTOMS_CHEST_HEART, SYMPTOMS_FEVER_ACHES):
            assert (
                await service.regenerate_for_verdict(user, subject, analysis=morning(answer)) == []
            )
        assert (await session.execute(select(WorkoutDeliveryProposal))).scalars().all() == []

        # A head cold is Red on the easy path, so the easy substitute is still offered.
        offered = await service.regenerate_for_verdict(
            user, subject, analysis=morning(SYMPTOMS_HEAD_COLD)
        )
        assert len(offered) == 1
        assert offered[0].structured_workout_ir["origin"] == "red_substitution"
