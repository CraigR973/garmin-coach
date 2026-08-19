"""Interval-resolved ride execution (Batch 44).

Pure, DB-free segmentation of a ride's per-second trace against its planned
structured-workout IR (Batch 12.1), grading each *work* interval on its own %FTP
target instead of judging the whole ride by its blended average power.

The bug this fixes (Mark, 2026-07-02): the post-ride packet handed Claude the
whole-ride average power, so on a structured session the blended average sits
below the work band (warm-up + recovery valleys + cool-down drag it down) and the
model either anchored on it or pattern-matched the workout's name. Here we slice
the executed trace on the IR's interval boundaries, grade only the *work*
intervals against their targets, and describe (never grade) warm-up/recovery/
cool-down power.

Batch 214 (Mark, 2026-08-13) fixes three ways this could still hand the model a
false grade, in the order they bite:

1. **The clock.** A pause stops the workout but not the ride. Garmin's
   ``sumElapsedDuration`` counts paused seconds; the IR's planned windows are
   timer time. Segmenting on elapsed time therefore shifts every window after a
   pause by its whole length — 110 s on the 08-13 ride, on which 31 of Mark's
   last 57 rides carry a pause over 30 s. Segment on the pause-excluding clock
   whenever the trace carries one.
2. **The statistic.** A neuromuscular sprint is prescribed as a *peak*, not a
   held average: a 12 s window's mean is dragged down by its own acceleration
   ramp. Short work efforts grade on peak power, and never "over" — exceeding a
   sprint target is not a failure.
3. **The evidence.** Planned-clock boundaries carry an uncertainty that can rival
   a short effort's whole duration, so a short effort's peak is searched in a
   neighbourhood of its nominal window; and any work interval that records below
   an adjacent recovery is a segmentation failure rather than a performance
   result, so its grade is withheld and said to be withheld.

See docs/designs/interval-resolved-ride-analysis.md.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from statistics import median
from typing import Any, Protocol

# A steady interval step at/below this %FTP target sitting between efforts is a
# recovery valley, not a work interval — its power is described, never graded.
RECOVERY_CEILING_PCT = 60
# Grading slack (in %FTP points) around a work step's target. build_structured_workout_ir
# collapses a target band to its midpoint for steady steps, and ERG holds it with
# small noise, so allow a little slack before calling a work interval over/under.
ADHERENCE_TOLERANCE_PCT = 5
# Fade needs a long enough effort for first-third vs last-third to mean anything.
FADE_MIN_DURATION_SEC = 180
# A work interval fades if its last third averages this fraction below its first.
FADE_DROP_FRACTION = 0.05
# Normalised power needs a ~30 s rolling window to be meaningful; below this use the mean.
NP_ROLLING_WINDOW_SEC = 30
# Garmin/Zwift imports commonly expose one whole-ride lap even for a structured
# workout. When useful step laps are absent, a 5 s dynamic-time-warp alignment
# can recover the executed boundaries from the known target-power sequence. It
# is accepted only when the trace fits that sequence closely and materially
# better than the planned clock, so noisy/free rides keep the old fallback.
TRACE_ALIGNMENT_BIN_SEC = 5
TRACE_ALIGNMENT_MAX_RMSE_PCT_FTP = 8.0
LAP_ALIGNMENT_MAX_RMSE_PCT_FTP = 12.0
TRACE_ALIGNMENT_MIN_IMPROVEMENT_PCT_FTP = 1.0
TRACE_ALIGNMENT_WARP_PENALTY = 4.0
TRACE_ALIGNMENT_MAX_POINT_ERROR_PCT_FTP = 30.0

# A work effort at or below this length is neuromuscular: the prescription means
# "peak at or near target", and a window mean over it is dominated by the effort's
# own acceleration ramp rather than by what the athlete produced.
PEAK_GRADED_MAX_DURATION_SEC = 30
# On boundaries we did not observe, a short effort's peak is searched either side of
# its nominal window by its own duration — self-scaling, and clamped below so it can
# never reach into a neighbouring work step.
PEAK_SEARCH_SLACK_MULTIPLE = 1.0

# The whole-ride average, once intervals exist, is context only — never the verdict.
WHOLE_RIDE_CONTEXT_NOTE = (
    "Whole-ride average power is context only. On a structured session it sits "
    "below the work target because the warm-up, recovery valleys, and cool-down "
    "pull it down. It is not the execution verdict and never indicates "
    "under-performance — grade execution on the work intervals below."
)

# An ungraded interval is a gap in what we measured, not a gap in what he did.
UNGRADED_INTERVAL_NOTE = (
    "One or more work intervals recorded below an adjacent recovery valley, which "
    "means the window did not sit on the effort — a measurement failure on our side, "
    "not a performance result. Their grade has been withheld deliberately. Say the "
    "app could not measure those efforts, and do not offer a reason he fell short: no "
    "trainer, ERG, pacing or fatigue explanation, and no counting them as "
    "under-performance anywhere in the read."
)


class TraceSample(Protocol):
    """The per-second trace fields segmentation reads (a subset of ActivityTimeSeries)."""

    elapsed_sec: float | None
    moving_duration_sec: float | None
    sample_index: int
    power_watts: float | None
    heart_rate_bpm: float | None
    cadence_rpm: float | None


def power_zone(power_watts: float | None, ftp_watts: int | None) -> str | None:
    """Coggan power zone for a wattage against FTP; ``None`` when either is missing."""
    if power_watts is None or not ftp_watts:
        return None
    pct = power_watts / ftp_watts
    if pct < 0.56:
        return "Z1"
    if pct < 0.76:
        return "Z2"
    if pct < 0.91:
        return "Z3"
    if pct < 1.06:
        return "Z4"
    if pct < 1.21:
        return "Z5"
    return "Z6"


def segment_ride_intervals(
    timeseries: Sequence[TraceSample],
    ir: Mapping[str, Any] | None,
    ftp_watts: int | None,
    *,
    actual_laps: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Slice the per-second trace on the best honest interval boundaries.

    Timestamped Garmin laps are preferred when they match the planned step
    sequence. Zwift often supplies only one whole-ride lap, so a clearly-fitting
    target-power trace may recover the executed step boundaries next. The original
    cumulative planned-duration clock remains the conservative fallback. Work
    intervals carry an ``adherence`` grade and a ``fade`` flag against their own
    target; warm-up/recovery/cool-down power is described, never graded. Returns
    ``[]`` when there is no plan or no trace so the caller degrades to the whole-
    ride read.
    """
    steps = ir.get("steps") if ir else None
    if not isinstance(steps, list) or not steps or not timeseries:
        return []

    roles = classify_roles(steps)
    clock_source, paused_sec = _segmentation_clock(timeseries)
    timed = sorted(
        ((_sample_time(s, clock_source), s) for s in timeseries), key=lambda pair: pair[0]
    )
    windows, boundary_source = _segmentation_windows(
        timed,
        steps,
        ftp_watts,
        actual_laps=actual_laps,
        clock_source=clock_source,
    )

    intervals: list[dict[str, Any]] = []
    for index, (step, role, (t_start, t_end)) in enumerate(zip(steps, roles, windows, strict=True)):
        duration = t_end - t_start
        window = [sample for time, sample in timed if t_start <= time < t_end]
        grade_start, grade_end = _grading_bounds(index, roles, windows, boundary_source)
        grading_window = (
            window
            if (grade_start, grade_end) == (t_start, t_end)
            else [sample for time, sample in timed if grade_start <= time < grade_end]
        )
        intervals.append(
            _build_interval(
                index,
                step,
                role,
                duration,
                window,
                ftp_watts,
                boundary_source=boundary_source,
                clock_source=clock_source,
                paused_sec=paused_sec,
                grading_window=grading_window,
                grading_slack_sec=t_start - grade_start,
            )
        )
    _withhold_inconsistent_grades(intervals)
    return intervals


