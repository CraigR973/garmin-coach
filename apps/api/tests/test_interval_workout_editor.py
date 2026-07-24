from __future__ import annotations

from copy import deepcopy

from src.services.interval_workout_editor import (
    apply_interval_block,
    interval_editor_snapshot,
)
from src.services.workout_delivery import (
    build_zwo_xml,
    expand_structured_steps,
    validate_deliverable_bike_workout,
)


def _mark_vo2_source() -> dict:
    return {
        "format": "bike",
        "summary": "Mark's worked VO2 example",
        "steps": [
            {"label": "Warm-up ramp 55→80%", "minutes": 10, "ramp": [55, 80]},
            {
                "label": "Primer 2×30s @100% / 55%",
                "target": "100%",
                "pattern": "2 x 30s / 30s @55%",
                "cadenceRpm": 95,
            },
            {"label": "Warm-up @72%", "minutes": 3, "target": "72%"},
            {"label": "Warm-up @55%", "minutes": 2, "target": "55%"},
            {
                "label": "VO₂ 5×2min @120%",
                "target": "120%",
                "pattern": "5 x 2min / 2min @60%",
                "cadenceRpm": 95,
            },
            {"label": "Cool-down ramp", "minutes": 10, "ramp": [70, 45]},
        ],
    }


def test_new_block_expands_independent_work_and_rest_cadence_into_zwo() -> None:
    source = _mark_vo2_source()
    source["steps"][4] = {
        "label": "VO₂ intervals",
        "block": {
            "repeat": 2,
            "work": {"durationSec": 120, "powerPct": 120, "cadenceRpm": 95},
            "rest": {"durationSec": 90, "powerPct": 60, "cadenceRpm": 70},
        },
    }

    steps = expand_structured_steps(source, "VO₂")
    work = next(step for step in steps if step["label"] == "VO₂ intervals work 1/2")
    rest = next(step for step in steps if step["label"] == "VO₂ intervals recovery 1/2")
    assert work["cadenceRpm"] == 95
    assert rest["cadenceRpm"] == 70

    zwo = build_zwo_xml({"name": "Cadence test", "steps": steps})
    assert 'Power="1.2" Cadence="95"' in zwo
    assert 'Power="0.6" Cadence="70"' in zwo


def test_zone_two_one_repeat_zero_rest_is_one_work_step_and_still_deliverable() -> None:
    source = _mark_vo2_source()
    snapshot = interval_editor_snapshot(source, "VO₂")
    updated = apply_interval_block(source, "VO₂", snapshot.zone_two)

    steps = validate_deliverable_bike_workout(updated, "Z2")
    main_steps = [step for step in steps if step["label"].startswith("VO₂ 5×2min")]
    assert len(main_steps) == 1
    assert main_steps[0]["durationSec"] == 2700
    assert main_steps[0]["powerEndPct"] == 65
    assert "recovery" not in main_steps[0]["label"]


def test_mapper_round_trips_primary_block_and_leaves_every_pass_through_step_identical() -> None:
    source = _mark_vo2_source()
    before = deepcopy(source["steps"])
    snapshot = interval_editor_snapshot(source, "VO₂")

    assert snapshot.primary_step_index == 4
    assert snapshot.current.repeat == 5
    assert snapshot.current.work.duration_sec == 120
    assert snapshot.current.work.power_pct == 120
    assert snapshot.current.work.cadence_rpm == 95
    assert snapshot.current.rest.duration_sec == 120
    assert snapshot.current.rest.power_pct == 60
    assert snapshot.current.rest.cadence_rpm is None

    updated = apply_interval_block(source, "VO₂", snapshot.scaled)
    for index, step in enumerate(updated["steps"]):
        if index != snapshot.primary_step_index:
            assert step == before[index]

    expanded = expand_structured_steps(updated, "VO₂")
    edited_work = next(
        step
        for step in expanded
        if step["label"].startswith("VO₂ 5×2min") and " work " in step["label"]
    )
    assert edited_work["durationSec"] == 90
    assert edited_work["powerEndPct"] == 108


def test_sweet_spot_and_zone_two_presets_are_deterministic() -> None:
    snapshot = interval_editor_snapshot(_mark_vo2_source(), "VO₂")

    assert snapshot.sweet_spot.repeat == 3
    assert snapshot.sweet_spot.work.duration_sec == 600
    assert snapshot.sweet_spot.work.power_pct == 90
    assert snapshot.sweet_spot.rest.duration_sec == 300
    assert snapshot.zone_two.repeat == 1
    assert snapshot.zone_two.work.duration_sec == 2700
    assert snapshot.zone_two.work.power_pct == 65
    assert snapshot.zone_two.rest.duration_sec == 0


def test_legacy_pattern_expansion_is_unchanged() -> None:
    source = _mark_vo2_source()
    steps = expand_structured_steps(source, "VO₂")

    main = [step for step in steps if step["label"].startswith("VO₂ 5×2min")]
    assert len(main) == 10
    assert main[0]["durationSec"] == 120
    assert main[0]["powerEndPct"] == 120
    assert main[0]["cadenceRpm"] == 95
    assert main[1]["durationSec"] == 120
    assert main[1]["powerEndPct"] == 60
    assert "cadenceRpm" not in main[1]
