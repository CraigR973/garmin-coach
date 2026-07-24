"""Pure source mapper and deterministic suggestions for Batch 147's ride editor."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, status

from src.services.workout_delivery import _expand_step

MIN_REPEATS = 1
MAX_REPEATS = 20
MIN_WORK_DURATION_SEC = 30
MAX_WORK_DURATION_SEC = 7200
MIN_REST_DURATION_SEC = 0
MAX_REST_DURATION_SEC = 3600
MIN_POWER_PCT = 40
MAX_POWER_PCT = 150
MIN_CADENCE_RPM = 40
MAX_CADENCE_RPM = 130


@dataclass(frozen=True)
class IntervalLeg:
    duration_sec: int
    power_pct: int
    cadence_rpm: int | None


@dataclass(frozen=True)
class EditableIntervalBlock:
    repeat: int
    work: IntervalLeg
    rest: IntervalLeg


@dataclass(frozen=True)
class FixedWorkoutStep:
    index: int
    label: str
    role: str
    raw_step: dict[str, Any]


@dataclass(frozen=True)
class IntervalEditorSnapshot:
    primary_step_index: int
    current: EditableIntervalBlock
    scaled: EditableIntervalBlock
    sweet_spot: EditableIntervalBlock
    zone_two: EditableIntervalBlock
    fixed_steps: tuple[FixedWorkoutStep, ...]


def interval_editor_snapshot(
    structured: dict[str, Any] | None,
    intensity_target: str | None,
) -> IntervalEditorSnapshot:
    """Map one planned workout source to Mark's Current/Change-to table.

    V1 edits the primary block only. Current plans contain one interval block;
    warm-up, cool-down, and primer steps remain read-only context and are copied
    without alteration when the edit is applied.
    """
    structured = structured or {}
    raw_steps = structured.get("steps")
    if structured.get("format") != "bike" or not isinstance(raw_steps, list):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="This session has no editable bike interval block",
        )

    primary_index = _primary_step_index(raw_steps, intensity_target)
    if primary_index is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="This session has no editable bike interval block",
        )
    raw_primary = raw_steps[primary_index]
    if not isinstance(raw_primary, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The editable interval block is malformed",
        )
    current = _block_from_step(raw_primary, intensity_target)
    fixed_steps = tuple(
        FixedWorkoutStep(
            index=index,
            label=str(raw.get("label") or f"Step {index + 1}"),
            role=_step_role(raw),
            raw_step=deepcopy(raw),
        )
        for index, raw in enumerate(raw_steps)
        if index != primary_index and isinstance(raw, dict)
    )
    return IntervalEditorSnapshot(
        primary_step_index=primary_index,
        current=current,
        scaled=scale_block(current),
        sweet_spot=sweet_spot_block(current),
        zone_two=zone_two_block(current),
        fixed_steps=fixed_steps,
    )


def apply_interval_block(
    structured: dict[str, Any],
    intensity_target: str | None,
    block: EditableIntervalBlock,
) -> dict[str, Any]:
    """Write the edited primary block while preserving every other source step."""
    validate_interval_block(block)
    snapshot = interval_editor_snapshot(structured, intensity_target)
    updated = deepcopy(structured)
    raw_steps = updated.get("steps")
    assert isinstance(raw_steps, list)  # established by interval_editor_snapshot
    original = raw_steps[snapshot.primary_step_index]
    label = str(original.get("label") or "Intervals") if isinstance(original, dict) else "Intervals"
    raw_steps[snapshot.primary_step_index] = {
        "label": label,
        "block": block_to_source(block),
    }
    return updated


def block_to_source(block: EditableIntervalBlock) -> dict[str, Any]:
    validate_interval_block(block)
    return {
        "repeat": block.repeat,
        "work": _leg_to_source(block.work),
        "rest": _leg_to_source(block.rest),
    }


def scale_block(block: EditableIntervalBlock) -> EditableIntervalBlock:
    """The deterministic, cautious scale preset replacing the old 75%/90% dials."""
    return EditableIntervalBlock(
        repeat=block.repeat,
        work=IntervalLeg(
            duration_sec=max(MIN_WORK_DURATION_SEC, round(block.work.duration_sec * 0.75)),
            power_pct=max(MIN_POWER_PCT, round(block.work.power_pct * 0.9)),
            cadence_rpm=block.work.cadence_rpm,
        ),
        rest=IntervalLeg(
            duration_sec=round(block.rest.duration_sec * 0.75),
            power_pct=max(MIN_POWER_PCT, round(block.rest.power_pct * 0.9)),
            cadence_rpm=block.rest.cadence_rpm,
        ),
    )


def sweet_spot_block(block: EditableIntervalBlock) -> EditableIntervalBlock:
    return EditableIntervalBlock(
        repeat=3,
        work=IntervalLeg(duration_sec=600, power_pct=90, cadence_rpm=block.work.cadence_rpm or 85),
        rest=IntervalLeg(duration_sec=300, power_pct=55, cadence_rpm=block.rest.cadence_rpm or 75),
    )


def zone_two_block(block: EditableIntervalBlock) -> EditableIntervalBlock:
    return EditableIntervalBlock(
        repeat=1,
        work=IntervalLeg(duration_sec=2700, power_pct=65, cadence_rpm=block.work.cadence_rpm or 85),
        rest=IntervalLeg(duration_sec=0, power_pct=55, cadence_rpm=None),
    )


def validate_interval_block(block: EditableIntervalBlock) -> None:
    _bounded(block.repeat, "repeat", MIN_REPEATS, MAX_REPEATS)
    _validate_leg(
        block.work,
        "work",
        minimum_duration=MIN_WORK_DURATION_SEC,
        maximum_duration=MAX_WORK_DURATION_SEC,
    )
    _validate_leg(
        block.rest,
        "rest",
        minimum_duration=MIN_REST_DURATION_SEC,
        maximum_duration=MAX_REST_DURATION_SEC,
    )


def block_workout_type(block: EditableIntervalBlock) -> str:
    if block.work.power_pct >= 106:
        return "bike_vo2"
    if block.work.power_pct >= 85:
        return "bike_sweet_spot"
    return "bike_endurance"


def _block_from_step(
    raw_step: dict[str, Any],
    intensity_target: str | None,
) -> EditableIntervalBlock:
    raw_block = raw_step.get("block")
    if isinstance(raw_block, dict):
        return _block_from_source(raw_block)

    expanded = _expand_step(raw_step, intensity_target)
    if not expanded:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The editable interval block did not produce any steps",
        )
    work_steps = [step for step in expanded if "recovery" not in str(step.get("label", "")).lower()]
    rest_steps = [step for step in expanded if "recovery" in str(step.get("label", "")).lower()]
    work = work_steps[0]
    rest = rest_steps[0] if rest_steps else None
    block = EditableIntervalBlock(
        repeat=max(1, len(work_steps)),
        work=_leg_from_ir(work),
        rest=(
            _leg_from_ir(rest)
            if rest is not None
            else IntervalLeg(duration_sec=0, power_pct=55, cadence_rpm=None)
        ),
    )
    validate_interval_block(block)
    return block


def _block_from_source(raw_block: dict[str, Any]) -> EditableIntervalBlock:
    work = raw_block.get("work")
    rest = raw_block.get("rest") or {"durationSec": 0, "powerPct": 55}
    if not isinstance(work, dict) or not isinstance(rest, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The editable interval block is malformed",
        )
    block = EditableIntervalBlock(
        repeat=_as_int(raw_block.get("repeat")),
        work=_leg_from_source(work),
        rest=_leg_from_source(rest),
    )
    validate_interval_block(block)
    return block


def _leg_from_ir(step: dict[str, Any]) -> IntervalLeg:
    return IntervalLeg(
        duration_sec=_as_int(step.get("durationSec")),
        power_pct=_as_int(step.get("powerEndPct")),
        cadence_rpm=_optional_int(step.get("cadenceRpm")),
    )


def _leg_from_source(raw: dict[str, Any]) -> IntervalLeg:
    return IntervalLeg(
        duration_sec=_as_int(raw.get("durationSec")),
        power_pct=_as_int(raw.get("powerPct")),
        cadence_rpm=_optional_int(raw.get("cadenceRpm")),
    )


def _leg_to_source(leg: IntervalLeg) -> dict[str, Any]:
    result: dict[str, Any] = {
        "durationSec": leg.duration_sec,
        "powerPct": leg.power_pct,
    }
    if leg.cadence_rpm is not None:
        result["cadenceRpm"] = leg.cadence_rpm
    return result


def _primary_step_index(raw_steps: list[Any], intensity_target: str | None) -> int | None:
    for index, raw in enumerate(raw_steps):
        if isinstance(raw, dict) and isinstance(raw.get("block"), dict):
            return index

    candidates: list[tuple[int, int]] = []
    for index, raw in enumerate(raw_steps):
        if isinstance(raw, dict) and isinstance(raw.get("pattern"), str) and "/" in raw["pattern"]:
            try:
                duration = sum(
                    int(step["durationSec"]) for step in _expand_step(raw, intensity_target)
                )
            except (HTTPException, KeyError, TypeError, ValueError):
                continue
            candidates.append((duration, index))
    if candidates:
        return max(candidates)[1]

    candidates = []
    for index, raw in enumerate(raw_steps):
        if not isinstance(raw, dict) or "minutes" not in raw or "ramp" in raw:
            continue
        if _step_role(raw) != "primer":
            continue
        try:
            duration = round(float(raw["minutes"]) * 60)
        except (TypeError, ValueError):
            continue
        candidates.append((duration, index))
    return max(candidates)[1] if candidates else None


def _step_role(raw: dict[str, Any]) -> str:
    label = str(raw.get("label") or "").lower()
    if "warm" in label or "settle" in label:
        return "warmup"
    if "cool" in label:
        return "cooldown"
    return "primer"


def _validate_leg(
    leg: IntervalLeg,
    name: str,
    *,
    minimum_duration: int,
    maximum_duration: int,
) -> None:
    _bounded(leg.duration_sec, f"{name} duration", minimum_duration, maximum_duration)
    _bounded(leg.power_pct, f"{name} power", MIN_POWER_PCT, MAX_POWER_PCT)
    if leg.cadence_rpm is not None:
        _bounded(leg.cadence_rpm, f"{name} cadence", MIN_CADENCE_RPM, MAX_CADENCE_RPM)


def _bounded(value: int, field: str, minimum: int, maximum: int) -> None:
    if isinstance(value, bool) or value < minimum or value > maximum:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field} must be between {minimum} and {maximum}",
        )


def _as_int(value: Any) -> int:
    if isinstance(value, bool):
        return -1
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


def _optional_int(value: Any) -> int | None:
    return None if value is None else _as_int(value)
