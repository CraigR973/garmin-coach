"""Batch 269 — a lagging average, or a moved floor, is not a worse night.

Between 18 and 26 Sep 2026 Mark's mornings went Red eight times on one rule:
Garmin's 7-day HRV average under its floor, with the status UNBALANCED. On four of
them his own overnight reading was at or above the floor (18, 23, 24 and 26 Sep),
and on two Garmin had moved the floor under a reading that held (18 and 19 Sep,
Batch 271's detector). He called it "a sledgehammer to crack a nut", and on 23 Sep
asked that last night's reading "be recognised and soften any change".

Every row is his own, read on 27 Sep 2026 from ``coach.daily_metrics`` (morning
phase), ``coach.sleep`` and his check-ins:

    date    overnight weekly floor  readiness  RHR  sleep raw/age  feel  was
    18 Sep     48       45    46    HIGH 78    44      87/95        8    Red
    19 Sep     45       45    46    HIGH 77    43      79/83        6    Red
    21 Sep     37       44    45    MOD  66    45      70/74        7    Red
    22 Sep     39       43    45    HIGH 78    44      82/82        7    Red
    23 Sep     45       43    45    HIGH 79    45      87/87        8    Red
    24 Sep     47       44    45    MOD  67    45      72/76        7    Red
    25 Sep     44       43    45    MOD  63    46      87/87        -    Red
    26 Sep     46       43    45    MOD  68    46      80/84        7    Red

What the batch decides (Mark's G3 answers, made on his behalf while he is away;
Craig, 27 Sep): a morning whose only mark is Garmin's weekly HRV signal — his own
overnight reading at or above the floor, or the floor moved under a reading that
held — keeps the full session with its targets held, and stays Green. Resting heart
rate above his usual range, readiness below it or Garmin's Low, a poor night and a
low check-in each still ease a session on their own, and any one of them beside the
HRV flag makes the day Amber rather than a hold.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Any

import pytest

from src.models.coaching import (
    DAILY_METRIC_PHASE_MORNING,
    DailyMetric,
    ManualEntry,
    MetricBaseline,
    PlannedWorkout,
    Sleep,
)
from src.services.hrv_recalibration import is_band_artifact
from src.services.morning_analysis import (
    HRV_GRADED_RESPONSE_RULE,
    PROMPT_VERSION,
    SYSTEM_PROMPT,
)
from src.services.morning_verdict import (
    HRV_HOLD_PLAN_LINE,
    HRV_RED_REASON,
    morning_verdict,
)
from src.services.verdict_scaling import blocks_red_vo2
from src.services.workout_delivery import build_structured_workout_ir

USER_ID = uuid.uuid4()

# (day, overnight, weekly, floor, ceiling, status, readiness level, readiness score,
#  resting HR, raw sleep, age-adjusted sleep, check-in feel), exactly as production
# holds them. It starts on 28 Aug because the recalibration detector reads 14 days
# back and the acute HRV rail needs 21 nights: a fixture shorter than the longest
# window the code reads tests a different history from the one production sees
# (the bug Batch 271's own fixture shipped once).
PRODUCTION_SERIES: tuple[tuple[Any, ...], ...] = (
    (date(2026, 8, 28), 43, 49, 44, 56, "BALANCED", "LOW", 26, 44, 54, 58, 6),
    (date(2026, 8, 29), 48, 48, 44, 56, "BALANCED", "MODERATE", 53, 43, 80, 88, 7),
    (date(2026, 8, 30), 44, 47, 44, 56, "BALANCED", "LOW", 43, 46, 57, 61, 6),
    (date(2026, 8, 31), 47, 47, 44, 56, "BALANCED", "MODERATE", 65, 44, 84, 88, 6),
    (date(2026, 9, 1), 44, 46, 44, 56, "BALANCED", "MODERATE", 72, 41, 78, 82, 6),
    (date(2026, 9, 2), 50, 46, 44, 56, "BALANCED", "MODERATE", 61, 43, 68, 76, 6),
    (date(2026, 9, 3), 51, 47, 44, 56, "BALANCED", "MODERATE", 71, 42, 79, 83, 6),
    (date(2026, 9, 4), 54, 48, 44, 56, "BALANCED", "LOW", 47, 45, 79, 87, 7),
    (date(2026, 9, 5), 51, 49, 44, 56, "BALANCED", "HIGH", 80, 44, 91, 95, 8),
    (date(2026, 9, 6), 49, 49, 44, 56, "BALANCED", "HIGH", 75, 44, 82, 86, 7),
    (date(2026, 9, 7), 48, 49, 44, 56, "BALANCED", "MODERATE", 51, 45, 53, 53, 6),
    (date(2026, 9, 8), 43, 49, 44, 56, "BALANCED", "MODERATE", 74, 45, 87, 87, 7),
    (date(2026, 9, 9), 49, 49, 44, 56, "BALANCED", "HIGH", 84, 44, 92, 92, 8),
    (date(2026, 9, 10), 51, 49, 44, 56, "BALANCED", "HIGH", 89, 44, 83, 91, 7),
    (date(2026, 9, 11), 52, 49, 45, 56, "BALANCED", "MODERATE", 57, 44, 78, 82, None),
    (date(2026, 9, 12), 48, 48, 45, 56, "BALANCED", "HIGH", 79, 45, 77, 81, 7),
    (date(2026, 9, 13), 42, 47, 45, 56, "BALANCED", "MODERATE", 66, 45, 68, 76, 6),
    (date(2026, 9, 14), 47, 47, 45, 56, "BALANCED", "HIGH", 79, 44, 84, 84, 7),
    (date(2026, 9, 15), 42, 47, 45, 56, "BALANCED", "HIGH", 78, 43, 76, 80, 7),
    (date(2026, 9, 16), 44, 47, 45, 56, "BALANCED", "HIGH", 76, 43, 75, 79, 6),
    (date(2026, 9, 17), 43, 45, 45, 56, "BALANCED", "HIGH", 81, 45, 84, 84, 7),
    (date(2026, 9, 18), 48, 45, 46, 56, "UNBALANCED", "HIGH", 78, 44, 87, 95, 8),
    (date(2026, 9, 19), 45, 45, 46, 56, "UNBALANCED", "HIGH", 77, 43, 79, 83, 6),
    (date(2026, 9, 20), 46, 45, 45, 55, "BALANCED", "HIGH", 83, 43, 87, 87, 8),
    (date(2026, 9, 21), 37, 44, 45, 55, "UNBALANCED", "MODERATE", 66, 45, 70, 74, 7),
    (date(2026, 9, 22), 39, 43, 45, 55, "UNBALANCED", "HIGH", 78, 44, 82, 82, 7),
    (date(2026, 9, 23), 45, 43, 45, 55, "UNBALANCED", "HIGH", 79, 45, 87, 87, 8),
    (date(2026, 9, 24), 47, 44, 45, 55, "UNBALANCED", "MODERATE", 67, 45, 72, 76, 7),
    (date(2026, 9, 25), 44, 43, 45, 55, "UNBALANCED", "MODERATE", 63, 46, 87, 87, None),
    (date(2026, 9, 26), 46, 43, 45, 55, "UNBALANCED", "MODERATE", 68, 46, 80, 84, 7),
)

# The prior day's load as the morning read classified it (replayed 27 Sep).
YESTERDAY_LOAD = {
    date(2026, 9, 15): "easy",
    date(2026, 9, 16): "moderate",
    date(2026, 9, 17): "moderate",
    date(2026, 9, 18): "moderate",
    date(2026, 9, 19): "easy",
    date(2026, 9, 20): "moderate",
    date(2026, 9, 21): "moderate",
    date(2026, 9, 22): "easy",
    date(2026, 9, 23): "moderate",
    date(2026, 9, 24): "moderate",
    date(2026, 9, 25): "hard",
    date(2026, 9, 26): "moderate",
}


def _baseline(
    metric_key: str, *, median: float, lower_quartile: float, upper_quartile: float
) -> MetricBaseline:
    # Production's own baselines on 27 Sep 2026 (84 samples, 5 Jul - 26 Sep).
    return MetricBaseline(
        user_id=USER_ID,
        metric_key=metric_key,
        metric_label=metric_key,
        source="db_history",
        window_start_date=date(2026, 7, 5),
        window_end_date=date(2026, 9, 26),
        sample_count=84,
        excluded_sample_count=0,
        median_value=median,
        lower_quartile_value=lower_quartile,
        upper_quartile_value=upper_quartile,
    )


BASELINES = {
    "resting_heart_rate_bpm": _baseline(
        "resting_heart_rate_bpm", median=44, lower_quartile=43, upper_quartile=45
    ),
    "readiness_score": _baseline(
        "readiness_score", median=68, lower_quartile=54.75, upper_quartile=77
    ),
    "average_spo2_pct": _baseline(
        "average_spo2_pct", median=96, lower_quartile=95, upper_quartile=97
    ),
    "average_respiration": _baseline(
        "average_respiration", median=11, lower_quartile=11, upper_quartile=12
    ),
}


def _metric(row: tuple[Any, ...], **overrides: Any) -> DailyMetric:
    day, overnight, weekly, floor, ceiling, status, level, score, rhr, *_ = row
    fields: dict[str, Any] = {
        "hrv_last_night_avg_ms": overnight,
        "hrv_weekly_avg_ms": weekly,
        "hrv_baseline_low_ms": floor,
        "hrv_baseline_high_ms": ceiling,
        "hrv_status": status,
        "readiness_level": level,
        "readiness_score": score,
        "resting_heart_rate_bpm": rhr,
    }
    fields.update(overrides)
    return DailyMetric(
        user_id=USER_ID,
        calendar_date=day,
        phase=DAILY_METRIC_PHASE_MORNING,
        raw_payload={},
        **fields,
    )


def _sleep(day: date, raw_score: int) -> Sleep:
    return Sleep(
        user_id=USER_ID,
        calendar_date=day,
        score=raw_score,
        average_spo2_pct=96,
        lowest_spo2_pct=92,
        average_respiration=11,
        factors_json={},
        raw_payload={},
    )


def bike(title: str, workout_type: str, steps: list[dict[str, Any]], day: date) -> PlannedWorkout:
    return PlannedWorkout(
        user_id=USER_ID,
        workout_date=day,
        version=1,
        title=title,
        workout_type=workout_type,
        status="planned",
        is_active=True,
        source="test",
        structured_workout={"format": "bike", "steps": steps},
    )


def z2(day: date) -> PlannedWorkout:
    # 23 Sep's session: 75 minutes of Zone 2.
    return bike(
        "Z2 Endurance",
        "bike_endurance",
        [{"label": "Endurance", "minutes": 75, "target": "65-72% FTP"}],
        day,
    )


def vo2(day: date) -> PlannedWorkout:
    return bike(
        "VO2 Max",
        "bike_vo2",
        [
            {"label": "Warm-up", "minutes": 15, "target": "easy spin"},
            {"label": "VO2 work", "minutes": 12, "target": "110% FTP"},
            {"label": "Cool-down", "minutes": 10, "target": "easy spin"},
        ],
        day,
    )


def _verdict_on(
    day: date,
    *,
    feel: int | None | str = "production",
    planned: list[PlannedWorkout] | None = None,
    **metric_overrides: Any,
) -> dict[str, Any]:
    rows = {row[0]: row for row in PRODUCTION_SERIES}
    row = rows[day]
    raw_sleep, age_sleep, production_feel = row[9], row[10], row[11]
    subjective = production_feel if feel == "production" else feel
    entries = (
        [
            ManualEntry(
                user_id=USER_ID,
                entry_date=day,
                entry_at_utc=datetime.combine(day, datetime.min.time()) + timedelta(hours=7),
                subjective_score=subjective,
            )
        ]
        if subjective is not None
        else []
    )
    history = [_metric(other) for other in PRODUCTION_SERIES if other[0] < day]
    return morning_verdict(
        daily_metric=_metric(row, **metric_overrides),
        sleep=_sleep(day, raw_sleep),
        age_adjusted_sleep_score=age_sleep,
        manual_entries=entries,
        planned_workouts=planned if planned is not None else [z2(day)],
        baselines=BASELINES,
        yesterday_load={"status": YESTERDAY_LOAD.get(day, "moderate")},
        recent_daily_metrics=history,
        recent_sleeps=[],
        enforce_data_sufficiency=True,
    )


# -- the mornings Mark disputed ------------------------------------------------


@pytest.mark.parametrize(
    ("day", "concern"),
    [
        (date(2026, 9, 18), "floor_moved"),
        (date(2026, 9, 19), "floor_moved"),
        (date(2026, 9, 23), "weekly_average_below_floor"),
    ],
)
def test_a_lagging_average_or_a_moved_floor_alone_holds_the_session(
    day: date, concern: str
) -> None:
    verdict = _verdict_on(day)
    graded = verdict["hrvGradedResponse"]

    assert verdict["status"] == "Green"
    assert graded["tier"] == "hold"
    assert graded["concern"] == concern
    assert graded["corroboratingSignals"] == []
    assert HRV_RED_REASON not in verdict["reasons"]
    # The first reason — the one the Sleep page shows — leads with his own reading.
    assert f"{graded['overnightMs']} ms" in verdict["reasons"][0]
    # Full session, targets held: no cut, no substitution.
    assert HRV_HOLD_PLAN_LINE in verdict["planAdjustments"]
    assert not any("Cut the bike" in line for line in verdict["planAdjustments"])


def test_the_eighteenth_names_the_floor_movement_not_just_the_average() -> None:
    verdict = _verdict_on(date(2026, 9, 18))
    assert is_band_artifact(verdict["hrvRecalibration"])
    assert "46 ms" in verdict["reasons"][0]
    assert "48 ms" in verdict["reasons"][0]


def test_24_sep_eases_because_its_raw_sleep_was_only_fair() -> None:
    """The HRV flag alone would have held; a raw sleep score of 72, lifted to 76 by
    age adjustment, is a second thing, and the Batch 170 ceiling keeps it Amber."""
    verdict = _verdict_on(date(2026, 9, 24))
    graded = verdict["hrvGradedResponse"]

    assert verdict["status"] == "Amber"
    assert graded["tier"] == "ease"
    assert graded["heldBackBy"] == "sleep_credit_ceiling"
    assert verdict["sleepCreditCeiling"]["applied"] is True
    assert HRV_RED_REASON not in verdict["reasons"]
    assert HRV_HOLD_PLAN_LINE not in verdict["planAdjustments"]


def test_26_sep_eases_because_his_resting_heart_rate_agreed() -> None:
    verdict = _verdict_on(date(2026, 9, 26))
    graded = verdict["hrvGradedResponse"]

    assert verdict["status"] == "Amber"
    assert graded["tier"] == "ease"
    assert "resting_heart_rate_above_usual" in graded["corroboratingSignals"]
    # Batch 293's calm path: two mornings above his usual range cap the day, no rest.
    assert verdict["acutePhysiology"]["requiresBikeRest"] is False


@pytest.mark.parametrize("day", [date(2026, 9, 21), date(2026, 9, 22)])
def test_nights_that_genuinely_fell_stay_red(day: date) -> None:
    verdict = _verdict_on(day)

    assert verdict["status"] == "Red"
    assert HRV_RED_REASON in verdict["reasons"]
    assert verdict["hrvGradedResponse"]["tier"] == "red"
    assert verdict["hrvGradedResponse"]["concern"] == "overnight_below_floor"
    # The acute rail still caps the day. Whether it also rests the bike is Batch 294's
    # illness-grade line, judged on the full 84-night history this fixture does not
    # carry (see test_batch_294_symptom_floors).
    assert verdict["acutePhysiology"]["overnightHrv"]["triggered"] is True


def test_a_dip_under_a_floor_that_held_stays_red() -> None:
    """25 Sep: 44 ms under a 45 ms floor Garmin had not moved. Resting heart rate
    was above his usual range too, so a graded rule would have cut it as well."""
    verdict = _verdict_on(date(2026, 9, 25))

    assert not is_band_artifact(verdict["hrvRecalibration"])
    assert verdict["status"] == "Red"
    assert verdict["hrvGradedResponse"]["tier"] == "red"
    assert verdict["hrvGradedResponse"]["concern"] == "overnight_below_floor"


def test_replaying_16_to_22_sep_gives_red_on_21_and_22_only() -> None:
    statuses = {
        day: _verdict_on(day)["status"]
        for day in (date(2026, 9, 16) + timedelta(days=offset) for offset in range(7))
    }
    assert [day for day, status in statuses.items() if status == "Red"] == [
        date(2026, 9, 21),
        date(2026, 9, 22),
    ]
    assert statuses[date(2026, 9, 18)] == "Green"
    assert statuses[date(2026, 9, 19)] == "Green"


@pytest.mark.parametrize("day", [date(2026, 9, 15), date(2026, 9, 16), date(2026, 9, 17)])
def test_a_low_night_in_a_balanced_week_is_not_newly_cut(day: date) -> None:
    """Garmin's band is a band for the 7-day average. Reading one night against it
    everywhere, as the row first proposed, would have cut 10 of his 43 Green days
    between 1 Jul and 26 Sep — these three among them. Only the Red rule reads the
    night."""
    verdict = _verdict_on(day)
    assert verdict["status"] == "Green"
    assert verdict["hrvGradedResponse"]["tier"] is None


# -- what still eases -----------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "feel", "signal"),
    [
        ({}, 4, "check_in_low"),
        ({"resting_heart_rate_bpm": 47}, "production", "resting_heart_rate_above_usual"),
        ({"readiness_score": 50}, "production", "readiness_below_usual"),
    ],
)
def test_anything_else_disagreeing_turns_the_hold_into_an_eased_day(
    overrides: dict[str, Any], feel: int | str, signal: str
) -> None:
    verdict = _verdict_on(date(2026, 9, 23), feel=feel, **overrides)
    graded = verdict["hrvGradedResponse"]

    assert verdict["status"] == "Amber"
    assert graded["tier"] == "ease"
    assert signal in graded["corroboratingSignals"]
    assert HRV_HOLD_PLAN_LINE not in verdict["planAdjustments"]


def test_low_readiness_still_eases_on_its_own() -> None:
    verdict = _verdict_on(date(2026, 9, 23), readiness_level="LOW", readiness_score=40)
    assert verdict["status"] == "Amber"
    assert verdict["hrvGradedResponse"]["tier"] != "hold"


def test_garmin_calling_the_week_low_eases_rather_than_holds() -> None:
    """How far off matters: Garmin's Low is a week well under the band, not a point."""
    verdict = _verdict_on(date(2026, 9, 23), hrv_status="LOW")
    graded = verdict["hrvGradedResponse"]

    assert verdict["status"] == "Amber"
    assert graded["tier"] == "ease"
    assert graded["garminStatus"] == "low"