def _segmentation_clock(timeseries: Sequence[TraceSample]) -> tuple[str, int]:
    """Choose the clock the planned windows are actually measured in, and the pause.

    The IR's cumulative step durations are *timer* time, so a trace that carries
    Garmin's pause-excluding ``sumMovingDuration`` must be segmented on it: on the
    elapsed clock every window after a pause is shifted by the pause's whole length,
    which is invisible on a steady block and catastrophic on a short effort. Falls
    back to elapsed time — the pre-Batch-214 behaviour — unless the moving clock is
    present and coherent on the whole trace, so a partial or legacy import is never
    segmented on a half-populated column.
    """
    pairs: list[tuple[float, float]] = []
    for sample in timeseries:
        value = getattr(sample, "moving_duration_sec", None)
        if value is None:
            return "elapsed_sec", 0
        pairs.append((_sample_time(sample), float(value)))

    pairs.sort(key=lambda pair: pair[0])
    moving = [value for _elapsed, value in pairs]
    if moving[-1] <= 0 or any(later < earlier for earlier, later in zip(moving, moving[1:])):
        return "elapsed_sec", 0

    elapsed_span = pairs[-1][0] - pairs[0][0]
    return "moving_duration_sec", max(0, int(round(elapsed_span - (moving[-1] - moving[0]))))


