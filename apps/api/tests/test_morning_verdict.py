"""The morning's floors and context (``services.morning_verdict``), since Batch 308.

The rule ladder that set the colour until Batch 296 is gone. What these tests pin is
what stays: the acute rail (the floors, in the graded verdict's words) and the context
the morning packet carries beside the graded colour.
"""

from __future__ import annotations

import re
import uuid
from datetime import date, timedelta
from typing import Any

import pytest

from src.models.coaching import (
    DAILY_METRIC_PHASE_MORNING,
    DailyMetric,
    MetricBaseline,
    PlannedWorkout,
    Sleep,
)
from src.services.morning_analysis import verdict_context as compatibility_entrypoint
from src.services.morning_verdict import (
    BIKE_REST_PLAN_LINE,
    CONTEXT_FIELDS,
    GRADED_SIGNAL_IMPACT,
    INSUFFICIENT_DATA_MESSAGE,
    MEDICAL_BOUNDARY_STANDING_LINE,
    graded_verdict_packet,
    verdict_context,
)
from src.services.verdict_grading import build_grading_inputs, grade

TODAY = date(2026, 9, 2)


def _metric(
    *,
    resting_hr: int | None = 44,
    last_night_hrv: int | None = 47,
    day: date = TODAY,
) -> DailyMetric:
    return DailyMetric(
        user_id=uuid.uuid4(),
        calendar_date=day,
        phase=DAILY_METRIC_PHASE_MORNING,
        readiness_score=70,
        readiness_level="High",
        hrv_last_night_avg_ms=last_night_hrv,
        hrv_weekly_avg_ms=47,
        hrv_baseline_low_ms=40,
        hrv_baseline_high_ms=55,
        hrv_status="Balanced",
        resting_heart_rate_bpm=resting_hr,
        raw_payload={},
    )


def _sleep(
    *,
    day: date = TODAY,
    average_spo2: float | None = 97,
    lowest_spo2: float | None = 93,
    respiration: float | None = 11,
) -> Sleep:
    return Sleep(
        user_id=uuid.uuid4(),
        calendar_date=day,
        score=82,
        average_spo2_pct=average_spo2,
        lowest_spo2_pct=lowest_spo2,
        average_respiration=respiration,
        factors_json={},
        raw_payload={},
    )


def _baseline(
    metric_key: str,
    *,
    median: float,
    upper_quartile: float,
    sample_count: int = 84,
) -> MetricBaseline:
    return MetricBaseline(
        user_id=uuid.uuid4(),
        metric_key=metric_key,
        metric_label=metric_key,
        source="test",
        window_start_date=date(2026, 6, 10),
        window_end_date=date(2026, 9, 1),
        sample_count=sample_count,
        excluded_sample_count=0,
        median_value=median,
        upper_quartile_value=upper_quartile,
        raw_payload={},
    )


def _baselines() -> dict[str, MetricBaseline]:
    return {
        "resting_heart_rate_bpm": _baseline("resting_heart_rate_bpm", median=44, upper_quartile=45),
        "average_spo2_pct": _baseline("average_spo2_pct", median=96, upper_quartile=97),
        "average_respiration": _baseline("average_respiration", median=11, upper_quartile=12),
    }


def _bike_workout() -> PlannedWorkout:
    return PlannedWorkout(
        user_id=uuid.uuid4(),
        workout_date=TODAY,
        version=1,
        title="Endurance ride",
        workout_type="bike_endurance",
        status="planned",
        is_active=True,
        source="test",
        structured_workout={
            "format": "bike",
            "steps": [{"label": "Endurance", "minutes": 60, "target": "Zone 2"}],
        },
    )


def _complete_verdict(
    *,
    daily_metric: DailyMetric | None = None,
    sleep: Sleep | None = None,
    recent_daily_metrics: list[DailyMetric] | None = None,
    recent_sleeps: list[Sleep] | None = None,
    planned_workouts: list[PlannedWorkout] | None = None,
) -> dict[str, Any]:
    """This morning's context: the acute rail and the packet's context fields."""
    return verdict_context(
        daily_metric=daily_metric or _metric(),
        sleep=sleep or _sleep(),
        age_adjusted_sleep_score=82,
        manual_entries=[],
        planned_workouts=planned_workouts or [],
        baselines=_baselines(),
        recent_daily_metrics=recent_daily_metrics or [],
        recent_sleeps=recent_sleeps or [],
    )


