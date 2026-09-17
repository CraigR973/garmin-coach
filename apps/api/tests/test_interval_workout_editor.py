from __future__ import annotations

from copy import deepcopy

from src.services.interval_workout_editor import (
    EditableIntervalBlock,
    IntervalLeg,
    apply_interval_block,
    interval_editor_snapshot,
    interval_workout_title,
    normalise_interval_workout_copy,
    scale_block,
)
from src.services.structured_workout_builder import classify_bike_workout_steps
from src.services.verdict_scaling import (
    RECOVERY_CAP_PCT,
    adjust_ir_for_verdict,
    ease_amber_power_pct,
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


def _mark_two_block_source() -> dict:
    """The two-equal-main-block shape from 2026-09-08 and 2026-09-29."""
    return {
        "format": "bike",
        "summary": "2 × 10-rep blocks of 40s/20s @125%",
        "steps": [
            {"label": "Warm-up", "minutes": 10, "ramp": [55, 80]},
            {
                "label": "Primer 2×30s @100% / 55%",
                "target": "100%",
                "pattern": "2 x 30s / 30s @55%",
            },
            {
                "label": "40s/20s @125% block 1",
                "target": "125%",
                "pattern": "10 x 40s / 20s @55%",
                "cadenceRpm": 95,
            },
            {"label": "Recover between blocks", "minutes": 4, "target": "60%"},
            {
                "label": "40s/20s @125% block 2",
                "target": "125%",
                "pattern": "10 x 40s / 20s @55%",
                "cadenceRpm": 95,
            },
            {"label": "Cool-down", "minutes": 10, "ramp": [70, 45]},
        ],
    }


def _mark_edited_35_25_block() -> EditableIntervalBlock:
    return EditableIntervalBlock(
        repeat=10,
        work=IntervalLeg(duration_sec=35, power_pct=125, cadence_rpm=95),
        rest=IntervalLeg(duration_sec=25, power_pct=55, cadence_rpm=None),
    )


def test_two_equal_main_blocks_are_edited_together_and_copy_follows_the_steps() -> None:
    source = _mark_two_block_source()

    snapshot = interval_editor_snapshot(source, "VO₂")
    updated = apply_interval_block(source, "VO₂", _mark_edited_35_25_block())

    assert snapshot.primary_step_index == 2  # stable first-on-tie, never the last block
    assert [step.index for step in snapshot.fixed_steps] == [0, 1, 3, 5]
    assert [updated["steps"][index]["block"] for index in (2, 4)] == [
        {
            "repeat": 10,
            "work": {"durationSec": 35, "powerPct": 125, "cadenceRpm": 95},
            "rest": {"durationSec": 25, "powerPct": 55},
        },
        {
            "repeat": 10,
            "work": {"durationSec": 35, "powerPct": 125, "cadenceRpm": 95},
            "rest": {"durationSec": 25, "powerPct": 55},
        },
    ]
    assert updated["steps"][2]["label"] == "10 × 35s/25s @ 125%/55% block 1"
    assert updated["steps"][4]["label"] == "10 × 35s/25s @ 125%/55% block 2"
    assert "40s/20s" not in updated["summary"]
    assert updated["summary"].count("10 × 35s/25s @ 125%/55%") == 2


def test_a_prior_native_block_does_not_hide_the_unedited_first_sibling() -> None:
    source = _mark_two_block_source()
    source["steps"][4] = {
        "label": "40s/20s @125% block 2",
        "block": {
            "repeat": 10,
            "work": {"durationSec": 35, "powerPct": 125, "cadenceRpm": 95},
            "rest": {"durationSec": 25, "powerPct": 55},
        },
    }
    second_before = deepcopy(source["steps"][4]["block"])

    snapshot = interval_editor_snapshot(source, "VO₂")
    updated = apply_interval_block(source, "VO₂", _mark_edited_35_25_block())

    assert snapshot.primary_step_index == 2
    assert snapshot.current.work.duration_sec == 40
    assert updated["steps"][4]["block"] == second_before
    assert updated["steps"][4]["label"] == "10 × 35s/25s @ 125%/55% block 2"


def test_historical_mixed_session_copy_is_repaired_without_changing_its_steps() -> None:
    source = _mark_two_block_source()
    source["steps"][4] = {
        "label": "40s/20s @125% block 2",
        "block": {
            "repeat": 10,
            "work": {"durationSec": 35, "powerPct": 125, "cadenceRpm": 95},
            "rest": {"durationSec": 25, "powerPct": 55},
        },
    }
    dose_before = [
        deepcopy(source["steps"][2]["pattern"]),
        deepcopy(source["steps"][4]["block"]),
    ]

    repaired = normalise_interval_workout_copy(source, "125% FTP intervals")
    title = interval_workout_title(
        "VO₂ (40/20s @ 125%)",
        repaired,
        "125% FTP intervals",
    )

    assert [repaired["steps"][2]["pattern"], repaired["steps"][4]["block"]] == dose_before
    assert repaired["steps"][2]["label"] == "10 × 40s/20s @ 125%/55% block 1"
    assert repaired["steps"][4]["label"] == "10 × 35s/25s @ 125%/55% block 2"
    assert title == "VO₂ (10 × 40s/20s @ 125%/55% + 10 × 35s/25s @ 125%/55%)"
    assert "10 × 40s/20s @ 125%/55%" in repaired["summary"]
    assert "10 × 35s/25s @ 125%/55%" in repaired["summary"]


def test_neuromuscular_set_wins_over_the_longer_zone_two_block() -> None:
    source = {
        "format": "bike",
        "steps": [
            {"label": "Warm-up", "minutes": 5, "ramp": [50, 75]},
            {
                "label": "Z2 @65% + cadence surges",
                "target": "65%",
                "pattern": "5 x 1min / 5min @65%",
                "cadenceRpm": 102,
            },
            {
                "label": "Neuromuscular sprints @185%",
                "target": "185%",
                "pattern": "6 x 12s / 168s @55%",
            },
            {"label": "Cool-down", "minutes": 5, "target": "50%"},
        ],
    }

    snapshot = interval_editor_snapshot(source, "Zone 2")

    assert snapshot.primary_step_index == 2
    assert snapshot.current.repeat == 6
    assert snapshot.current.work.duration_sec == 12
    assert snapshot.current.work.power_pct == 185
    z2 = next(step for step in snapshot.fixed_steps if step.index == 1)
    assert z2.role == "main"
    updated = apply_interval_block(source, "Zone 2", snapshot.current)
    classification = classify_bike_workout_steps(expand_structured_steps(updated, "Zone 2"))
    assert classification.workout_type == "bike_endurance"
    assert classification.intensity_target == "Endurance with short efforts up to 185% FTP"


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
    main_steps = [step for step in steps if step["label"].startswith("45 min @ 65%")]
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
        if step["label"].startswith("4 × 2 min/2 min @ 94%/60%") and " work " in step["label"]
    )
    assert edited_work["durationSec"] == 120
    assert (
        len([step for step in expanded if step["label"].startswith("4 × 2 min/2 min @ 94%/60%")])
        == 8
    )  # four intact work/recovery pairs, not five shortened ones
    # Batches 173/201: the "Scale down" preset shares the delivery transform's
    # Zone-2-aware ease, so a 120% VO2 leg drops a zone and is capped at the top
    # of Sweet Spot (HIT/threshold removed) instead of the old near-VO2 108%.
    assert edited_work["powerEndPct"] == 94