def _grading_bounds(
    index: int,
    roles: Sequence[str],
    windows: Sequence[tuple[float, float]],
    boundary_source: str,
) -> tuple[float, float]:
    """Where to look for a short effort's peak when the boundaries are not observed.

    A planned-clock boundary can be out by as much as a sprint is long, so grading a
    12 s effort strictly inside its nominal 12 s asks a question the boundaries cannot
    answer. Search either side by the step's own duration, clamped to the midpoint of
    each neighbouring recovery so a sprint can never be graded on its neighbour's peak.
    Observed lap boundaries need none of this and get their exact window.
    """
    start, end = windows[index]
    duration = end - start
    if (
        boundary_source == "actual_laps"
        or roles[index] != "work"
        or duration <= 0
        or duration > PEAK_GRADED_MAX_DURATION_SEC
    ):
        return start, end

    slack = duration * PEAK_SEARCH_SLACK_MULTIPLE
    if index > 0:
        previous_start, previous_end = windows[index - 1]
        slack = min(slack, max(0.0, (previous_end - previous_start) / 2))
    if index + 1 < len(windows):
        next_start, next_end = windows[index + 1]
        slack = min(slack, max(0.0, (next_end - next_start) / 2))
    return start - slack, end + slack


def classify_roles(steps: Sequence[Mapping[str, Any]]) -> list[str]:
    """Assign warmup / work / recovery / cooldown to each IR step.

    Warm-up and cool-down come straight from the IR ``phase`` (derived from the step
    label by build_structured_workout_ir) or a leading/trailing ramp; among the
    remaining steady interval steps, one at/below ``RECOVERY_CEILING_PCT`` is a
    recovery valley and the rest are work. If nothing classifies as work (e.g. an
    all-easy active-recovery ride), the recovery steps are promoted to work — there
    is no other effort to read, so grading them against their own easy target is the
    honest read rather than grading nothing.
    """
    roles: list[str] = []
    for step in steps:
        phase = str(step.get("phase") or "")
        kind = str(step.get("kind") or "")
        if phase == "warmup":
            roles.append("warmup")
        elif phase == "cooldown":
            roles.append("cooldown")
        elif kind == "ramp":
            roles.append("warmup" if _ramp_is_rising(step) else "cooldown")
        elif _target_mid(step) > RECOVERY_CEILING_PCT:
            roles.append("work")
        else:
            roles.append("recovery")

    if "work" not in roles:
        roles = ["work" if role == "recovery" else role for role in roles]
    return roles


def summarize_execution(
    intervals: Sequence[Mapping[str, Any]],
    *,
    whole_ride_avg_power_watts: float | int | None,
) -> dict[str, Any]:
    """A compact execution read the model leads with, so it grades the work — not
    the blended average. ``hasPlan`` is False for a free/outdoor ride (no IR)."""
    has_plan = bool(intervals)
    work = [item for item in intervals if item.get("role") == "work"]
    boundary_source = (
        str(intervals[0].get("boundarySource") or "planned_durations") if has_plan else "none"
    )
    clock_source = str(intervals[0].get("clockSource") or "elapsed_sec") if has_plan else "none"
    paused_sec = int(intervals[0].get("pausedSec") or 0) if has_plan else 0

    if not work:
        summary = (
            "No planned structure — read the whole-ride effort and power zones."
            if not has_plan
            else "Planned session had no gradable work intervals."
        )
        result: dict[str, Any] = {
            "hasPlan": has_plan,
            "workIntervalCount": 0,
            "workIntervals": [],
            "summary": summary,
            "wholeRideAvgPowerWatts": whole_ride_avg_power_watts,
            "boundarySource": boundary_source,
            "boundarySourceNote": _boundary_source_note(boundary_source),
        }
        if has_plan:
            result["wholeRideContextNote"] = WHOLE_RIDE_CONTEXT_NOTE
            result["clockSource"] = clock_source
            result["pausedSec"] = paused_sec
        return result

    on = sum(1 for item in work if item.get("adherence") == "on")
    over = sum(1 for item in work if item.get("adherence") == "over")
    under = sum(1 for item in work if item.get("adherence") == "under")
    withheld = [item for item in work if item.get("gradeWithheldReason")]
    faded = sum(1 for item in work if item.get("fade") is True)

    summary = (
        f"{len(work)} work interval(s): {on} on target, {over} over, {under} under"
        + (f", {len(withheld)} ungraded" if withheld else "")
        + f"; {f'fade in {faded} block(s)' if faded else 'no fade'}."
    )
    result = {
        "hasPlan": True,
        "workIntervalCount": len(work),
        "onTargetCount": on,
        "overCount": over,
        "underCount": under,
        "ungradedCount": len(withheld),
        "fadedCount": faded,
        "workIntervals": [_work_interval_phrase(item) for item in work],
        "summary": summary,
        "wholeRideAvgPowerWatts": whole_ride_avg_power_watts,
        "wholeRideContextNote": WHOLE_RIDE_CONTEXT_NOTE,
        "boundarySource": boundary_source,
        "boundarySourceNote": _boundary_source_note(boundary_source),
        "clockSource": clock_source,
        "pausedSec": paused_sec,
    }
    if withheld:
        result["ungradedNote"] = UNGRADED_INTERVAL_NOTE
    return result