def _graded_packet(
    context: dict[str, Any], planned_workouts: list[PlannedWorkout]
) -> dict[str, Any]:
    """The verdict section the morning packet would carry for ``context``."""
    graded = grade(
        build_grading_inputs(
            subject_date=TODAY,
            acute=context["acutePhysiology"],
            last_night_hrv_ms=None,
            hrv_history={},
            sleep_score_raw=82,
            sleep_score_age_adjusted=82,
            sleep_minutes=None,
            sleep_minutes_history={},
            acwr=None,
            recovery_time_min=None,
            yesterday_load=None,
            feel=None,
            feel_history={},
            readiness_level="High",
            readiness_score=70.0,
            readiness_lower_quartile=None,
            planned_workouts=planned_workouts,
            rest_day=bool(context["isRestDay"]),
            blocks=[],
        )
    )
    return graded_verdict_packet(context, graded, planned_workouts, breathwork_line=None)


def test_named_module_owns_the_compatibility_entrypoint() -> None:
    assert verdict_context.__module__ == "src.services.morning_verdict"
    assert compatibility_entrypoint is verdict_context


def test_the_context_has_no_colour_and_carries_exactly_the_packet_fields() -> None:
    """Batch 308: the ladder's colour and its working are gone; the context is an allow-list."""
    context = verdict_context(
        daily_metric=None,
        sleep=None,
        age_adjusted_sleep_score=78,
        manual_entries=[],
        planned_workouts=[],
    )

    assert set(context) == {*CONTEXT_FIELDS, "acutePhysiology"}
    assert "status" not in context and "reasons" not in context
    assert context["ageAdjustedSleepScore"] == 78
    assert context["dayType"] == "training" and context["isRestDay"] is False
    assert context["hasVo2WorkoutToday"] is False
    assert context["readinessBaselineTrend"]["status"] == "not_evaluated"


def test_garmins_hrv_flag_stays_context_for_the_brief() -> None:
    """Garmin's own 7-day comparison is context, never the reason for the colour."""
    metric = DailyMetric(
        user_id=uuid.uuid4(),
        calendar_date=date(2026, 9, 2),
        phase=DAILY_METRIC_PHASE_MORNING,
        hrv_status="UNBALANCED",
        hrv_weekly_avg_ms=20,
        hrv_baseline_low_ms=30,
    )

    context = verdict_context(
        daily_metric=metric,
        sleep=None,
        age_adjusted_sleep_score=78,
        manual_entries=[],
        planned_workouts=[],
    )

    assert context["hrvStatus"] == "unbalanced"
    assert context["hrvBelowBaseline"] is True


@pytest.mark.parametrize("resting_hr", [51, 60, 70, 85])
def test_rhr_absolute_delta_takes_him_off_the_bike(resting_hr: int) -> None:
    context = _complete_verdict(
        daily_metric=_metric(resting_hr=resting_hr),
        planned_workouts=[_bike_workout()],
    )

    rhr = context["acutePhysiology"]["restingHeartRate"]
    assert rhr["trigger"] == "absolute_delta"
    assert rhr["verdictImpact"] == GRADED_SIGNAL_IMPACT
    assert context["acutePhysiology"]["requiresBikeRest"] is True
    packet = _graded_packet(context, [_bike_workout()])
    assert packet["status"] == "Amber"
    assert packet["planAdjustments"] == [BIKE_REST_PLAN_LINE]
    assert "bike_rest_floor" in packet["safetyRulesApplied"]


def test_rhr_absolute_delta_boundary_is_inclusive_and_copy_is_pinned() -> None:
    at_boundary = _complete_verdict(daily_metric=_metric(resting_hr=51))
    below_boundary = _complete_verdict(daily_metric=_metric(resting_hr=50))

    escalation = at_boundary["acutePhysiology"]["escalations"][0]
    # Batch 293: the GP line is conditional on feeling unwell, and only a jump
    # this size carries it. Wording signed off by Craig on Mark's behalf, 27 Sep.
    assert escalation == {
        "kind": "resting_heart_rate",
        "level": "rest",
        "message": (
            "Your resting heart rate is 51 this morning against a usual 44 — a rise of "
            "7 bpm. A jump that size can come from a short night, alcohol, dehydration or "
            "a hard day, and sometimes from your body fighting something off. Take today "
            "off the bike. If you also feel unwell, rest until it settles, and see your GP "
            "if it doesn't."
        ),
    }
    rhr = at_boundary["acutePhysiology"]["restingHeartRate"]
    assert rhr["requiresBikeRest"] is True
    assert rhr["reason"] == "Resting heart rate 51 bpm is 7 bpm above the personal median of 44."
    assert below_boundary["acutePhysiology"]["restingHeartRate"]["triggered"] is False


