"""Build Garmin Connect's structured-workout JSON from the Batch 67 IR.

Batch 78 (Decision #151): an outdoor ride is delivered to Garmin by uploading a
Garmin *cycling workout* — a different payload from the intervals.icu calendar
event and the ``.ZWO`` file, but authored from the same expanded IR that
``build_structured_workout_ir`` produces. Pure and DB-free, mirroring
``build_zwo_xml`` / ``build_intervals_payload`` in ``workout_delivery.py`` so it
is trivially unit-testable without a live Garmin session.

The numeric type ids below come from Garmin's ``/workout-service/workout/types``
and are mirrored in ``garminconnect.workout`` (``SportType`` / ``StepType`` /
``ConditionType`` / ``TargetType``). They are inlined as named constants so this
module stays a pure function with no import-time dependency on garminconnect.
"""

from __future__ import annotations

from typing import Any

# Sport / step / condition / target ids (Garmin workout-service types).
SPORT_TYPE_CYCLING = {"sportTypeId": 2, "sportTypeKey": "cycling", "displayOrder": 2}

_STEP_TYPES = {
    "warmup": {"stepTypeId": 1, "stepTypeKey": "warmup", "displayOrder": 1},
    "cooldown": {"stepTypeId": 2, "stepTypeKey": "cooldown", "displayOrder": 2},
    "interval": {"stepTypeId": 3, "stepTypeKey": "interval", "displayOrder": 3},
    "recovery": {"stepTypeId": 4, "stepTypeKey": "recovery", "displayOrder": 4},
}
_END_CONDITION_TIME = {
    "conditionTypeId": 2,
    "conditionTypeKey": "time",
    "displayOrder": 2,
    "displayable": True,
}
_TARGET_POWER_ZONE = {
    "workoutTargetTypeId": 2,
    "workoutTargetTypeKey": "power.zone",
    "displayOrder": 2,
}

# A steady step has one power target; Garmin wants a range, so widen it to a tight
# band around the target watts (±POWER_BAND_PCT of FTP, at least POWER_BAND_MIN_WATTS).
POWER_BAND_PCT = 2.5
POWER_BAND_MIN_WATTS = 5
_MAX_NAME_LEN = 80


def build_garmin_workout(ir: dict[str, Any], *, ftp_watts: int | None = None) -> dict[str, Any]:
    """Map an expanded structured-workout IR to a Garmin cycling-workout payload.

    Steps are emitted flat (the IR is already expanded — ``cadenceCriticalExpanded``),
    each a time-bounded power-zone target in absolute watts derived from FTP. A ramp
    step becomes a low→high target range; a steady step becomes a tight band.
    """
    ftp = int(ftp_watts if ftp_watts is not None else ir.get("ftpWatts") or 0)
    if ftp <= 0:
        raise ValueError("Garmin workout export needs a positive FTP")

    raw_steps = ir.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ValueError("Structured workout has no steps to export to Garmin")

    steps: list[dict[str, Any]] = []
    for order, raw_step in enumerate(raw_steps, start=1):
        if not isinstance(raw_step, dict):
            continue
        steps.append(_garmin_step(raw_step, order, ftp))
    if not steps:
        raise ValueError("Structured workout did not produce deliverable Garmin steps")

    name = str(ir.get("name") or "CheckMark ride")[:_MAX_NAME_LEN]
    total = int(ir.get("totalDurationSec") or sum(int(s["endConditionValue"]) for s in steps))
    return {
        "workoutName": name,
        "description": "CheckMark outdoor ride",
        "sportType": dict(SPORT_TYPE_CYCLING),
        "estimatedDurationInSecs": total,
        "workoutSegments": [
            {
                "segmentOrder": 1,
                "sportType": dict(SPORT_TYPE_CYCLING),
                "workoutSteps": steps,
            }
        ],
    }


def _garmin_step(raw_step: dict[str, Any], order: int, ftp: int) -> dict[str, Any]:
    phase = str(raw_step.get("phase") or "interval")
    label = str(raw_step.get("label") or "")
    duration_sec = int(raw_step.get("durationSec") or 0)
    start_pct = float(raw_step.get("powerStartPct") or 0)
    end_pct = float(raw_step.get("powerEndPct") or start_pct)
    low_watts, high_watts = _power_range(start_pct, end_pct, ftp)
    return {
        "type": "ExecutableStepDTO",
        "stepOrder": order,
        "stepType": dict(_STEP_TYPES[_step_type_key(phase, label)]),
        "endCondition": dict(_END_CONDITION_TIME),
        "endConditionValue": float(duration_sec),
        "targetType": dict(_TARGET_POWER_ZONE),
        "targetValueOne": low_watts,
        "targetValueTwo": high_watts,
    }


def _step_type_key(phase: str, label: str) -> str:
    if phase == "warmup":
        return "warmup"
    if phase == "cooldown":
        return "cooldown"
    lowered = label.lower()
    if "recovery" in lowered or "rest" in lowered:
        return "recovery"
    return "interval"


def _power_range(start_pct: float, end_pct: float, ftp: int) -> tuple[int, int]:
    start_watts = round(ftp * start_pct / 100)
    end_watts = round(ftp * end_pct / 100)
    if start_watts != end_watts:
        return (min(start_watts, end_watts), max(start_watts, end_watts))
    band = max(POWER_BAND_MIN_WATTS, round(ftp * POWER_BAND_PCT / 100))
    return (max(0, start_watts - band), start_watts + band)