def _build_interval(
    index: int,
    step: Mapping[str, Any],
    role: str,
    duration_sec: float,
    window: Sequence[TraceSample],
    ftp_watts: int | None,
    *,
    boundary_source: str,
    clock_source: str,
    paused_sec: int,
    grading_window: Sequence[TraceSample],
    grading_slack_sec: float,
) -> dict[str, Any]:
    powers = [float(s.power_watts) for s in window if s.power_watts is not None]
    hrs = [float(s.heart_rate_bpm) for s in window if s.heart_rate_bpm is not None]
    cadences = [float(s.cadence_rpm) for s in window if s.cadence_rpm is not None]

    avg_power = round(sum(powers) / len(powers), 1) if powers else None
    pct_ftp = round(avg_power / ftp_watts * 100, 1) if avg_power is not None and ftp_watts else None
    target_low = min(_int(step, "powerStartPct"), _int(step, "powerEndPct"))
    target_high = max(_int(step, "powerStartPct"), _int(step, "powerEndPct"))
    is_work = role == "work"

    # A short effort is prescribed as a peak, so it is graded on the highest power it
    # reached — searched a little wider than its nominal window when the boundaries
    # were not observed. Everything longer keeps the held-average grade it always had.
    peak_graded = is_work and 0 < duration_sec <= PEAK_GRADED_MAX_DURATION_SEC
    peak_powers = [float(s.power_watts) for s in grading_window if s.power_watts is not None]
    max_power = round(max(peak_powers), 1) if peak_powers else None
    peak_pct_ftp = (
        round(max_power / ftp_watts * 100, 1) if max_power is not None and ftp_watts else None
    )
    graded_pct_ftp = peak_pct_ftp if peak_graded else pct_ftp

    return {
        "index": index,
        "label": str(step.get("label") or f"Step {index + 1}"),
        "role": role,
        "boundarySource": boundary_source,
        "clockSource": clock_source,
        "pausedSec": paused_sec,
        "durationSec": int(round(duration_sec)),
        "sampleCount": len(window),
        "avgPowerWatts": avg_power,
        "maxPowerWatts": max_power,
        "normalizedPowerWatts": _normalized_power(powers),
        "pctFtp": pct_ftp,
        "peakPctFtp": peak_pct_ftp,
        "powerZone": power_zone(avg_power, ftp_watts),
        "avgHeartRateBpm": round(sum(hrs) / len(hrs), 1) if hrs else None,
        "maxHeartRateBpm": round(max(hrs), 1) if hrs else None,
        "avgCadenceRpm": round(sum(cadences) / len(cadences), 1) if cadences else None,
        "targetPctFtpLow": target_low,
        "targetPctFtpHigh": target_high,
        "cadenceTargetRpm": _int(step, "cadenceRpm") if step.get("cadenceRpm") else None,
        # Graded only for work intervals; described (None grade) for everything else.
        "adherence": (
            _adherence(graded_pct_ftp, target_low, target_high, peak_graded=peak_graded)
            if is_work
            else None
        ),
        "gradedPctFtp": graded_pct_ftp if is_work else None,
        "gradeBasis": (
            _grade_basis(peak_graded, duration_sec, grading_slack_sec) if is_work else None
        ),
        "gradeWithheldReason": None,
        "fade": _fade(window, duration_sec) if is_work else None,
        "hrDriftPct": _hr_drift_pct(window, duration_sec) if is_work else None,
    }