def test_rhr_two_consecutive_mornings_above_q3_uses_proportionate_path() -> None:
    current = _metric(resting_hr=46)
    prior = _metric(resting_hr=46, day=TODAY - timedelta(days=1))
    context = _complete_verdict(daily_metric=current, recent_daily_metrics=[prior])

    rhr = context["acutePhysiology"]["restingHeartRate"]
    assert rhr["trigger"] == "consecutive_q3"
    assert rhr["priorBpm"] == 46
    assert rhr["requiresBikeRest"] is False
    assert rhr["reason"] == (
        "Resting heart rate has been above the personal upper quartile of 45 bpm for two "
        "mornings: one thing a little off."
    )
    assert "a little above your usual range, as it was yesterday" in rhr["escalation"]

    one_high_morning = _complete_verdict(
        daily_metric=current,
        recent_daily_metrics=[_metric(resting_hr=45, day=TODAY - timedelta(days=1))],
    )
    assert one_high_morning["acutePhysiology"]["restingHeartRate"]["triggered"] is False


def test_a_small_rise_is_one_thing_a_little_off_without_rest_or_illness_talk() -> None:
    """Batch 293 — 27 Sep 2026: 47 bpm after 46, against a median of 44 and a quartile of 45.

    Mark accepted the cap and called the illness and GP talk "totally over the top
    when there are clear and obvious explanations". Since Batch 298 the notice says it
    is one thing a little off, already counted in today's call (signed off 1 Oct 2026),
    and since Batch 308 the rail writes those words itself.
    """
    context = _complete_verdict(
        daily_metric=_metric(resting_hr=47),
        recent_daily_metrics=[_metric(resting_hr=46, day=TODAY - timedelta(days=1))],
        planned_workouts=[_bike_workout()],
    )

    acute = context["acutePhysiology"]
    assert acute["triggeredSignals"] == ["resting_heart_rate"]
    assert acute["requiresBikeRest"] is False
    assert acute["gradedWording"] is True
    assert acute["escalations"] == [
        {
            "kind": "resting_heart_rate",
            "level": "ease",
            "message": (
                "Your resting heart rate is 47 this morning against a usual 44 — a little "
                "above your usual range, as it was yesterday. Small rises like this usually "
                "come from travel, a short night, a busy week or a hard day before. On its "
                "own it is one thing a little off, and today's call already counts it: not a "
                "day off the bike."
            ),
        }
    ]
    assert not re.search(
        r"\b(infection|illness|ill|unwell|gp|doctor)\b", acute["escalations"][0]["message"], re.I
    )
    packet = _graded_packet(context, [_bike_workout()])
    assert not any("off the bike" in line for line in packet["planAdjustments"])


def test_last_night_hrv_collapse_is_one_thing_a_little_off_and_illness_grade_rests() -> None:
    values = [43] * 10 + [47] + [51] * 10
    history = [
        _metric(last_night_hrv=value, day=TODAY - timedelta(days=len(values) - index))
        for index, value in enumerate(values)
    ]

    context = _complete_verdict(
        daily_metric=_metric(last_night_hrv=41),
        recent_daily_metrics=history,
    )

    hrv = context["acutePhysiology"]["overnightHrv"]
    assert hrv["triggered"] is True
    assert hrv["verdictImpact"] == GRADED_SIGNAL_IMPACT
    assert hrv["baselineMedianMs"] == 47
    assert hrv["baselineStddevMs"] == 3.9
    assert hrv["acuteFloorMs"] == 41.14
    assert hrv["baselineSampleCount"] == 21
    assert hrv["reason"] == "Overnight HRV 41 ms is below the acute personal floor of 41.1 ms."
    # Batch 294: 41 against 47 is 1.5 SD and 13% down, under the illness-grade line
    # (37.24 ms here), so it counts without taking him off the bike.
    assert hrv["illnessLineMs"] == 37.24
    assert hrv["illnessGrade"] is False
    assert context["acutePhysiology"]["requiresBikeRest"] is False
    assert hrv["requiresBikeRest"] is False
    assert context["acutePhysiology"]["escalations"][0]["level"] == "ease"
    assert hrv["escalation"].endswith(
        "On its own it is one thing a little off, and today's call already counts it: not a "
        "day off the bike."
    )
    [floor_rule] = [entry["rule"] for entry in hrv["provenance"]]
    assert "Below it last night counts as one thing a little off in the graded verdict" in (
        floor_rule
    )

    illness_grade = _complete_verdict(
        daily_metric=_metric(last_night_hrv=37),
        recent_daily_metrics=history,
    )
    rail = illness_grade["acutePhysiology"]["overnightHrv"]
    assert rail["illnessGrade"] is True
    assert rail["reason"] == "Overnight HRV 37 ms is an illness-grade drop, at or under 37.2 ms."
    assert illness_grade["acutePhysiology"]["requiresBikeRest"] is True
    assert "against a usual 47 ms from 12 Aug to 1 Sep — a drop" in rail["escalation"]
    assert illness_grade["acutePhysiology"]["escalations"][0]["level"] == "rest"


