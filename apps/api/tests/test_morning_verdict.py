from __future__ import annotations

import uuid
from datetime import date

from src.models.coaching import DAILY_METRIC_PHASE_MORNING, DailyMetric
from src.services.morning_analysis import _morning_verdict as compatibility_entrypoint
from src.services.morning_verdict import (
    ACWR_AMBER_CAP_THRESHOLD,
    morning_verdict,
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