def _grade_basis(peak_graded: bool, duration_sec: float, slack_sec: float) -> str:
    if not peak_graded:
        return "Held average power across the interval."
    if slack_sec <= 0:
        return (
            f"Peak power in this {int(round(duration_sec))} s effort — a sprint "
            "target is a peak, not an average."
        )
    return (
        f"Peak power in this {int(round(duration_sec))} s effort, searched "
        f"±{int(round(slack_sec))} s around boundaries we did not observe — a sprint "
        "target is a peak, not an average."
    )


def _withhold_inconsistent_grades(intervals: list[dict[str, Any]]) -> None:
    """Withhold any work grade that contradicts its own neighbours.

    A work interval recording *below* an adjacent recovery valley is not a
    performance result — nobody rests harder than they sprint — it is a sign the
    window is not sitting on the effort. On Mark's 08-13 ride this fired on all six
    sprints before the clock was fixed and on none of them after, which is the
    property that makes it a detector rather than a blanket suppressor. The grade is
    removed and the reason recorded, so the read says it could not measure rather
    than inventing a reason the athlete fell short.
    """
    for index, interval in enumerate(intervals):
        graded = interval.get("gradedPctFtp")
        if interval.get("role") != "work" or interval.get("adherence") is None or graded is None:
            continue
        neighbours = [
            value
            for offset in (-1, 1)
            if 0 <= index + offset < len(intervals)
            and intervals[index + offset].get("role") == "recovery"
            and (value := intervals[index + offset].get("pctFtp")) is not None
        ]
        if neighbours and graded < max(neighbours):
            interval["adherence"] = None
            interval["gradeWithheldReason"] = "recorded_below_adjacent_recovery"


def _segmentation_windows(
    timed: Sequence[tuple[float, TraceSample]],
    steps: Sequence[Mapping[str, Any]],
    ftp_watts: int | None,
    *,
    actual_laps: Sequence[Mapping[str, Any]] | None,
    clock_source: str = "elapsed_sec",
) -> tuple[list[tuple[float, float]], str]:
    planned = _planned_windows(steps)

    lap_windows = _actual_lap_windows(actual_laps, steps, timed, ftp_watts, clock_source)
    if lap_windows is not None:
        return lap_windows, "actual_laps"

    trace_windows = _trace_aligned_windows(timed, steps, ftp_watts, planned)
    if trace_windows is not None:
        return trace_windows, "actual_trace"

    return planned, "planned_durations"


def _planned_windows(steps: Sequence[Mapping[str, Any]]) -> list[tuple[float, float]]:
    windows: list[tuple[float, float]] = []
    cursor = 0.0
    for step in steps:
        end = cursor + _step_duration(step)
        windows.append((cursor, end))
        cursor = end
    return windows


def _actual_lap_windows(
    actual_laps: Sequence[Mapping[str, Any]] | None,
    steps: Sequence[Mapping[str, Any]],
    timed: Sequence[tuple[float, TraceSample]],
    ftp_watts: int | None,
    clock_source: str = "elapsed_sec",
) -> list[tuple[float, float]] | None:
    """Return cumulative Garmin-lap windows only when they are credible workout steps.

    A lap carries both clocks, so the one read here must be the one the samples are
    laid out on (Batch 214): pairing a lap's wall-clock ``elapsedDuration`` with a
    pause-excluding sample clock would reintroduce the very drift that clock exists
    to remove.
    """
    if not actual_laps or len(actual_laps) != len(steps):
        return None

    preference = (
        ("duration", "elapsedDuration")
        if clock_source == "moving_duration_sec"
        else ("elapsedDuration", "duration")
    )
    durations: list[float] = []
    for lap in actual_laps:
        raw = lap.get(preference[0])
        if not isinstance(raw, int | float) or raw <= 0:
            raw = lap.get(preference[1])
        if not isinstance(raw, int | float) or raw <= 0:
            return None
        durations.append(float(raw))

    windows: list[tuple[float, float]] = []
    cursor = 0.0
    for duration in durations:
        windows.append((cursor, cursor + duration))
        cursor += duration

    trace_end = _trace_end(timed)
    if trace_end <= 0 or abs(cursor - trace_end) > max(30.0, trace_end * 0.05):
        return None
    if (
        ftp_watts
        and _windows_fit_rmse(timed, steps, windows, ftp_watts) > LAP_ALIGNMENT_MAX_RMSE_PCT_FTP
    ):
        return None
    return windows


