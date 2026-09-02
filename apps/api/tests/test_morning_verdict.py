from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from src.models.coaching import (
    DAILY_METRIC_PHASE_MORNING,
    DailyMetric,
    MetricBaseline,
    PlannedWorkout,
    Sleep,
)
from src.services.morning_analysis import _morning_verdict as compatibility_entrypoint
from src.services.morning_verdict import (
    ACWR_AMBER_CAP_THRESHOLD,
    INSUFFICIENT_DATA_MESSAGE,
    MEDICAL_BOUNDARY_STANDING_LINE,
    morning_verdict,
)

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
) -> dict:
    return morning_verdict(
        daily_metric=daily_metric or _metric(),
        sleep=sleep or _sleep(),
        age_adjusted_sleep_score=82,
        manual_entries=[],
        planned_workouts=planned_workouts or [],
        baselines=_baselines(),
        recent_daily_metrics=recent_daily_metrics or [],
        recent_sleeps=recent_sleeps or [],
        enforce_data_sufficiency=True,
    )


def test_named_module_owns_the_compatibility_entrypoint() -> None:
    assert morning_verdict.__module__ == "src.services.morning_verdict"
    assert compatibility_entrypoint is morning_verdict


def test_minimal_green_packet_is_unchanged_after_extraction() -> None:
    verdict = morning_verdict(
        daily_metric=None,
        sleep=None,
        age_adjusted_sleep_score=78,
        manual_entries=[],
        planned_workouts=[],
    )

    assert verdict["status"] == "Green"
    assert verdict["reasons"] == [
        "Sleep clears the green rule; missing HRV/check-in data is neutral "
        "and did not provide positive evidence."
    ]
    assert verdict["planAdjustments"] == [
        "No active planned workout found for today; keep advice conservative."
    ]
    assert verdict["safetyRulesApplied"] == []


def test_low_unbalanced_hrv_still_sets_red() -> None:
    metric = DailyMetric(
        user_id=uuid.uuid4(),
        calendar_date=date(2026, 9, 2),
        phase=DAILY_METRIC_PHASE_MORNING,
        hrv_status="UNBALANCED",
        hrv_weekly_avg_ms=20,
        hrv_baseline_low_ms=30,
    )

    verdict = morning_verdict(
        daily_metric=metric,
        sleep=None,
        age_adjusted_sleep_score=78,
        manual_entries=[],
        planned_workouts=[],
    )

    assert verdict["status"] == "Red"
    assert "HRV is below baseline and marked low/unbalanced." in verdict["reasons"]
    assert verdict["hrvBelowBaseline"] is True


def test_training_load_string_coercion_is_preserved_by_the_move() -> None:
    verdict = morning_verdict(
        daily_metric=None,
        sleep=None,
        age_adjusted_sleep_score=78,
        manual_entries=[],
        planned_workouts=[],
        training_load={"acuteChronicLoadRatio": str(ACWR_AMBER_CAP_THRESHOLD)},
    )

    assert verdict["status"] == "Amber"
    assert verdict["trainingLoadCap"]["applied"] is True
    assert verdict["trainingLoadCap"]["acuteChronicLoadRatio"] == ACWR_AMBER_CAP_THRESHOLD
    assert verdict["safetyRulesApplied"] == ["training_load_amber_cap"]


@pytest.mark.parametrize("resting_hr", [51, 60, 70, 85])
def test_rhr_absolute_delta_caps_green_independently_of_readiness(resting_hr: int) -> None:
    verdict = _complete_verdict(
        daily_metric=_metric(resting_hr=resting_hr),
        planned_workouts=[_bike_workout()],
    )

    assert verdict["status"] == "Amber"
    assert verdict["acutePhysiology"]["restingHeartRate"]["trigger"] == "absolute_delta"
    assert verdict["acutePhysiology"]["requiresBikeRest"] is True
    assert verdict["planAdjustments"] == [
        "Take today off the bike; do not substitute an eased ride for the acute signal."
    ]
    assert "acute_resting_heart_rate_amber_cap" in verdict["safetyRulesApplied"]


def test_rhr_absolute_delta_boundary_is_inclusive_and_copy_is_pinned() -> None:
    at_boundary = _complete_verdict(daily_metric=_metric(resting_hr=51))
    below_boundary = _complete_verdict(daily_metric=_metric(resting_hr=50))

    escalation = at_boundary["acutePhysiology"]["escalations"][0]
    assert escalation == {
        "kind": "resting_heart_rate",
        "message": (
            "Your resting heart rate is 51 this morning against a usual 44 across "
            "2026-06-10 to 2026-09-01 — a rise of 7 bpm. In practice that usually means "
            "one of: an infection starting, dehydration, alcohol, or simply being run "
            "down. Training hard through it tends to make it worse. Take today off the "
            "bike, and if you feel unwell alongside it, see your GP rather than just resting."
        ),
    }
    assert below_boundary["status"] == "Green"
    assert below_boundary["acutePhysiology"]["restingHeartRate"]["triggered"] is False


