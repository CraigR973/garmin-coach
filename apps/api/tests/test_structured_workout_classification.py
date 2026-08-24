"""Batch 223: a ride is classified by its sustained working demand."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.services.plan_import import build_plan_rows
from src.services.structured_workout_builder import (
    FreeformBikeWorkoutSpec,
    WorkoutSegment,
    build_freeform_bike_workout,
    classify_bike_workout_steps,
)
from src.services.verdict_scaling import blocks_red_vo2
from src.services.weekly_mix import MIX_Z2, mix_bucket
from src.services.workout_delivery import expand_structured_steps

PLAN_PATH = Path(__file__).resolve().parents[1] / "data" / "plans" / "plan_no2.json"


def _ramp(duration_min: int, start: int, end: int) -> WorkoutSegment:
    return WorkoutSegment(
        kind="ramp",
        duration_min=duration_min,
        start_ftp_pct=start,
        end_ftp_pct=end,
    )


def _steady(duration_min: int, power_pct: int) -> WorkoutSegment:
    return WorkoutSegment(kind="steady", duration_min=duration_min, ftp_pct=power_pct)


def _interval(
    repeats: int,
    work_min: int,
    work_power_pct: int,
    recover_min: int,
    recover_power_pct: int,
) -> WorkoutSegment:
    return WorkoutSegment(
        kind="interval",
        repeats=repeats,
        work_min=work_min,
        work_ftp_pct=work_power_pct,
        recover_min=recover_min,
        recover_ftp_pct=recover_power_pct,
    )


def _spec(*segments: WorkoutSegment) -> FreeformBikeWorkoutSpec:
    return FreeformBikeWorkoutSpec(delivery="indoor", segments=tuple(segments))


def _step(*, duration_sec: int, power_pct: int) -> dict[str, object]:
    return {
        "label": "Work",
        "phase": "interval",
        "durationSec": duration_sec,
        "powerStartPct": power_pct,
        "powerEndPct": power_pct,
    }


def test_hot_warmup_does_not_reclassify_zone_two_as_tempo() -> None:
    built, warnings = build_freeform_bike_workout(
        _spec(
            _ramp(10, 45, 80),
            _steady(45, 67),
            _ramp(5, 70, 45),
        )
    )

    assert warnings == []
    assert built.workout_type == "bike_endurance"
    assert built.intensity_target == "Endurance up to 67% FTP"


def test_real_two_minute_vo2_work_stays_vo2() -> None:
    built, warnings = build_freeform_bike_workout(
        _spec(
            _ramp(10, 45, 75),
            _interval(5, 2, 120, 2, 60),
            _ramp(5, 70, 45),
        ),
        soft_gates=True,
    )

    assert {warning.code for warning in warnings} == set()
    assert built.workout_type == "bike_vo2"
    assert built.intensity_target == "VO2 efforts up to 120% FTP"


def test_all_nine_committed_neuromuscular_saturdays_stay_zone_two() -> None:
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    rows = [row for row in build_plan_rows(plan).workouts if row.title == "Z2 + Neuromuscular"]

    assert len(rows) == 9
    for row in rows:
        steps = expand_structured_steps(row.structured_workout, row.intensity_target)
        classification = classify_bike_workout_steps(steps)
        assert classification.workout_type == "bike_endurance"
        assert classification.intensity_target == ("Endurance with short efforts up to 185% FTP")
        assert mix_bucket(classification.workout_type) == MIX_Z2
        # Type drives accounting only. The Red safety gate still sees every
        # 185% step in the IR and remains deliberately stricter.
        assert blocks_red_vo2("Red", {"steps": steps}) is True


@pytest.mark.parametrize(
    ("duration_sec", "expected_type", "expected_target"),
    [
        (20, "bike_endurance", "Endurance with short efforts up to 120% FTP"),
        (21, "bike_vo2", "VO2 efforts up to 120% FTP"),
    ],
)
def test_short_effort_duration_boundary(
    duration_sec: int,
    expected_type: str,
    expected_target: str,
) -> None:
    classification = classify_bike_workout_steps(
        [
            _step(duration_sec=30 * 60, power_pct=65),
            _step(duration_sec=duration_sec, power_pct=120),
        ]
    )

    assert classification.workout_type == expected_type
    assert classification.intensity_target == expected_target