def _trace_aligned_windows(
    timed: Sequence[tuple[float, TraceSample]],
    steps: Sequence[Mapping[str, Any]],
    ftp_watts: int | None,
    planned_windows: Sequence[tuple[float, float]],
) -> list[tuple[float, float]] | None:
    """Align a controlled ride's measured power sequence to the planned targets.

    This is deliberately fail-closed: it runs only with power + FTP, requires a
    close absolute fit, and must beat the planned clock by a material margin.
    """
    if not ftp_watts:
        return None
    planned_rmse = _windows_fit_rmse(timed, steps, planned_windows, ftp_watts)
    if planned_rmse <= TRACE_ALIGNMENT_MAX_RMSE_PCT_FTP:
        return None

    observed = _binned_power_pct(timed, ftp_watts)
    expected = _expected_power_pct(steps)
    if len(observed) < len(steps) or len(expected) < len(steps):
        return None

    match_by_step, aligned_rmse = _dtw_step_matches(observed, expected, len(steps))
    if (
        aligned_rmse > TRACE_ALIGNMENT_MAX_RMSE_PCT_FTP
        or planned_rmse - aligned_rmse < TRACE_ALIGNMENT_MIN_IMPROVEMENT_PCT_FTP
        or any(not matches for matches in match_by_step)
    ):
        return None

    boundaries = [observed[0][0]]
    for left_matches, right_matches in zip(match_by_step, match_by_step[1:]):
        left_end = observed[max(left_matches)][0] + TRACE_ALIGNMENT_BIN_SEC
        right_start = observed[min(right_matches)][0]
        boundary = (left_end + right_start) / 2
        if boundary <= boundaries[-1]:
            return None
        boundaries.append(boundary)
    boundaries.append(_trace_end(timed))

    windows = list(zip(boundaries, boundaries[1:]))
    if any(end <= start for start, end in windows):
        return None
    return windows


