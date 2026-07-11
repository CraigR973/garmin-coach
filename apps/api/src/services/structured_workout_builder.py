from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from fastapi import HTTPException, status

from src.services.workout_delivery import expand_structured_steps

# Soft band (Batch 77): the coaching-sensible range. Outside it on Mark's manual
# authoring path is a *warning*, not a block (Batch 88, Decision #161).
MIN_SOFT_POWER_PCT = 45
MAX_SOFT_POWER_PCT = 150
# Absolute sanity floor kept hard even under soft warnings (Batch 88 decision): a
# power the delivery rail (intervals.icu / Zwift / Garmin) cannot represent, or a
# non-positive duration, is rejected outright — the soft warnings cover aggressive
# coaching choices, not physically undeliverable garbage.
ABS_MIN_POWER_PCT = 1
ABS_MAX_POWER_PCT = 300
MAX_TOTAL_DURATION_MIN = 480

DeliveryTarget = Literal["indoor", "outdoor"]
SegmentKind = Literal["ramp", "steady", "interval"]


@dataclass(frozen=True)
class WorkoutSegment:
    """One authored segment of a free-form ride (Batch 88).

    A flat shape whose relevant fields depend on ``kind``; the API layer validates
    per-kind before this is built, and ``build_freeform_bike_workout`` hard-checks
    the fields it needs. Segments map 1:1 onto the existing raw ``steps`` grammar
    (``ramp`` / ``steady`` / interval ``pattern``) that ``expand_structured_steps``
    already consumes, so no delivery-path change is needed.
    """

    kind: SegmentKind
    # ramp + steady
    duration_min: int | None = None
    # ramp
    start_ftp_pct: int | None = None
    end_ftp_pct: int | None = None
    # steady
    ftp_pct: int | None = None
    # interval
    repeats: int | None = None
    work_min: int | None = None
    work_ftp_pct: int | None = None
    recover_min: int | None = None
    recover_ftp_pct: int | None = None


@dataclass(frozen=True)
class FreeformBikeWorkoutSpec:
    delivery: DeliveryTarget
    segments: tuple[WorkoutSegment, ...]


@dataclass(frozen=True)
class WorkoutWarning:
    """A non-blocking advisory returned on a successful save (Batch 88).

    Structured (``code`` + ``detail``) so the data is durable and the UI copy stays
    swappable, following the Batch 86 "structured data durable, layout swappable"
    pattern.
    """

    code: str
    detail: str


@dataclass(frozen=True)
class BuiltCustomBikeWorkout:
    title: str
    workout_type: str
    planned_duration_min: int
    intensity_target: str
    structured_workout: dict[str, Any]
    delivery: DeliveryTarget


def build_freeform_bike_workout(
    spec: FreeformBikeWorkoutSpec,
    *,
    title: str = "Custom ride",
    soft_gates: bool = False,
) -> tuple[BuiltCustomBikeWorkout, list[WorkoutWarning]]:
    """Author an arbitrary ordered-segment bike workout into the ``steps`` grammar.

    Emits each segment through the exact per-kind step shapes the Batch 77 builder
    used inline, so any count/order authors the existing structured-workout grammar
    and the downstream contract (``structured_workout`` shape, ``totalDurationMin``,
    workout-type classification, delivery IR) is unchanged.

    ``soft_gates`` scopes the Batch 88 reversal (Decision #161): on Mark's explicit
    manual authoring path (``soft_gates=True``) the coaching gates — power outside
    the 45-150% band and a missing warm-up / cool-down ramp — become non-blocking
    :class:`WorkoutWarning` entries instead of 422s, while the coach/automated
    authoring path (the default, ``soft_gates=False``) keeps them **hard**. The
    absolute sanity floor (power ``1-300`` %FTP, positive durations, total under
    ``MAX_TOTAL_DURATION_MIN``) stays hard in both modes.
    """
    if spec.delivery not in {"indoor", "outdoor"}:
        raise _invalid("Choose indoor or outdoor.")
    if not spec.segments:
        raise _invalid("Add at least one workout segment.")

    steps: list[dict[str, Any]] = []
    powers: list[int] = []
    total = len(spec.segments)
    for index, segment in enumerate(spec.segments):
        step, step_powers = _segment_to_step(
            segment, is_first=index == 0, is_last=index == total - 1
        )
        steps.append(step)
        powers.extend(step_powers)

    warnings = _gate_warnings(spec.segments, powers, soft_gates=soft_gates)

    structured: dict[str, Any] = {
        "format": "bike",
        "delivery": spec.delivery,
        "source": "structured_builder",
        "steps": steps,
    }
    expanded = _expand_or_422(structured)
    total_duration_min = round(sum(int(step["durationSec"]) for step in expanded) / 60)
    if total_duration_min > MAX_TOTAL_DURATION_MIN:
        raise _invalid(
            f"Total workout duration {total_duration_min} min exceeds the "
            f"{MAX_TOTAL_DURATION_MIN} min limit."
        )
    max_power = max(max(int(step["powerStartPct"]), int(step["powerEndPct"])) for step in expanded)
    structured["totalDurationMin"] = total_duration_min

    built = BuiltCustomBikeWorkout(
        title=title,
        workout_type=_workout_type_for_power(max_power),
        planned_duration_min=total_duration_min,
        intensity_target=_intensity_target_for_power(max_power),
        structured_workout=structured,
        delivery=spec.delivery,
    )
    return built, warnings


def is_indoor_bike_workout(structured: dict[str, Any] | None) -> bool:
    if not isinstance(structured, dict):
        return False
    return structured.get("format") == "bike" and structured.get("delivery", "indoor") != "outdoor"