def test_without_last_nights_reading_the_weekly_rule_stands() -> None:
    verdict = _verdict_on(date(2026, 9, 23), hrv_last_night_avg_ms=None)
    assert verdict["status"] == "Red"
    assert verdict["hrvGradedResponse"]["tier"] == "red"


# -- the VO2 guarantee ------------------------------------------------------------


def test_red_still_never_keeps_vo2() -> None:
    day = date(2026, 9, 22)
    session = vo2(day)
    verdict = _verdict_on(day, planned=[session])

    assert verdict["status"] == "Red"
    assert "red_never_vo2" in verdict["safetyRulesApplied"]
    assert blocks_red_vo2(verdict["status"], build_structured_workout_ir(session))


def test_a_hold_day_keeps_its_vo2_session() -> None:
    """Mark, 19 Sep: the app "could instruct me not to do Tuesday's vo2 workout
    because garmin raised hrv band … this is simply incorrect". On a hold day it
    does not."""
    day = date(2026, 9, 23)
    session = vo2(day)
    verdict = _verdict_on(day, planned=[session])

    assert verdict["status"] == "Green"
    assert verdict["hasVo2WorkoutToday"] is True
    assert "red_never_vo2" not in verdict["safetyRulesApplied"]
    assert not blocks_red_vo2(verdict["status"], build_structured_workout_ir(session))
    assert HRV_HOLD_PLAN_LINE in verdict["planAdjustments"]


# -- the brief ----------------------------------------------------------------------


def test_the_brief_is_told_to_lead_with_his_own_recovery() -> None:
    assert HRV_GRADED_RESPONSE_RULE in SYSTEM_PROMPT
    assert "hold" in HRV_GRADED_RESPONSE_RULE
    # The model is given new wording, so no stored brief written without it is
    # served as current; the morning read self-heals, so nothing is regenerated.
    # (Batch 272 moved it on again, to v49; Batch 294 to v50.)
    assert PROMPT_VERSION == "morning-analysis-v50-2026-09-28"