def test_scale_block_holds_zone_two_and_matches_the_shared_ease() -> None:
    """Batch 173.2: the "Scale down" preset uses the same Zone-2-aware ease as the
    delivery transform — a 67% Z2 ride stays 67% (Mark's 2026-07-29 hand-reset), a
    hard leg drops via ease_amber_power_pct — so the editor and the delivered ride
    quote one number."""
    z2 = EditableIntervalBlock(
        repeat=1,
        work=IntervalLeg(duration_sec=3600, power_pct=67, cadence_rpm=85),
        rest=IntervalLeg(duration_sec=0, power_pct=55, cadence_rpm=None),
    )
    scaled_z2 = scale_block(z2)
    assert scaled_z2.work.power_pct == 67  # held, not 60 (the old ×0.9)
    assert scaled_z2.work.duration_sec == 2700  # 25% duration cut
    assert scaled_z2.work.power_pct == ease_amber_power_pct(z2.work.power_pct)

    hard = EditableIntervalBlock(
        repeat=4,
        work=IntervalLeg(duration_sec=240, power_pct=105, cadence_rpm=90),
        rest=IntervalLeg(duration_sec=120, power_pct=55, cadence_rpm=None),
    )
    scaled_hard = scale_block(hard)
    assert scaled_hard.repeat == 3
    assert scaled_hard.work.duration_sec == hard.work.duration_sec
    assert scaled_hard.rest.duration_sec == hard.rest.duration_sec
    assert scaled_hard.work.power_pct == ease_amber_power_pct(105)  # drops a zone, capped
    assert scaled_hard.work.power_pct < 105


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


def _mark_0808_source() -> dict:
    """Mark's real 2026-08-08 session as production stored it (planned_workouts v2's
    source shape, whose primary block came from the v1 plan row's 35 min @60-65%)."""
    return {
        "format": "bike",
        "summary": "5 min ramp → 35 min @60–65% (midpoint 62%) → 5 min ramp",
        "steps": [
            {"ramp": [50, 65], "label": "Warm-up ramp 50→65%", "minutes": 5},
            {
                "label": "Easy Z2 60–65%",
                "block": {
                    "repeat": 1,
                    "work": {"durationSec": 2100, "powerPct": 62},
                    "rest": {"durationSec": 0, "powerPct": 55},
                },
            },
            {"ramp": [60, 45], "label": "Cool-down ramp", "minutes": 5},
        ],
    }