def is_outdoor_bike_workout(structured: dict[str, Any] | None) -> bool:
    if not isinstance(structured, dict):
        return False
    return structured.get("format") == "bike" and structured.get("delivery") == "outdoor"


def _segment_to_step(
    segment: WorkoutSegment, *, is_first: bool, is_last: bool
) -> tuple[dict[str, Any], list[int]]:
    """Map one authored segment onto a raw ``steps`` entry + its power values.

    Leading/trailing ramps are labelled "Warm-up ramp" / "Cool-down ramp" so the
    delivery expander's label-driven phase detection tags them ``warmup``/``cooldown``
    (and the edit round-trip recognises them); a mid-workout ramp stays a plain ramp.
    """
    if segment.kind == "ramp":
        duration = _required_positive(segment.duration_min, "Ramp duration")
        start = _required_power(segment.start_ftp_pct, "Ramp start %FTP")
        end = _required_power(segment.end_ftp_pct, "Ramp end %FTP")
        if is_first:
            label = "Warm-up ramp"
        elif is_last:
            label = "Cool-down ramp"
        else:
            label = "Ramp"
        return {"label": label, "minutes": duration, "ramp": [start, end]}, [start, end]

    if segment.kind == "steady":
        duration = _required_positive(segment.duration_min, "Steady duration")
        pct = _required_power(segment.ftp_pct, "Steady %FTP")
        return {"label": "Steady", "minutes": duration, "target": f"{pct}%"}, [pct]

    if segment.kind == "interval":
        repeats = _required_positive(segment.repeats, "Repeats")
        work = _required_positive(segment.work_min, "Interval work minutes")
        recover = _required_positive(segment.recover_min, "Interval recovery minutes")
        work_pct = _required_power(segment.work_ftp_pct, "Interval work %FTP")
        recover_pct = _required_power(segment.recover_ftp_pct, "Interval recovery %FTP")
        step = {
            "label": "Intervals",
            "target": f"{work_pct}%",
            "pattern": f"{repeats} x {work}min / {recover}min @{recover_pct}%",
        }
        return step, [work_pct, recover_pct]

    raise _invalid(f"Unknown segment kind {segment.kind!r}.")


def _gate_warnings(
    segments: tuple[WorkoutSegment, ...], powers: list[int], *, soft_gates: bool
) -> list[WorkoutWarning]:
    """Apply the two authoring gates: warn (manual) or raise (coach/automated)."""
    warnings: list[WorkoutWarning] = []

    out_of_band = sorted({p for p in powers if p < MIN_SOFT_POWER_PCT or p > MAX_SOFT_POWER_PCT})
    if out_of_band:
        if len(out_of_band) == 1:
            detail = (
                f"Power target {out_of_band[0]}% FTP is outside the usual "
                f"{MIN_SOFT_POWER_PCT}–{MAX_SOFT_POWER_PCT}% band."
            )
        else:
            joined = ", ".join(f"{p}%" for p in out_of_band)
            detail = (
                f"Power targets {joined} FTP are outside the usual "
                f"{MIN_SOFT_POWER_PCT}–{MAX_SOFT_POWER_PCT}% band."
            )
        if soft_gates:
            warnings.append(WorkoutWarning("power_out_of_band", detail))
        else:
            raise _invalid(detail)

    ramp_detail = _missing_ramp_detail(segments)
    if ramp_detail is not None:
        if soft_gates:
            warnings.append(WorkoutWarning("missing_ramp", ramp_detail))
        else:
            raise _invalid(ramp_detail)

    return warnings


def _missing_ramp_detail(segments: tuple[WorkoutSegment, ...]) -> str | None:
    """Describe a missing warm-up and/or cool-down ramp, or None when both present."""
    if not segments:
        return None
    opens_with_ramp = segments[0].kind == "ramp"
    closes_with_ramp = segments[-1].kind == "ramp"
    if opens_with_ramp and closes_with_ramp:
        return None
    if not opens_with_ramp and not closes_with_ramp:
        return "No warm-up or cool-down ramp — consider easing in and out."
    if not opens_with_ramp:
        return "No warm-up ramp — consider easing in before the work."
    return "No cool-down ramp — consider easing out at the end."


def _expand_or_422(structured: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        return expand_structured_steps(structured, None)
    except HTTPException:
        raise
    except Exception as exc:
        raise _invalid(str(exc)) from exc


def _required_positive(value: int | None, label: str) -> int:
    if value is None or value <= 0:
        raise _invalid(f"{label} must be greater than 0.")
    return value


def _required_power(value: int | None, label: str) -> int:
    """Present + within the absolute deliverable floor. The soft 45-150 band is a
    warning handled by ``_gate_warnings``; here we only reject the undeliverable."""
    if value is None:
        raise _invalid(f"{label} is required.")
    if value < ABS_MIN_POWER_PCT or value > ABS_MAX_POWER_PCT:
        raise _invalid(f"{label} must be between {ABS_MIN_POWER_PCT} and {ABS_MAX_POWER_PCT}% FTP.")
    return value


def _workout_type_for_power(max_power: int) -> str:
    if max_power >= 105:
        return "bike_vo2"
    if max_power >= 88:
        return "bike_sweet_spot"
    if max_power >= 76:
        return "bike_tempo"
    if max_power <= 55:
        return "bike_recovery"
    return "bike_endurance"


def _intensity_target_for_power(max_power: int) -> str:
    if max_power >= 105:
        return f"VO2 efforts up to {max_power}% FTP"
    if max_power >= 88:
        return f"Sweet Spot up to {max_power}% FTP"
    if max_power >= 76:
        return f"Tempo up to {max_power}% FTP"
    if max_power <= 55:
        return f"Recovery up to {max_power}% FTP"
    return f"Endurance up to {max_power}% FTP"


def _invalid(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)
