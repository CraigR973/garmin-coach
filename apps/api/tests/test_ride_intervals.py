"""Pure unit tests for interval-resolved ride execution (Batch 44)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.services.ride_intervals import (
    classify_roles,
    power_zone,
    segment_ride_intervals,
    summarize_execution,
)


@dataclass
class _Sample:
    sample_index: int
    elapsed_sec: float | None
    power_watts: float | None
    heart_rate_bpm: float | None = None
    cadence_rpm: float | None = None
    moving_duration_sec: float | None = None


def _trace(*segments: tuple[int, float | None, float | None]) -> list[_Sample]:
    """Lay out per-second samples from ``(duration_sec, power, hr)`` segments."""
    samples: list[_Sample] = []
    for duration, power, hr in segments:
        for _ in range(duration):
            index = len(samples)
            samples.append(_Sample(index, float(index), power, hr, cadence_rpm=90))
    return samples


def _with_moving_clock(
    samples: list[_Sample], *, pause_after_sec: int, pause_sec: int
) -> list[_Sample]:
    """Add Garmin's two clocks to a trace, as a mid-ride pause records them.

    ``elapsed_sec`` keeps counting through a pause and ``moving_duration_sec`` does
    not, so after the pause the wall clock runs ``pause_sec`` ahead of the workout's
    own clock — exactly the divergence Mark's 2026-08-13 ride carries (110 s).
    """
    return [
        _Sample(
            sample_index=sample.sample_index,
            elapsed_sec=(
                sample.elapsed_sec + pause_sec
                if sample.elapsed_sec is not None and sample.elapsed_sec >= pause_after_sec
                else sample.elapsed_sec
            ),
            power_watts=sample.power_watts,
            heart_rate_bpm=sample.heart_rate_bpm,
            cadence_rpm=sample.cadence_rpm,
            moving_duration_sec=sample.elapsed_sec,
        )
        for sample in samples
    ]


def _sprint_ride_trace() -> list[_Sample]:
    """Mark's 2026-08-13 shape: a Z2 block, a mid-ride pause, then 6 × 12 s sprints.

    FTP is 280 W, so the sprints' 515 W peaks read ~184% against their 185% target and
    the 154 W recoveries read 55%. The pause lands inside the Z2 block, where nothing
    reveals it, and shifts every later planned window by its whole length.
    """
    segments: list[tuple[int, float | None, float | None]] = [(1800, 182, 115)]
    for _ in range(6):
        segments.append((2, 380, 118))
        segments.append((8, 515, 120))
        segments.append((2, 400, 123))
        segments.append((168, 154, 116))
    return _with_moving_clock(_trace(*segments), pause_after_sec=1500, pause_sec=110)


def _sprint_ride_ir() -> dict[str, Any]:
    steps = [_step("Z2 base", "interval", "steady", 1800, 65, 65)]
    for index in range(6):
        steps.append(_step(f"Sprint {index + 1}", "interval", "steady", 12, 185, 185))
        steps.append(_step(f"Sprint recovery {index + 1}", "interval", "steady", 168, 55, 55))
    return _ir(*steps)


def _drop_moving_clock(samples: list[_Sample]) -> list[_Sample]:
    """The same trace as it segmented before Batch 214 — wall clock only."""
    return [
        _Sample(
            sample.sample_index,
            sample.elapsed_sec,
            sample.power_watts,
            sample.heart_rate_bpm,
            sample.cadence_rpm,
            moving_duration_sec=None,
        )
        for sample in samples
    ]


def _step(
    label: str,
    phase: str,
    kind: str,
    duration_sec: int,
    start_pct: int,
    end_pct: int,
    cadence: int | None = None,
) -> dict[str, Any]:
    step: dict[str, Any] = {
        "label": label,
        "phase": phase,
        "kind": kind,
        "durationSec": duration_sec,
        "powerStartPct": start_pct,
        "powerEndPct": end_pct,
    }
    if cadence:
        step["cadenceRpm"] = cadence
    return step


def _ir(*steps: dict[str, Any]) -> dict[str, Any]:
    return {"version": 1, "steps": list(steps)}


# FTP 100 so a step held at N watts reads exactly N% FTP — assertions stay legible.
_FTP = 100


def test_warmup_two_sweetspot_cooldown_grades_only_work() -> None:
    ir = _ir(
        _step("Warm-up", "warmup", "ramp", 60, 50, 70),
        _step("Sweet spot 1", "interval", "steady", 300, 91, 91),
        _step("Recovery", "interval", "steady", 60, 50, 50),
        _step("Sweet spot 2", "interval", "steady", 300, 91, 91),
        _step("Cool-down", "cooldown", "ramp", 60, 70, 40),
    )
    trace = _trace(
        (60, 60, 110),  # warm-up
        (300, 91, 150),  # SS1 held on target
        (60, 50, 120),  # recovery valley
        (300, 91, 150),  # SS2 held on target
        (60, 55, 110),  # cool-down
    )

    intervals = segment_ride_intervals(trace, ir, _FTP)

    assert [item["role"] for item in intervals] == [
        "warmup",
        "work",
        "recovery",
        "work",
        "cooldown",
    ]
    # Work intervals graded on their own target; warm-up/recovery/cool-down are not.
    for work_index in (1, 3):
        work = intervals[work_index]
        assert work["adherence"] == "on"
        assert work["pctFtp"] == 91.0
        assert work["fade"] is False
        assert work["hrDriftPct"] == 0.0
    for ungraded_index in (0, 2, 4):
        ungraded = intervals[ungraded_index]
        assert ungraded["adherence"] is None
        assert ungraded["fade"] is None
        assert ungraded["hrDriftPct"] is None
    assert {item["boundarySource"] for item in intervals} == {"planned_durations"}


def test_actual_laps_grade_shortened_erg_work_at_the_power_really_held() -> None:
    ftp = 280
    ir = _ir(
        _step("Warm-up", "warmup", "ramp", 600, 55, 80),
        _step("Sweet spot 1", "interval", "steady", 1500, 89, 89),
        _step("Recovery", "interval", "steady", 180, 60, 60),
        _step("Sweet spot 2", "interval", "steady", 1500, 89, 89),
        _step("Cool-down", "cooldown", "ramp", 600, 70, 45),
    )
    # He executed 2×15 min at 250 W with a 5-min 170 W recovery, not the
    # planned 2×25/3-min clock.
    trace = _trace(
        (600, 185, 120),
        (900, 250, 150),
        (300, 170, 125),
        (900, 250, 151),
        (600, 150, 115),
    )
    laps = [
        {"lapIndex": 1, "elapsedDuration": 600},
        {"lapIndex": 2, "elapsedDuration": 900},
        {"lapIndex": 3, "elapsedDuration": 300},
        {"lapIndex": 4, "elapsedDuration": 900},
        {"lapIndex": 5, "elapsedDuration": 600},
    ]

    planned_clock = segment_ride_intervals(trace, ir, None)
    actual = segment_ride_intervals(trace, ir, ftp, actual_laps=laps)

    assert planned_clock[1]["avgPowerWatts"] != 250.0
    assert [actual[index]["avgPowerWatts"] for index in (1, 3)] == [250.0, 250.0]
    assert [actual[index]["durationSec"] for index in (1, 3)] == [900, 900]
    assert [actual[index]["adherence"] for index in (1, 3)] == ["on", "on"]
    assert {item["boundarySource"] for item in actual} == {"actual_laps"}


def test_one_whole_ride_lap_uses_executed_trace_transitions() -> None:
    ftp = 280
    ir = _ir(
        _step("Warm-up", "warmup", "ramp", 600, 55, 80),
        _step("Sweet spot 1", "interval", "steady", 1500, 89, 89),
        _step("Recovery", "interval", "steady", 180, 60, 60),
        _step("Sweet spot 2", "interval", "steady", 1500, 89, 89),
        _step("Cool-down", "cooldown", "ramp", 600, 70, 45),
    )
    trace = _trace(
        (600, 185, 120),
        (900, 250, 150),
        (300, 170, 125),
        (900, 250, 151),
        (600, 150, 115),
    )

    intervals = segment_ride_intervals(
        trace,
        ir,
        ftp,
        actual_laps=[{"lapIndex": 1, "elapsedDuration": 3300}],
    )

    assert [intervals[index]["avgPowerWatts"] for index in (1, 3)] == [250.0, 250.0]
    assert all(895 <= intervals[index]["durationSec"] <= 905 for index in (1, 3))
    assert {item["boundarySource"] for item in intervals} == {"actual_trace"}


def test_non_matching_trace_keeps_planned_duration_fallback() -> None:
    ir = _ir(_step("Threshold", "interval", "steady", 600, 91, 91))
    trace = _trace((300, 50, 110))

    intervals = segment_ride_intervals(trace, ir, _FTP)

    assert intervals[0]["durationSec"] == 600
    assert intervals[0]["boundarySource"] == "planned_durations"


def test_fading_work_interval_flags_fade_and_steady_does_not() -> None:
    ir = _ir(_step("VO2 block", "interval", "steady", 600, 105, 105))
    fading = _trace((300, 110, None), (300, 92, None))  # last third drops well below first
    steady = _trace((600, 105, None))

    faded = segment_ride_intervals(fading, ir, _FTP)[0]
    held = segment_ride_intervals(steady, ir, _FTP)[0]

    assert faded["fade"] is True
    assert held["fade"] is False


def test_adherence_over_and_under_vs_target_band() -> None:
    ir = _ir(_step("Threshold", "interval", "steady", 300, 91, 91))

    over = segment_ride_intervals(_trace((300, 100, None)), ir, _FTP)[0]
    under = segment_ride_intervals(_trace((300, 80, None)), ir, _FTP)[0]
    on = segment_ride_intervals(_trace((300, 91, None)), ir, _FTP)[0]

    assert over["adherence"] == "over"
    assert under["adherence"] == "under"
    assert on["adherence"] == "on"


def test_normalized_power_uses_mean_below_window_and_rolling_above() -> None:
    short_ir = _ir(_step("Sprint", "interval", "steady", 20, 150, 150))
    short = segment_ride_intervals(_trace((20, 150, None)), short_ir, _FTP)[0]
    # Under the 30 s rolling window NP collapses to the plain mean.
    assert short["normalizedPowerWatts"] == 150.0

    long_ir = _ir(_step("Tempo", "interval", "steady", 120, 80, 80))
    steady = segment_ride_intervals(_trace((120, 80, None)), long_ir, _FTP)[0]
    # A perfectly steady effort has NP == avg.
    assert steady["normalizedPowerWatts"] == 80.0


def test_no_plan_or_no_trace_returns_empty() -> None:
    ir = _ir(_step("Work", "interval", "steady", 300, 91, 91))
    assert segment_ride_intervals(_trace((300, 91, None)), None, _FTP) == []
    assert segment_ride_intervals([], ir, _FTP) == []
    assert segment_ride_intervals(_trace((300, 91, None)), {"steps": []}, _FTP) == []


def test_endurance_single_steady_step_is_work() -> None:
    ir = _ir(_step("Zone 2", "interval", "steady", 3600, 65, 65))
    intervals = segment_ride_intervals(_trace((3600, 65, 130)), ir, _FTP)
    assert len(intervals) == 1
    assert intervals[0]["role"] == "work"
    assert intervals[0]["adherence"] == "on"


def test_all_easy_ride_promotes_recovery_to_work() -> None:
    # Nothing clears the work threshold, so the easy steps become the work set —
    # grading them against their own easy target rather than grading nothing.
    steps = [
        _step("Spin 1", "interval", "steady", 300, 50, 50),
        _step("Spin 2", "interval", "steady", 300, 55, 55),
    ]
    assert classify_roles(steps) == ["work", "work"]


def test_classify_roles_uses_ramp_direction_without_phase_label() -> None:
    rising = _step("Ramp up", "interval", "ramp", 120, 50, 75)
    falling = _step("Ramp down", "interval", "ramp", 120, 75, 45)
    assert classify_roles([rising, falling]) == ["warmup", "cooldown"]


def test_summarize_execution_with_work_intervals() -> None:
    intervals: list[dict[str, Any]] = [
        {
            "role": "warmup",
            "adherence": None,
            "fade": None,
            "boundarySource": "actual_laps",
        },
        {
            "role": "work",
            "adherence": "on",
            "fade": False,
            "durationSec": 1200,
            "label": "Sweet spot",
            "targetPctFtpLow": 91,
            "targetPctFtpHigh": 91,
            "pctFtp": 91.0,
            "normalizedPowerWatts": 250,
            "boundarySource": "actual_laps",
        },
    ]
    execution = summarize_execution(intervals, whole_ride_avg_power_watts=180)

    assert execution["hasPlan"] is True
    assert execution["workIntervalCount"] == 1
    assert execution["onTargetCount"] == 1
    assert execution["wholeRideAvgPowerWatts"] == 180
    assert "context only" in execution["wholeRideContextNote"]
    assert "on target" in execution["summary"]
    assert "Sweet spot" in execution["workIntervals"][0]
    assert execution["boundarySource"] == "actual_laps"
    assert "executed lap boundaries" in execution["boundarySourceNote"]


def test_summarize_execution_without_plan_omits_context_disclaimer() -> None:
    execution = summarize_execution([], whole_ride_avg_power_watts=210)
    assert execution["hasPlan"] is False
    assert execution["workIntervalCount"] == 0
    assert execution["boundarySource"] == "none"
    # A free ride's whole-ride average is the real read, so it is not disclaimed.
    assert "wholeRideContextNote" not in execution
    assert execution["wholeRideAvgPowerWatts"] == 210


# --- Batch 214: a 12-second sprint is graded on evidence that exists ---------------


def test_mid_ride_pause_no_longer_shifts_every_later_window() -> None:
    """The 2026-08-13 regression: 110 s of pause moved six sprints out of their windows.

    On the wall clock the sprint windows land in the recovery valleys, so each sprint
    records *below* the recovery that follows it — in production that shipped as six
    "under" grades. On the workout's own clock the same six efforts are found, and
    their 515 W peaks grade on target.
    """
    ir = _sprint_ride_ir()
    trace = _sprint_ride_trace()
    sprint_indices = [1, 3, 5, 7, 9, 11]

    before = segment_ride_intervals(_drop_moving_clock(trace), ir, 280)
    after = segment_ride_intervals(trace, ir, 280)

    # Before: no sprint window contains a sprint. The first lands back in the Z2 block
    # and the rest land in recovery valleys — the same 182 / 154 signature the real
    # 08-13 packet carries (64.7% FTP then five reads of 54.x%).
    assert [before[index]["avgPowerWatts"] for index in sprint_indices] == [182.0] + [154.0] * 5
    # After: the same windows now contain the efforts he actually rode.
    assert all(after[index]["avgPowerWatts"] == 473.3 for index in sprint_indices)

    # So nothing in the "before" read can be graded honestly, and nothing is — the
    # app never repeats the "under" it shipped.
    assert all(
        before[index]["gradedPctFtp"] < before[index + 1]["pctFtp"] for index in sprint_indices
    )
    assert [before[index]["adherence"] for index in sprint_indices] == [None] * 6
    assert before[0]["clockSource"] == "elapsed_sec"
    assert before[0]["pausedSec"] == 0

    # And the peaks he produced are in the packet, graded against their own target.
    assert [after[index]["adherence"] for index in sprint_indices] == ["on"] * 6
    assert [after[index]["maxPowerWatts"] for index in sprint_indices] == [515.0] * 6
    assert all(after[index]["peakPctFtp"] == 183.9 for index in sprint_indices)
    assert after[0]["clockSource"] == "moving_duration_sec"
    assert after[0]["pausedSec"] == 110


def test_short_effort_grades_on_peak_and_long_effort_still_grades_on_mean() -> None:
    # A 12 s sprint whose window mean is dragged down by its own acceleration ramp
    # still reached its target at the peak, which is what the prescription asks for.
    sprint_ir = _ir(_step("Sprint", "interval", "steady", 12, 185, 185))
    sprint = segment_ride_intervals(_trace((4, 60, None), (8, 190, None)), sprint_ir, _FTP)[0]
    assert sprint["pctFtp"] == 146.7
    assert sprint["peakPctFtp"] == 190.0
    assert sprint["gradedPctFtp"] == 190.0
    assert sprint["adherence"] == "on"
    assert "peak" in sprint["gradeBasis"].lower()

    # Anything long enough to hold is still judged on the power he held.
    tempo_ir = _ir(_step("Tempo", "interval", "steady", 600, 91, 91))
    tempo = segment_ride_intervals(_trace((300, 91, None), (300, 60, None)), tempo_ir, _FTP)[0]
    assert tempo["gradedPctFtp"] == tempo["pctFtp"] == 75.5
    assert tempo["adherence"] == "under"
    assert tempo["maxPowerWatts"] == 91.0
    assert "average" in tempo["gradeBasis"].lower()


def test_peak_graded_sprint_is_never_marked_over() -> None:
    # Beating a sprint target is the point of a sprint, not a pacing error.
    ir = _ir(_step("Sprint", "interval", "steady", 12, 150, 150))
    sprint = segment_ride_intervals(_trace((12, 240, None)), ir, _FTP)[0]
    assert sprint["peakPctFtp"] == 240.0
    assert sprint["adherence"] == "on"

    # A sprint genuinely not attempted is still called under.
    missed = segment_ride_intervals(_trace((12, 70, None)), ir, _FTP)[0]
    assert missed["adherence"] == "under"


def test_work_recorded_below_adjacent_recovery_withholds_the_grade() -> None:
    """The general net: nobody rests harder than they sprint."""
    ir = _ir(
        _step("Effort", "interval", "steady", 300, 100, 100),
        _step("Valley", "interval", "steady", 300, 50, 50),
    )
    intervals = segment_ride_intervals(_trace((300, 40, None), (300, 60, None)), ir, _FTP)

    work = intervals[0]
    assert work["role"] == "work"
    assert work["gradedPctFtp"] == 40.0
    assert work["adherence"] is None
    assert work["gradeWithheldReason"] == "recorded_below_adjacent_recovery"

    execution = summarize_execution(intervals, whole_ride_avg_power_watts=50)
    assert execution["ungradedCount"] == 1
    assert execution["underCount"] == 0
    assert "ungraded" in execution["summary"]
    assert "could not measure" in execution["ungradedNote"]
    assert "grade withheld" in execution["workIntervals"][0]


def test_consistency_guard_is_a_detector_not_a_blanket_suppressor() -> None:
    # It fires on all six sprints while the clock is wrong and on none once it is
    # right — the property that makes it worth keeping.
    ir = _sprint_ride_ir()
    trace = _sprint_ride_trace()

    before = segment_ride_intervals(_drop_moving_clock(trace), ir, 280)
    after = segment_ride_intervals(trace, ir, 280)

    assert sum(1 for item in before if item.get("gradeWithheldReason")) == 6
    assert sum(1 for item in after if item.get("gradeWithheldReason")) == 0


def test_moving_clock_reads_the_lap_duration_that_matches_it() -> None:
    # A lap carries both clocks; pairing the wall-clock one with a pause-excluding
    # sample clock would reintroduce the drift the clock exists to remove.
    ir = _ir(
        _step("Work", "interval", "steady", 300, 91, 91),
        _step("Valley", "interval", "steady", 300, 50, 50),
    )
    trace = _with_moving_clock(
        _trace((200, 91, None), (400, 50, None)), pause_after_sec=200, pause_sec=110
    )
    laps = [
        {"lapIndex": 1, "duration": 200, "elapsedDuration": 310},
        {"lapIndex": 2, "duration": 400, "elapsedDuration": 400},
    ]

    intervals = segment_ride_intervals(trace, ir, _FTP, actual_laps=laps)

    assert {item["boundarySource"] for item in intervals} == {"actual_laps"}
    assert [item["durationSec"] for item in intervals] == [200, 400]
    assert intervals[0]["avgPowerWatts"] == 91.0


def test_partial_moving_column_keeps_the_elapsed_clock() -> None:
    # A legacy or half-imported trace must not be segmented on a column that only
    # covers part of the ride.
    ir = _ir(_step("Work", "interval", "steady", 300, 91, 91))
    trace = _with_moving_clock(_trace((300, 91, None)), pause_after_sec=100, pause_sec=60)
    trace[10].moving_duration_sec = None

    assert segment_ride_intervals(trace, ir, _FTP)[0]["clockSource"] == "elapsed_sec"


def test_power_zone_thresholds() -> None:
    assert power_zone(50, 100) == "Z1"
    assert power_zone(60, 100) == "Z2"
    assert power_zone(80, 100) == "Z3"
    assert power_zone(100, 100) == "Z4"
    assert power_zone(110, 100) == "Z5"
    assert power_zone(130, 100) == "Z6"
    assert power_zone(None, 100) is None
    assert power_zone(200, None) is None