def test_average_spo2_surveillance_has_gp_route_without_rest_or_diagnosis() -> None:
    context = _complete_verdict(sleep=_sleep(average_spo2=89, lowest_spo2=87, respiration=17))

    oxygen = context["acutePhysiology"]["oxygenRespiration"]
    assert oxygen["trigger"] == "low_average_spo2"
    assert oxygen["verdictImpact"] == "surveillance_only"
    assert context["acutePhysiology"]["requiresBikeRest"] is False
    assert context["acutePhysiology"]["escalations"] == [
        {
            "kind": "oxygen_respiration",
            "level": "watch",
            "message": (
                "Your watch estimated overnight oxygen saturation at an average of 89% "
                "last night against a usual 96% from 10 Jun to 1 Sep, and your "
                "breathing rate was 17 against a usual 11 from 10 Jun to 1 Sep. "
                "Sustained low overnight oxygen has causes worth checking properly — a chest "
                "infection, or disrupted breathing during sleep. This one isn't something "
                "training or rest changes. Mention this to your GP if it happens again."
            ),
        }
    ]
    assert "Take today off" not in oxygen["escalation"]
    assert "you have" not in oxygen["escalation"].lower()
    packet = _graded_packet(context, [])
    assert packet["status"] == "Green"
    assert "oxygen_respiration_surveillance" in packet["safetyRulesApplied"]


def test_low_spo2_nadir_cluster_needs_sustained_respiration_corroboration() -> None:
    prior_low = _sleep(
        day=TODAY - timedelta(days=1),
        average_spo2=96,
        lowest_spo2=87,
        respiration=13,
    )
    current_low = _sleep(average_spo2=96, lowest_spo2=86, respiration=13)
    corroborated = _complete_verdict(sleep=current_low, recent_sleeps=[prior_low])

    signal = corroborated["acutePhysiology"]["oxygenRespiration"]
    assert signal["trigger"] == "nadir_cluster_with_respiration"
    assert signal["nadirNightsInWindow"] == 2
    assert signal["respirationSustained"] is True
    assert "a lowest oxygen reading of 86% last night" in signal["escalation"]
    assert "usual overnight average is 96% from 10 Jun to 1 Sep" in signal["escalation"]
    assert (
        "breathing rate has stayed above its usual range (up to 12 from 10 Jun to 1 Sep) "
        "for two nights."
    ) in signal["escalation"]

    not_corroborated = _complete_verdict(
        sleep=_sleep(average_spo2=96, lowest_spo2=86, respiration=11),
        recent_sleeps=[
            _sleep(
                day=TODAY - timedelta(days=1),
                average_spo2=96,
                lowest_spo2=87,
                respiration=11,
            )
        ],
    )
    assert not_corroborated["acutePhysiology"]["oxygenRespiration"]["triggered"] is False


def test_missing_source_rows_are_recorded_and_the_graded_day_is_never_green() -> None:
    cases = [
        (_metric(), None, ["sleep"]),
        (None, _sleep(), ["daily_metric"]),
        (None, None, ["daily_metric", "sleep"]),
    ]
    for daily_metric, sleep, missing_rows in cases:
        context = verdict_context(
            daily_metric=daily_metric,
            sleep=sleep,
            age_adjusted_sleep_score=82,
            manual_entries=[],
            planned_workouts=[],
            baselines=_baselines(),
        )

        assert context["acutePhysiology"]["dataSufficiency"] == {
            "status": "insufficient_data",
            "message": INSUFFICIENT_DATA_MESSAGE,
            "missingRows": missing_rows,
        }
        assert context["acutePhysiology"]["escalations"] == []
        packet = _graded_packet(context, [])
        assert packet["status"] == "Amber"
        assert INSUFFICIENT_DATA_MESSAGE in packet["reasons"]
        assert "missing_data_amber_floor" in packet["safetyRulesApplied"]


def test_medical_boundary_standing_line_is_exact_deterministic_data() -> None:
    context = _complete_verdict()

    assert context["acutePhysiology"]["standingLine"] == MEDICAL_BOUNDARY_STANDING_LINE
    assert MEDICAL_BOUNDARY_STANDING_LINE == (
        "This read comes from your watch and your room sensors. It can't see how you "
        "actually feel — if those two disagree, trust yourself."
    )