def test_rhr_two_consecutive_mornings_above_q3_uses_proportionate_path() -> None:
    current = _metric(resting_hr=46)
    prior = _metric(resting_hr=46, day=TODAY - timedelta(days=1))
    verdict = _complete_verdict(daily_metric=current, recent_daily_metrics=[prior])

    assert verdict["status"] == "Amber"
    rhr = verdict["acutePhysiology"]["restingHeartRate"]
    assert rhr["trigger"] == "consecutive_q3"
    assert rhr["priorBpm"] == 46
    assert "above your usual upper quartile of 45 for two mornings" in rhr["escalation"]

    one_high_morning = _complete_verdict(
        daily_metric=current,
        recent_daily_metrics=[_metric(resting_hr=45, day=TODAY - timedelta(days=1))],
    )
    assert one_high_morning["status"] == "Green"
    assert one_high_morning["acutePhysiology"]["restingHeartRate"]["triggered"] is False


def test_last_night_hrv_collapse_is_an_independent_amber_cap() -> None:
    values = [43] * 10 + [47] + [51] * 10
    history = [
        _metric(last_night_hrv=value, day=TODAY - timedelta(days=len(values) - index))
        for index, value in enumerate(values)
    ]

    verdict = _complete_verdict(
        daily_metric=_metric(last_night_hrv=41),
        recent_daily_metrics=history,
    )

    hrv = verdict["acutePhysiology"]["overnightHrv"]
    assert verdict["status"] == "Amber"
    assert hrv["triggered"] is True
    assert hrv["baselineMedianMs"] == 47
    assert hrv["baselineStddevMs"] == 3.9
    assert hrv["acuteFloorMs"] == 41.14
    assert hrv["baselineSampleCount"] == 21
    assert "2026-08-12 to 2026-09-01" in hrv["escalation"]
    assert verdict["acutePhysiology"]["requiresBikeRest"] is True
    assert "acute_overnight_hrv_amber_cap" in verdict["safetyRulesApplied"]


def test_average_spo2_surveillance_has_gp_route_without_rest_or_diagnosis() -> None:
    verdict = _complete_verdict(sleep=_sleep(average_spo2=89, lowest_spo2=87, respiration=17))

    oxygen = verdict["acutePhysiology"]["oxygenRespiration"]
    assert verdict["status"] == "Green"
    assert oxygen["trigger"] == "low_average_spo2"
    assert oxygen["verdictImpact"] == "surveillance_only"
    assert verdict["acutePhysiology"]["requiresBikeRest"] is False
    assert verdict["acutePhysiology"]["escalations"] == [
        {
            "kind": "oxygen_respiration",
            "message": (
                "Your watch estimated overnight oxygen saturation at an average of 89% "
                "last night against a usual 96% from 2026-06-10 to 2026-09-01, and your "
                "breathing rate was 17 against a usual 11 from 2026-06-10 to 2026-09-01. "
                "Sustained low overnight oxygen has causes worth checking properly — a chest "
                "infection, or disrupted breathing during sleep. This one isn't something "
                "training or rest changes. Mention this to your GP if it happens again."
            ),
        }
    ]
    assert "Take today off" not in oxygen["escalation"]
    assert "you have" not in oxygen["escalation"].lower()
    assert "oxygen_respiration_surveillance" in verdict["safetyRulesApplied"]


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
    assert "oxygen nadir of 86% last night" in signal["escalation"]
    assert "usual overnight average is 96% from 2026-06-10 to 2026-09-01" in signal["escalation"]
    assert "upper quartile of 12 from 2026-06-10 to 2026-09-01" in signal["escalation"]

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


def test_missing_source_rows_floor_green_to_amber_without_escalation() -> None:
    cases = [
        (_metric(), None, ["sleep"]),
        (None, _sleep(), ["daily_metric"]),
        (None, None, ["daily_metric", "sleep"]),
    ]
    for daily_metric, sleep, missing_rows in cases:
        verdict = morning_verdict(
            daily_metric=daily_metric,
            sleep=sleep,
            age_adjusted_sleep_score=82,
            manual_entries=[],
            planned_workouts=[],
            baselines=_baselines(),
            enforce_data_sufficiency=True,
        )

        assert verdict["status"] == "Amber"
        assert INSUFFICIENT_DATA_MESSAGE in verdict["reasons"]
        assert verdict["acutePhysiology"]["dataSufficiency"] == {
            "status": "insufficient_data",
            "message": INSUFFICIENT_DATA_MESSAGE,
            "missingRows": missing_rows,
        }
        assert verdict["acutePhysiology"]["escalations"] == []
        assert "missing_data_amber_floor" in verdict["safetyRulesApplied"]


def test_medical_boundary_standing_line_is_exact_deterministic_data() -> None:
    verdict = _complete_verdict()

    assert verdict["acutePhysiology"]["standingLine"] == MEDICAL_BOUNDARY_STANDING_LINE
    assert MEDICAL_BOUNDARY_STANDING_LINE == (
        "This read comes from your watch and your room sensors. It can't see how you "
        "actually feel — if those two disagree, trust yourself."
    )
