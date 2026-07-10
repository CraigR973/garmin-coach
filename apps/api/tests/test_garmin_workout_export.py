"""Batch 78: IR → Garmin cycling-workout JSON export (pure, hermetic)."""

from __future__ import annotations

from typing import Any

import pytest

from src.services.garmin_workout_export import build_garmin_workout


def _ir(steps: list[dict[str, Any]], *, ftp: int = 280, name: str = "Test ride") -> dict[str, Any]:
    return {
        "name": name,
        "ftpWatts": ftp,
        "totalDurationSec": sum(int(s["durationSec"]) for s in steps),
        "steps": steps,
    }


def _steady(pct: int, *, phase: str = "interval", label: str = "Block", seconds: int = 600) -> dict:
    return {
        "label": label,
        "phase": phase,
        "kind": "steady",
        "durationSec": seconds,
        "powerStartPct": pct,
        "powerEndPct": pct,
    }


def test_maps_sport_step_types_and_top_level() -> None:
    out = build_garmin_workout(
        _ir(
            [
                {
                    "label": "Warm-up ramp",
                    "phase": "warmup",
                    "kind": "ramp",
                    "durationSec": 600,
                    "powerStartPct": 45,
                    "powerEndPct": 75,
                },
                _steady(90, label="Main block", seconds=1200),
                {
                    "label": "Cool-down ramp",
                    "phase": "cooldown",
                    "kind": "ramp",
                    "durationSec": 300,
                    "powerStartPct": 75,
                    "powerEndPct": 45,
                },
            ]
        )
    )

    assert out["sportType"]["sportTypeKey"] == "cycling"
    assert out["sportType"]["sportTypeId"] == 2
    assert out["estimatedDurationInSecs"] == 2100
    steps = out["workoutSegments"][0]["workoutSteps"]
    assert [s["stepType"]["stepTypeKey"] for s in steps] == ["warmup", "interval", "cooldown"]
    assert [s["stepOrder"] for s in steps] == [1, 2, 3]
    for step in steps:
        assert step["type"] == "ExecutableStepDTO"
        assert step["endCondition"]["conditionTypeKey"] == "time"
        assert step["targetType"]["workoutTargetTypeKey"] == "power.zone"


def test_ramp_becomes_low_high_range() -> None:
    step = build_garmin_workout(
        _ir(
            [
                {
                    "label": "Warm-up ramp",
                    "phase": "warmup",
                    "kind": "ramp",
                    "durationSec": 600,
                    "powerStartPct": 45,
                    "powerEndPct": 75,
                }
            ]
        )
    )["workoutSegments"][0]["workoutSteps"][0]
    # 45% and 75% of 280 FTP = 126 and 210 W.
    assert step["targetValueOne"] == 126
    assert step["targetValueTwo"] == 210
    assert step["endConditionValue"] == 600.0


def test_steady_becomes_tight_band_around_target() -> None:
    step = build_garmin_workout(_ir([_steady(100)]))["workoutSegments"][0]["workoutSteps"][0]
    # 100% of 280 = 280; band = max(5, round(280*0.025)=7) = 7.
    assert step["targetValueOne"] == 273
    assert step["targetValueTwo"] == 287


def test_recovery_label_maps_to_recovery_step_type() -> None:
    step = build_garmin_workout(
        _ir([_steady(55, label="Main intervals recovery 1/5", seconds=30)])
    )["workoutSegments"][0]["workoutSteps"][0]
    assert step["stepType"]["stepTypeKey"] == "recovery"


def test_ftp_override_wins_over_ir_value() -> None:
    step = build_garmin_workout(_ir([_steady(50)], ftp=200), ftp_watts=300)["workoutSegments"][0][
        "workoutSteps"
    ][0]
    # Override 300 (not IR's 200): 50% of 300 = 150 W; band = max(5, round(7.5)=8) = 8.
    assert step["targetValueOne"] == 142
    assert step["targetValueTwo"] == 158


def test_zero_ftp_raises() -> None:
    with pytest.raises(ValueError, match="FTP"):
        build_garmin_workout(_ir([_steady(50)], ftp=0))


def test_no_steps_raises() -> None:
    with pytest.raises(ValueError, match="no steps"):
        build_garmin_workout({"name": "x", "ftpWatts": 280, "steps": []})