def _snapshot_total_sec(block: EditableIntervalBlock, fixed_sec: int) -> int:
    return fixed_sec + block.repeat * (block.work.duration_sec + block.rest.duration_sec)


def test_editor_no_longer_pre_fills_the_amber_cut_on_a_red_morning() -> None:
    """Batch 215.3, pinned on the real case. On 2026-08-08 the brief said "cut to 22
    minutes at 60% FTP" while the editor opened pre-filled at 37 minutes — because
    ``changeTo`` was :func:`scale_block`, the *Amber* preset, on every morning. Mark
    approved what the app offered him. It now offers today's own adjustment."""
    source = _mark_0808_source()

    red = interval_editor_snapshot(source, "62% FTP intervals", verdict="Red")

    # The generic preset is unchanged and still available — it is just not the default.
    assert red.scaled.work.duration_sec == 1575  # the 37-minute number Mark got
    assert _snapshot_total_sec(red.scaled, 600) == 2175
    # Today's adjustment is a different, and now the pre-filled, block.
    assert red.todays_adjustment is not None
    assert red.todays_adjustment.work.duration_sec != red.scaled.work.duration_sec


def test_todays_adjustment_lands_on_the_transforms_own_total() -> None:
    """The fixed 5+5 ramps are read-only, so scaling the block alone diluted a 50%
    cut to 19%. The block absorbs the whole reduction instead, so the editor and
    ``adjust_ir_for_verdict`` agree on the total the brief quotes."""
    source = _mark_0808_source()
    fixed_sec = 600  # the two 5-minute ramps
    base_ir = {"steps": expand_structured_steps(source, "62% FTP intervals")}
    assert sum(int(s["durationSec"]) for s in base_ir["steps"]) == 2700

    for verdict, companion in (("Amber", False), ("Red", False), ("Red", True)):
        snapshot = interval_editor_snapshot(
            source, "62% FTP intervals", verdict=verdict, companion_session=companion
        )
        transformed = adjust_ir_for_verdict(base_ir, verdict, companion_session=companion)
        assert snapshot.todays_adjustment is not None
        assert (
            _snapshot_total_sec(snapshot.todays_adjustment, fixed_sec)
            == (transformed["totalDurationSec"])
        )


def test_todays_adjustment_holds_zone_two_on_red_and_caps_it_when_load_is_shared() -> None:
    source = _mark_0808_source()

    held = interval_editor_snapshot(source, "62% FTP intervals", verdict="Red")
    assert held.todays_adjustment is not None
    assert held.todays_adjustment.work.power_pct == 62  # Zone 2 held, not dropped to 60
    assert _snapshot_total_sec(held.todays_adjustment, 600) == 1890  # 32 min, never > Amber

    shared = interval_editor_snapshot(
        source, "62% FTP intervals", verdict="Red", companion_session=True
    )
    assert shared.todays_adjustment is not None
    assert shared.todays_adjustment.work.power_pct == RECOVERY_CAP_PCT
    assert _snapshot_total_sec(shared.todays_adjustment, 600) == 1350  # the old 22 min


def test_todays_adjustment_removes_reps_without_shortening_interval_legs() -> None:
    source = _mark_vo2_source()
    snapshot = interval_editor_snapshot(source, "VO₂", verdict="Amber")

    assert snapshot.todays_adjustment is not None
    assert snapshot.todays_adjustment.repeat < snapshot.current.repeat
    assert snapshot.todays_adjustment.work.duration_sec == snapshot.current.work.duration_sec
    assert snapshot.todays_adjustment.rest.duration_sec == snapshot.current.rest.duration_sec


def test_a_green_morning_offers_no_todays_adjustment() -> None:
    """Nothing is pre-filled from a verdict that made no change — the editor falls
    back to the generic preset exactly as it did before."""
    source = _mark_0808_source()

    for verdict in (None, "Green", "nonsense"):
        snapshot = interval_editor_snapshot(source, "62% FTP intervals", verdict=verdict)
        assert snapshot.todays_adjustment is None
        assert snapshot.scaled == scale_block(snapshot.current)


def test_todays_adjustment_declines_rather_than_emit_an_impossible_block() -> None:
    """When the read-only warm-up/cool-down already exceed the adjusted total there
    is no honest block to offer, so the editor offers none instead of a floor."""
    source = {
        "format": "bike",
        "steps": [
            {"label": "Warm-up", "minutes": 20, "target": "55%"},
            {
                "label": "Short set",
                "block": {
                    "repeat": 1,
                    "work": {"durationSec": 120, "powerPct": 62},
                    "rest": {"durationSec": 0, "powerPct": 55},
                },
            },
            {"label": "Cool-down", "minutes": 20, "target": "55%"},
        ],
    }

    snapshot = interval_editor_snapshot(source, "62%", verdict="Red", companion_session=True)

    assert snapshot.todays_adjustment is None


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