def _binned_power_pct(
    timed: Sequence[tuple[float, TraceSample]], ftp_watts: int
) -> list[tuple[float, float]]:
    buckets: dict[int, list[float]] = {}
    for elapsed, sample in timed:
        if sample.power_watts is None:
            continue
        bucket = int(elapsed // TRACE_ALIGNMENT_BIN_SEC)
        buckets.setdefault(bucket, []).append(float(sample.power_watts) / ftp_watts * 100)
    return [
        (bucket * TRACE_ALIGNMENT_BIN_SEC, sum(values) / len(values))
        for bucket, values in sorted(buckets.items())
    ]


def _expected_power_pct(
    steps: Sequence[Mapping[str, Any]],
) -> list[tuple[int, float]]:
    expected: list[tuple[int, float]] = []
    for step_index, step in enumerate(steps):
        point_count = max(1, round(_step_duration(step) / TRACE_ALIGNMENT_BIN_SEC))
        start = _int(step, "powerStartPct")
        end = _int(step, "powerEndPct")
        for point_index in range(point_count):
            progress = (point_index + 0.5) / point_count
            expected.append((step_index, start + (end - start) * progress))
    return expected


def _dtw_step_matches(
    observed: Sequence[tuple[float, float]],
    expected: Sequence[tuple[int, float]],
    step_count: int,
) -> tuple[list[list[int]], float]:
    """Dynamic-time-warp two short (~5 s) power series and retain a backtrace."""
    row_count = len(observed)
    column_count = len(expected)
    infinity = float("inf")
    previous = [infinity] * (column_count + 1)
    previous[0] = 0.0
    directions = [bytearray(column_count) for _ in range(row_count)]

    for row_index in range(1, row_count + 1):
        current = [infinity] * (column_count + 1)
        observed_pct = observed[row_index - 1][1]
        for column_index in range(1, column_count + 1):
            expected_pct = expected[column_index - 1][1]
            difference = observed_pct - expected_pct
            point_cost = min(
                difference * difference,
                TRACE_ALIGNMENT_MAX_POINT_ERROR_PCT_FTP**2,
            )
            diagonal = previous[column_index - 1]
            vertical = previous[column_index] + TRACE_ALIGNMENT_WARP_PENALTY
            horizontal = current[column_index - 1] + TRACE_ALIGNMENT_WARP_PENALTY
            if diagonal <= vertical and diagonal <= horizontal:
                best = diagonal
                direction = 0
            elif vertical <= horizontal:
                best = vertical
                direction = 1
            else:
                best = horizontal
                direction = 2
            current[column_index] = point_cost + best
            directions[row_index - 1][column_index - 1] = direction
        previous = current

    row_index = row_count
    column_index = column_count
    pairs: list[tuple[int, int]] = []
    while row_index > 0 and column_index > 0:
        pairs.append((row_index - 1, column_index - 1))
        direction = directions[row_index - 1][column_index - 1]
        if direction == 0:
            row_index -= 1
            column_index -= 1
        elif direction == 1:
            row_index -= 1
        else:
            column_index -= 1
    if row_index != 0 or column_index != 0 or not pairs:
        return [[] for _ in range(step_count)], float("inf")
    pairs.reverse()

    match_by_step: list[list[int]] = [[] for _ in range(step_count)]
    squared_error = 0.0
    for observed_index, expected_index in pairs:
        step_index, expected_pct = expected[expected_index]
        match_by_step[step_index].append(observed_index)
        difference = observed[observed_index][1] - expected_pct
        squared_error += min(
            difference * difference,
            TRACE_ALIGNMENT_MAX_POINT_ERROR_PCT_FTP**2,
        )
    return match_by_step, (squared_error / len(pairs)) ** 0.5


def _windows_fit_rmse(
    timed: Sequence[tuple[float, TraceSample]],
    steps: Sequence[Mapping[str, Any]],
    windows: Sequence[tuple[float, float]],
    ftp_watts: int,
) -> float:
    squared_error = 0.0
    count = 0
    for step, (start, end) in zip(steps, windows, strict=True):
        duration = end - start
        if duration <= 0:
            return float("inf")
        target_start = _int(step, "powerStartPct")
        target_end = _int(step, "powerEndPct")
        for elapsed, sample in timed:
            if not (start <= elapsed < end) or sample.power_watts is None:
                continue
            progress = min(1.0, max(0.0, (elapsed - start) / duration))
            target = target_start + (target_end - target_start) * progress
            actual = float(sample.power_watts) / ftp_watts * 100
            difference = actual - target
            squared_error += min(
                difference * difference,
                TRACE_ALIGNMENT_MAX_POINT_ERROR_PCT_FTP**2,
            )
            count += 1
    return (squared_error / count) ** 0.5 if count else float("inf")


def _trace_end(timed: Sequence[tuple[float, TraceSample]]) -> float:
    if not timed:
        return 0.0
    times = [elapsed for elapsed, _sample in timed]
    differences = [
        later - earlier for earlier, later in zip(times, times[1:]) if 0 < later - earlier <= 10
    ]
    sample_period = median(differences) if differences else 1.0
    return times[-1] + sample_period


def _boundary_source_note(source: str) -> str:
    return {
        "actual_laps": "Intervals use Garmin's executed lap boundaries.",
        "actual_trace": (
            "Garmin supplied no useful step laps; intervals use the executed "
            "target-power transitions in the ride trace."
        ),
        "planned_durations": (
            "No reliable executed boundaries were available; intervals use the "
            "planned-duration clock, so a boundary can be out by several seconds — "
            "treat a short effort's placement as approximate."
        ),
        "none": "No planned interval structure was available.",
    }[source]


def _normalized_power(powers: Sequence[float]) -> float | None:
    """NP over the interval: a 30 s rolling mean, 4th-power mean, 4th root. Falls back
    to the plain mean when the interval is shorter than the rolling window."""
    if not powers:
        return None
    if len(powers) < NP_ROLLING_WINDOW_SEC:
        return round(sum(powers) / len(powers), 1)

    rolling: list[float] = []
    window: deque[float] = deque()
    running = 0.0
    for power in powers:
        window.append(power)
        running += power
        if len(window) > NP_ROLLING_WINDOW_SEC:
            running -= window.popleft()
        if len(window) == NP_ROLLING_WINDOW_SEC:
            rolling.append(running / NP_ROLLING_WINDOW_SEC)
    if not rolling:
        return round(sum(powers) / len(powers), 1)
    fourth_power_mean = sum(value**4 for value in rolling) / len(rolling)
    return round(float(fourth_power_mean**0.25), 1)


def _adherence(
    pct_ftp: float | None,
    target_low: int,
    target_high: int,
    *,
    peak_graded: bool = False,
) -> str | None:
    """Grade a work interval's %FTP against its own target band (with slack).

    A peak-graded short effort has no "over": beating a sprint target is the point of
    a sprint, not a pacing error, and the only honest question is whether the effort
    reached what it was set.
    """
    if pct_ftp is None:
        return None
    if pct_ftp < target_low - ADHERENCE_TOLERANCE_PCT:
        return "under"
    if peak_graded:
        return "on"
    if pct_ftp > target_high + ADHERENCE_TOLERANCE_PCT:
        return "over"
    return "on"


def _fade(window: Sequence[TraceSample], duration_sec: float) -> bool | None:
    """Power fade: does the last third average meaningfully below the first third?"""
    if duration_sec < FADE_MIN_DURATION_SEC:
        return None
    first, last = _first_last_third(window, "power_watts")
    if first is None or last is None or first <= 0:
        return None
    return (first - last) / first > FADE_DROP_FRACTION


def _hr_drift_pct(window: Sequence[TraceSample], duration_sec: float) -> float | None:
    """Cardiac drift/decoupling: last-third vs first-third average HR, as a percent."""
    if duration_sec < FADE_MIN_DURATION_SEC:
        return None
    first, last = _first_last_third(window, "heart_rate_bpm")
    if first is None or last is None or first <= 0:
        return None
    return round((last - first) / first * 100, 1)


def _first_last_third(
    window: Sequence[TraceSample], attribute: str
) -> tuple[float | None, float | None]:
    values = [
        float(value) for sample in window if (value := getattr(sample, attribute)) is not None
    ]
    third = len(values) // 3
    if third == 0:
        return None, None
    return sum(values[:third]) / third, sum(values[-third:]) / third


def _work_interval_phrase(interval: Mapping[str, Any]) -> str:
    duration_sec = int(interval["durationSec"])
    length = f"{duration_sec} s" if duration_sec < 60 else f"{round(duration_sec / 60)} min"
    target = _target_phrase(interval["targetPctFtpLow"], interval["targetPctFtpHigh"])
    pct_ftp = interval.get("pctFtp")
    held = f"{pct_ftp}% FTP" if pct_ftp is not None else "n/a"
    np_watts = interval.get("normalizedPowerWatts")
    np_phrase = f" ({int(np_watts)} W NP)" if np_watts else ""
    peak_watts = interval.get("maxPowerWatts")
    peak_pct = interval.get("peakPctFtp")
    peak_phrase = (
        f", peak {int(peak_watts)} W ({peak_pct}% FTP)"
        if peak_watts is not None and peak_pct is not None
        else ""
    )
    withheld = interval.get("gradeWithheldReason")
    adherence = (
        f"grade withheld ({withheld})" if withheld else (interval.get("adherence") or "ungraded")
    )
    fade = "fade" if interval.get("fade") else "no fade"
    return (
        f"{length} {interval['label']}: target {target}, "
        f"held {held}{np_phrase}{peak_phrase}, {adherence}, {fade}"
    )


def _target_phrase(low: int, high: int) -> str:
    return f"{low}% FTP" if low == high else f"{low}–{high}% FTP"


def _sample_time(sample: TraceSample, clock_source: str = "elapsed_sec") -> float:
    """Seconds for a sample on the chosen clock, falling back to its index at ~1 Hz."""
    value = getattr(sample, clock_source, None)
    if value is None and clock_source != "elapsed_sec":
        value = sample.elapsed_sec
    if value is not None:
        return float(value)
    return float(sample.sample_index)


def _step_duration(step: Mapping[str, Any]) -> float:
    value = step.get("durationSec")
    return float(value) if isinstance(value, int | float) else 0.0


def _ramp_is_rising(step: Mapping[str, Any]) -> bool:
    return _int(step, "powerEndPct") > _int(step, "powerStartPct")


def _target_mid(step: Mapping[str, Any]) -> float:
    return (_int(step, "powerStartPct") + _int(step, "powerEndPct")) / 2


def _int(step: Mapping[str, Any], key: str) -> int:
    value = step.get(key)
    return int(value) if isinstance(value, int | float) else 0
