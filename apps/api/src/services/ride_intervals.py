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

See docs/designs/interval-resolved-ride-analysis.md.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
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

# The whole-ride average, once intervals exist, is context only — never the verdict.
WHOLE_RIDE_CONTEXT_NOTE = (
    "Whole-ride average power is context only. On a structured session it sits "
    "below the work target because the warm-up, recovery valleys, and cool-down "
    "pull it down. It is not the execution verdict and never indicates "
    "under-performance — grade execution on the work intervals below."
)


class TraceSample(Protocol):
    """The per-second trace fields segmentation reads (a subset of ActivityTimeSeries)."""

    elapsed_sec: float | None
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
) -> list[dict[str, Any]]:
    """Slice the per-second trace on the planned IR's interval boundaries.

    Walks the IR steps in order, slices the trace into each step's
    ``[t_start, t_end)`` elapsed-time window (cumulative ``durationSec``), and emits
    one interval object per step. Work intervals carry an ``adherence`` grade and a
    ``fade`` flag against their own target; warm-up/recovery/cool-down power is
    described, never graded. Returns ``[]`` when there is no plan or no trace so the
    caller degrades to the whole-ride read.
    """
    steps = ir.get("steps") if ir else None
    if not isinstance(steps, list) or not steps or not timeseries:
        return []

    roles = classify_roles(steps)
    timed = sorted(((_sample_time(s), s) for s in timeseries), key=lambda pair: pair[0])

    intervals: list[dict[str, Any]] = []
    cursor = 0.0
    for index, (step, role) in enumerate(zip(steps, roles, strict=True)):
        duration = _step_duration(step)
        t_start, t_end = cursor, cursor + duration
        cursor = t_end
        window = [sample for time, sample in timed if t_start <= time < t_end]
        intervals.append(_build_interval(index, step, role, duration, window, ftp_watts))
    return intervals


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
        }
        if has_plan:
            result["wholeRideContextNote"] = WHOLE_RIDE_CONTEXT_NOTE
        return result

    on = sum(1 for item in work if item.get("adherence") == "on")
    over = sum(1 for item in work if item.get("adherence") == "over")
    under = sum(1 for item in work if item.get("adherence") == "under")
    faded = sum(1 for item in work if item.get("fade") is True)

    summary = (
        f"{len(work)} work interval(s): {on} on target, {over} over, {under} under; "
        f"{f'fade in {faded} block(s)' if faded else 'no fade'}."
    )
    return {
        "hasPlan": True,
        "workIntervalCount": len(work),
        "onTargetCount": on,
        "overCount": over,
        "underCount": under,
        "fadedCount": faded,
        "workIntervals": [_work_interval_phrase(item) for item in work],
        "summary": summary,
        "wholeRideAvgPowerWatts": whole_ride_avg_power_watts,
        "wholeRideContextNote": WHOLE_RIDE_CONTEXT_NOTE,
    }


def _build_interval(
    index: int,
    step: Mapping[str, Any],
    role: str,
    duration_sec: float,
    window: Sequence[TraceSample],
    ftp_watts: int | None,
) -> dict[str, Any]:
    powers = [float(s.power_watts) for s in window if s.power_watts is not None]
    hrs = [float(s.heart_rate_bpm) for s in window if s.heart_rate_bpm is not None]
    cadences = [float(s.cadence_rpm) for s in window if s.cadence_rpm is not None]

    avg_power = round(sum(powers) / len(powers), 1) if powers else None
    pct_ftp = round(avg_power / ftp_watts * 100, 1) if avg_power is not None and ftp_watts else None
    target_low = min(_int(step, "powerStartPct"), _int(step, "powerEndPct"))
    target_high = max(_int(step, "powerStartPct"), _int(step, "powerEndPct"))
    is_work = role == "work"

    return {
        "index": index,
        "label": str(step.get("label") or f"Step {index + 1}"),
        "role": role,
        "durationSec": int(round(duration_sec)),
        "sampleCount": len(window),
        "avgPowerWatts": avg_power,
        "normalizedPowerWatts": _normalized_power(powers),
        "pctFtp": pct_ftp,
        "powerZone": power_zone(avg_power, ftp_watts),
        "avgHeartRateBpm": round(sum(hrs) / len(hrs), 1) if hrs else None,
        "maxHeartRateBpm": round(max(hrs), 1) if hrs else None,
        "avgCadenceRpm": round(sum(cadences) / len(cadences), 1) if cadences else None,
        "targetPctFtpLow": target_low,
        "targetPctFtpHigh": target_high,
        "cadenceTargetRpm": _int(step, "cadenceRpm") if step.get("cadenceRpm") else None,
        # Graded only for work intervals; described (None grade) for everything else.
        "adherence": _adherence(pct_ftp, target_low, target_high) if is_work else None,
        "fade": _fade(window, duration_sec) if is_work else None,
        "hrDriftPct": _hr_drift_pct(window, duration_sec) if is_work else None,
    }


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


def _adherence(pct_ftp: float | None, target_low: int, target_high: int) -> str | None:
    """Grade a work interval's held %FTP against its own target band (with slack)."""
    if pct_ftp is None:
        return None
    if pct_ftp < target_low - ADHERENCE_TOLERANCE_PCT:
        return "under"
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
    minutes = round(int(interval["durationSec"]) / 60)
    target = _target_phrase(interval["targetPctFtpLow"], interval["targetPctFtpHigh"])
    pct_ftp = interval.get("pctFtp")
    held = f"{pct_ftp}% FTP" if pct_ftp is not None else "n/a"
    np_watts = interval.get("normalizedPowerWatts")
    np_phrase = f" ({int(np_watts)} W NP)" if np_watts else ""
    adherence = interval.get("adherence") or "ungraded"
    fade = "fade" if interval.get("fade") else "no fade"
    return (
        f"{minutes} min {interval['label']}: target {target}, "
        f"held {held}{np_phrase}, {adherence}, {fade}"
    )


def _target_phrase(low: int, high: int) -> str:
    return f"{low}% FTP" if low == high else f"{low}–{high}% FTP"


def _sample_time(sample: TraceSample) -> float:
    """Elapsed seconds for a sample, falling back to its index at ~1 Hz."""
    if sample.elapsed_sec is not None:
        return float(sample.elapsed_sec)
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
