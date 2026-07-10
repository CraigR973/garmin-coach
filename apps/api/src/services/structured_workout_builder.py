from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from fastapi import HTTPException, status

from src.services.workout_delivery import expand_structured_steps

MIN_CUSTOM_POWER_PCT = 45
MAX_CUSTOM_POWER_PCT = 150
Z2_LEAD_IN_PCT = 55
WARMUP_RAMP_PCT = (45, 75)
COOLDOWN_RAMP_PCT = (75, 45)

DeliveryTarget = Literal["indoor", "outdoor"]


@dataclass(frozen=True)
class CustomBikeWorkoutSpec:
    delivery: DeliveryTarget
    warmup_enabled: bool
    warmup_duration_min: int | None
    z2_lead_in_enabled: bool
    z2_lead_in_duration_min: int | None
    intervals_enabled: bool
    interval_1_duration_min: int | None
    interval_1_ftp_pct: int | None
    interval_2_duration_min: int | None
    interval_2_ftp_pct: int | None
    repeats: int | None
    block_duration_min: int | None
    block_ftp_pct: int | None
    cooldown_enabled: bool
    cooldown_duration_min: int | None


@dataclass(frozen=True)
class BuiltCustomBikeWorkout:
    title: str
    workout_type: str
    planned_duration_min: int
    intensity_target: str
    structured_workout: dict[str, Any]
    delivery: DeliveryTarget


def build_custom_bike_workout(
    spec: CustomBikeWorkoutSpec,
    *,
    title: str = "Custom ride",
) -> BuiltCustomBikeWorkout:
    steps: list[dict[str, Any]] = []

    if spec.delivery not in {"indoor", "outdoor"}:
        raise _invalid("Choose indoor or outdoor.")

    if spec.warmup_enabled:
        duration = _required_positive(spec.warmup_duration_min, "Warm-up duration")
        steps.append({"label": "Warm-up ramp", "minutes": duration, "ramp": list(WARMUP_RAMP_PCT)})

    if spec.z2_lead_in_enabled:
        duration = _required_positive(spec.z2_lead_in_duration_min, "Z2 lead-in duration")
        steps.append({"label": "Z2 lead-in", "minutes": duration, "target": f"{Z2_LEAD_IN_PCT}%"})

    if spec.intervals_enabled:
        int_1_duration = _required_positive(spec.interval_1_duration_min, "Interval 1 duration")
        int_2_duration = _required_positive(spec.interval_2_duration_min, "Interval 2 duration")
        int_1_pct = _required_power(spec.interval_1_ftp_pct, "Interval 1 %FTP")
        int_2_pct = _required_power(spec.interval_2_ftp_pct, "Interval 2 %FTP")
        repeats = _required_positive(spec.repeats, "Number of repeats")
        steps.append(
            {
                "label": "Main intervals",
                "target": f"{int_1_pct}%",
                "pattern": f"{repeats} x {int_1_duration}min / {int_2_duration}min @{int_2_pct}%",
            }
        )
    else:
        block_duration = _required_positive(spec.block_duration_min, "Block duration")
        block_pct = _required_power(spec.block_ftp_pct, "Block %FTP")
        steps.append({"label": "Main block", "minutes": block_duration, "target": f"{block_pct}%"})

    if spec.cooldown_enabled:
        duration = _required_positive(spec.cooldown_duration_min, "Cool-down duration")
        steps.append(
            {"label": "Cool-down ramp", "minutes": duration, "ramp": list(COOLDOWN_RAMP_PCT)}
        )

    if not steps:
        raise _invalid("Add at least one workout step.")

    structured: dict[str, Any] = {
        "format": "bike",
        "delivery": spec.delivery,
        "source": "structured_builder",
        "steps": steps,
    }
    expanded = _expand_or_422(structured)
    total_duration_min = round(sum(int(step["durationSec"]) for step in expanded) / 60)
    max_power = max(max(int(step["powerStartPct"]), int(step["powerEndPct"])) for step in expanded)
    structured["totalDurationMin"] = total_duration_min

    return BuiltCustomBikeWorkout(
        title=title,
        workout_type=_workout_type_for_power(max_power),
        planned_duration_min=total_duration_min,
        intensity_target=_intensity_target_for_power(max_power),
        structured_workout=structured,
        delivery=spec.delivery,
    )


def is_indoor_bike_workout(structured: dict[str, Any] | None) -> bool:
    if not isinstance(structured, dict):
        return False
    return structured.get("format") == "bike" and structured.get("delivery", "indoor") != "outdoor"


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
    if value is None:
        raise _invalid(f"{label} is required.")
    if value < MIN_CUSTOM_POWER_PCT or value > MAX_CUSTOM_POWER_PCT:
        raise _invalid(
            f"{label} must be between {MIN_CUSTOM_POWER_PCT} and {MAX_CUSTOM_POWER_PCT}."
        )
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
