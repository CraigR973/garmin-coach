"""Pure source mapper and deterministic suggestions for the interval editor.

Batch 147 introduced one primary-block edit; Batch 263 makes equal sibling
blocks one logical set and derives every prescription-bearing description from
the resulting steps.
"""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, status

from src.services import workout_delivery
from src.services.verdict_scaling import (
    AMBER_DURATION_SCALE,
    adjust_ir_for_verdict,
    ease_amber_power_pct,
    verdict_power_pct,
)

MIN_REPEATS = workout_delivery.INTERVAL_BLOCK_MIN_REPEATS
MAX_REPEATS = workout_delivery.INTERVAL_BLOCK_MAX_REPEATS
MIN_WORK_DURATION_SEC = workout_delivery.INTERVAL_BLOCK_MIN_WORK_DURATION_SEC
MAX_WORK_DURATION_SEC = workout_delivery.INTERVAL_BLOCK_MAX_WORK_DURATION_SEC
MIN_REST_DURATION_SEC = workout_delivery.INTERVAL_BLOCK_MIN_REST_DURATION_SEC
MAX_REST_DURATION_SEC = workout_delivery.INTERVAL_BLOCK_MAX_REST_DURATION_SEC
MIN_POWER_PCT = workout_delivery.INTERVAL_BLOCK_MIN_POWER_PCT
MAX_POWER_PCT = workout_delivery.INTERVAL_BLOCK_MAX_POWER_PCT
MIN_CADENCE_RPM = workout_delivery.INTERVAL_BLOCK_MIN_CADENCE_RPM
MAX_CADENCE_RPM = workout_delivery.INTERVAL_BLOCK_MAX_CADENCE_RPM


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
    editable_step_indices: tuple[int, ...]
    current: EditableIntervalBlock
    scaled: EditableIntervalBlock
    sweet_spot: EditableIntervalBlock
    zone_two: EditableIntervalBlock
    fixed_steps: tuple[FixedWorkoutStep, ...]
    #: Batch 215/243: today's Amber/Red adjustment. Continuous blocks land on the
    #: canonical total; repeated protocols preserve whole work/recovery legs and
    #: may therefore round cautiously to a nearby duration. ``None`` on Green.
    todays_adjustment: EditableIntervalBlock | None = None


def interval_editor_snapshot(
    structured: dict[str, Any] | None,
    intensity_target: str | None,
    *,
    verdict: str | None = None,
    companion_session: bool = False,
) -> IntervalEditorSnapshot:
    """Map one planned workout source to Mark's Current/Change-to table.

    The editor targets the main interval stimulus, not simply the longest source
    step. Equal sibling blocks are one logical set and are edited together;
    distinct blocks remain fixed context. Warm-up, cool-down, and primer steps
    are always copied without alteration when the edit is applied.

    Batch 215: the editor used to open pre-filled with :func:`scale_block` — the
    *Amber* preset — on every morning including a Red one, so on 2026-08-08 the
    brief said 22 minutes and the one-tap editor offered 37. When today's verdict is
    Amber or Red the pre-filled block is now that verdict's own adjustment instead.
    """
    structured = structured or {}
    raw_steps = structured.get("steps")
    if structured.get("format") != "bike" or not isinstance(raw_steps, list):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="This session has no editable bike interval block",
        )

    editable_indices = _editable_step_indices(raw_steps, intensity_target)
    if not editable_indices:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="This session has no editable bike interval block",
        )
    primary_index = editable_indices[0]
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
        if index not in editable_indices and isinstance(raw, dict)
    )
    return IntervalEditorSnapshot(
        primary_step_index=primary_index,
        editable_step_indices=editable_indices,
        current=current,
        scaled=scale_block(current),
        sweet_spot=sweet_spot_block(current),
        zone_two=zone_two_block(current),
        fixed_steps=fixed_steps,
        todays_adjustment=verdict_adjusted_block(
            current,
            structured,
            intensity_target,
            verdict=verdict,
            companion_session=companion_session,
        ),
    )


def verdict_adjusted_block(
    block: EditableIntervalBlock,
    structured: dict[str, Any],
    intensity_target: str | None,
    *,
    verdict: str | None,
    companion_session: bool = False,
) -> EditableIntervalBlock | None:
    """Today's verdict adjustment, expressed as an editable block.

    The editor changes one logical set — including every equal sibling block —
    while warm-up, cool-down, primer and distinct main steps stay read-only. It
    therefore derives the target from the canonical IR transform. A continuous
    block may shorten, but a repeated interval block loses whole repetitions and
    keeps each work/rest leg byte-for-byte on duration. If the transform replaces
    the whole set, the editor offers no dishonest partial equivalent. Returns
    ``None`` on Green, an unknown verdict, or a workout whose fixed steps already
    exceed the adjusted total.
    """
    try:
        expanded = _expand_step_list(structured, intensity_target)
    except HTTPException:
        return None
    base_ir = {"steps": expanded}
    transformed = adjust_ir_for_verdict(
        base_ir,
        verdict,
        companion_session=companion_session,
    )
    adjustment = transformed.get("adjustment")
    if not isinstance(adjustment, dict) or adjustment.get("changed") is not True:
        return None

    total_sec = sum(int(step.get("durationSec", 0)) for step in expanded)
    block_sec = block.repeat * (block.work.duration_sec + block.rest.duration_sec)
    raw_steps = structured.get("steps")
    if not isinstance(raw_steps, list):
        return None
    sibling_count = len(_editable_step_indices(raw_steps, intensity_target))
    if sibling_count == 0:
        return None
    fixed_sec = total_sec - block_sec * sibling_count
    target_block_sec = round(
        (int(transformed.get("totalDurationSec") or 0) - fixed_sec) / sibling_count
    )
    if block_sec <= 0 or target_block_sec < MIN_WORK_DURATION_SEC:
        return None

    pair_sec = block.work.duration_sec + block.rest.duration_sec
    if block.repeat > 1 or block.rest.duration_sec > 0:
        repeat = round(target_block_sec / pair_sec)
        if repeat < 1:
            return None
        repeat = min(block.repeat, repeat)
        work_sec = block.work.duration_sec
        rest_sec = block.rest.duration_sec
    else:
        repeat = 1
        work_sec = target_block_sec
        rest_sec = 0
    return EditableIntervalBlock(
        repeat=repeat,
        work=IntervalLeg(
            duration_sec=min(work_sec, MAX_WORK_DURATION_SEC),
            power_pct=max(
                MIN_POWER_PCT,
                verdict_power_pct(
                    block.work.power_pct,
                    base_ir,
                    verdict,
                    companion_session=companion_session,
                ),
            ),
            cadence_rpm=block.work.cadence_rpm,
        ),
        rest=IntervalLeg(
            duration_sec=min(rest_sec, MAX_REST_DURATION_SEC),
            power_pct=max(
                MIN_POWER_PCT,
                verdict_power_pct(
                    block.rest.power_pct,
                    base_ir,
                    verdict,
                    companion_session=companion_session,
                ),
            ),
            cadence_rpm=block.rest.cadence_rpm,
        ),
    )


def _expand_step_list(
    structured: dict[str, Any], intensity_target: str | None
) -> list[dict[str, Any]]:
    raw_steps = structured.get("steps")
    if not isinstance(raw_steps, list):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="This session has no editable bike interval block",
        )
    expanded: list[dict[str, Any]] = []
    for raw in raw_steps:
        if isinstance(raw, dict):
            expanded.extend(workout_delivery._expand_step(raw, intensity_target))
    return expanded


def apply_interval_block(
    structured: dict[str, Any],
    intensity_target: str | None,
    block: EditableIntervalBlock,
) -> dict[str, Any]:
    """Write one logical interval set and derive its source-facing copy.

    Equal sibling blocks are the same set split around a fixed recovery, so they
    move together. Distinct blocks and all non-interval steps are preserved.
    """
    validate_interval_block(block)
    snapshot = interval_editor_snapshot(structured, intensity_target)
    updated = deepcopy(structured)
    raw_steps = updated.get("steps")
    assert isinstance(raw_steps, list)  # established by interval_editor_snapshot
    for index in snapshot.editable_step_indices:
        original = raw_steps[index]
        original_label = (
            str(original.get("label") or "Intervals") if isinstance(original, dict) else "Intervals"
        )
        raw_steps[index] = {
            "label": _block_label(block, original_label),
            "block": block_to_source(block),
        }
    _normalise_matching_interval_labels(raw_steps, intensity_target, block)
    updated["summary"] = summarize_structured_workout(updated, intensity_target)
    return updated


def normalise_interval_workout_copy(
    structured: dict[str, Any], intensity_target: str | None
) -> dict[str, Any]:
    """Repair labels and summary from existing steps without changing their dose."""
    updated = deepcopy(structured)
    raw_steps = updated.get("steps")
    if not isinstance(raw_steps, list):
        return updated
    _normalise_main_interval_labels(raw_steps, intensity_target)
    updated["summary"] = summarize_structured_workout(updated, intensity_target)
    return updated


def interval_workout_title(
    current_title: str,
    structured: dict[str, Any],
    intensity_target: str | None,
) -> str:
    """Derive a prescription-bearing title from the resulting source steps.

    Generic titles such as ``Z2 + Neuromuscular`` remain generic. A title that
    already embeds interval numbers is rebuilt so the delivered IR name cannot
    carry the pre-edit prescription.
    """
    raw_steps = structured.get("steps")
    if not isinstance(raw_steps, list):
        return current_title
    prefix = _prescription_title_prefix(current_title)
    if prefix is None:
        return current_title
    blocks = [
        candidate.block for candidate in _main_interval_candidates(raw_steps, intensity_target)
    ]
    if not blocks:
        return current_title
    if all(block == blocks[0] for block in blocks[1:]):
        description = _format_block(blocks[0])
        if len(blocks) > 1:
            description = f"{len(blocks)} blocks of {description}"
    else:
        description = " + ".join(_format_block(block) for block in blocks)
    return f"{prefix} ({description})"


def summarize_structured_workout(structured: dict[str, Any], intensity_target: str | None) -> str:
    """Render the source steps themselves, never stale hand-authored copy."""
    raw_steps = structured.get("steps")
    if not isinstance(raw_steps, list):
        return ""
    return " → ".join(
        _summarize_source_step(raw, intensity_target) for raw in raw_steps if isinstance(raw, dict)
    )


def block_to_source(block: EditableIntervalBlock) -> dict[str, Any]:
    validate_interval_block(block)
    return {
        "repeat": block.repeat,
        "work": _leg_to_source(block.work),
        "rest": _leg_to_source(block.rest),
    }


def scale_block(block: EditableIntervalBlock) -> EditableIntervalBlock:
    """The "Scale down" preset — the *same* Zone-2-aware ease the delivery
    transform and the morning narrative use (Batch 173.2).

    Cuts a continuous block to :data:`AMBER_DURATION_SCALE`; repeated protocols
    instead lose complete trailing reps and keep each work/recovery leg intact.
    Working power is eased via :func:`ease_amber_power_pct`: a hard interval drops
    a zone (never below the Zone-2 floor), but an already-endurance ride *keeps*
    its intensity — so a 67% Z2 ride stays 67% instead of the old ``×0.9`` drop to
    60% that Mark hand-reset on 2026-07-29.
    """
    repeated_protocol = block.repeat > 1 or block.rest.duration_sec > 0
    repeat = (
        max(MIN_REPEATS, round(block.repeat * AMBER_DURATION_SCALE))
        if repeated_protocol
        else block.repeat
    )
    work_duration_sec = (
        block.work.duration_sec
        if repeated_protocol
        else max(MIN_WORK_DURATION_SEC, round(block.work.duration_sec * AMBER_DURATION_SCALE))
    )
    rest_duration_sec = (
        block.rest.duration_sec
        if repeated_protocol
        else round(block.rest.duration_sec * AMBER_DURATION_SCALE)
    )
    return EditableIntervalBlock(
        repeat=repeat,
        work=IntervalLeg(
            duration_sec=work_duration_sec,
            power_pct=max(MIN_POWER_PCT, ease_amber_power_pct(block.work.power_pct)),
            cadence_rpm=block.work.cadence_rpm,
        ),
        rest=IntervalLeg(
            duration_sec=rest_duration_sec,
            power_pct=max(MIN_POWER_PCT, ease_amber_power_pct(block.rest.power_pct)),
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


def _block_from_step(
    raw_step: dict[str, Any],
    intensity_target: str | None,
) -> EditableIntervalBlock:
    raw_block = raw_step.get("block")
    if isinstance(raw_block, dict):
        return _block_from_source(raw_block)

    expanded = workout_delivery._expand_step(raw_step, intensity_target)
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


@dataclass(frozen=True)
class _IntervalCandidate:
    index: int
    block: EditableIntervalBlock


def _interval_candidates(
    raw_steps: list[Any], intensity_target: str | None
) -> list[_IntervalCandidate]:
    candidates: list[_IntervalCandidate] = []
    for index, raw in enumerate(raw_steps):
        if not isinstance(raw, dict):
            continue
        has_block = isinstance(raw.get("block"), dict)
        pattern = raw.get("pattern")
        has_interval_pattern = isinstance(pattern, str) and "/" in pattern
        has_continuous_main = "minutes" in raw and "ramp" not in raw and _step_role(raw) == "main"
        if not has_block and not has_interval_pattern and not has_continuous_main:
            continue
        try:
            candidates.append(
                _IntervalCandidate(
                    index=index,
                    block=_block_from_step(raw, intensity_target),
                )
            )
        except (HTTPException, KeyError, TypeError, ValueError):
            continue
    return candidates


def _main_interval_candidates(
    raw_steps: list[Any], intensity_target: str | None
) -> list[_IntervalCandidate]:
    candidates = _interval_candidates(raw_steps, intensity_target)
    main = [
        candidate
        for candidate in candidates
        if isinstance(raw_steps[candidate.index], dict)
        and _step_role(raw_steps[candidate.index]) == "main"
    ]
    return main or candidates


def _editable_step_indices(raw_steps: list[Any], intensity_target: str | None) -> tuple[int, ...]:
    candidates = _main_interval_candidates(raw_steps, intensity_target)
    if not candidates:
        return ()
    # The editor changes the workout's interval stimulus. Power is the decisive
    # discriminator when a longer Zone-2 block sits beside a shorter sprint set;
    # total duration breaks ordinary main-set ties, and ``-index`` makes an exact
    # tie stable on the first source step instead of silently preferring the last.
    selected = max(
        candidates,
        key=lambda candidate: (
            candidate.block.work.power_pct,
            candidate.block.repeat
            * (candidate.block.work.duration_sec + candidate.block.rest.duration_sec),
            -candidate.index,
        ),
    )
    return tuple(candidate.index for candidate in candidates if candidate.block == selected.block)


def _primary_step_index(raw_steps: list[Any], intensity_target: str | None) -> int | None:
    """Compatibility name for the first step in the logical editable set."""
    indices = _editable_step_indices(raw_steps, intensity_target)
    return indices[0] if indices else None


def _step_role(raw: dict[str, Any]) -> str:
    label = str(raw.get("label") or "").lower()
    if "warm" in label or "settle" in label:
        return "warmup"
    if "cool" in label:
        return "cooldown"
    if "primer" in label:
        return "primer"
    if "recover" in label:
        return "recovery"
    return "main"


def _normalise_main_interval_labels(raw_steps: list[Any], intensity_target: str | None) -> None:
    for candidate in _main_interval_candidates(raw_steps, intensity_target):
        raw = raw_steps[candidate.index]
        assert isinstance(raw, dict)
        raw["label"] = _block_label(candidate.block, str(raw.get("label") or "Intervals"))


def _normalise_matching_interval_labels(
    raw_steps: list[Any],
    intensity_target: str | None,
    block: EditableIntervalBlock,
) -> None:
    for candidate in _main_interval_candidates(raw_steps, intensity_target):
        if candidate.block != block:
            continue
        raw = raw_steps[candidate.index]
        assert isinstance(raw, dict)
        raw["label"] = _block_label(candidate.block, str(raw.get("label") or "Intervals"))


def _block_label(block: EditableIntervalBlock, original_label: str) -> str:
    suffix = re.search(r"\bblock\s+\d+\b", original_label, flags=re.IGNORECASE)
    return f"{_format_block(block)}{f' {suffix.group(0).lower()}' if suffix else ''}"


def _format_block(block: EditableIntervalBlock) -> str:
    work = _format_duration(block.work.duration_sec)
    if block.rest.duration_sec > 0:
        effort = f"{work}/{_format_duration(block.rest.duration_sec)}"
        power = f"{block.work.power_pct}%/{block.rest.power_pct}%"
    else:
        effort = work
        power = f"{block.work.power_pct}%"
    prefix = f"{block.repeat} × " if block.repeat > 1 else ""
    return f"{prefix}{effort} @ {power}"


def _format_duration(duration_sec: int) -> str:
    if duration_sec < 60:
        return f"{duration_sec}s"
    minutes, seconds = divmod(duration_sec, 60)
    if seconds == 0:
        return f"{minutes} min"
    return f"{minutes}:{seconds:02d}"


def _format_minutes(value: Any) -> str:
    try:
        minutes = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{minutes:g} min"


def _summarize_source_step(raw: dict[str, Any], intensity_target: str | None) -> str:
    if isinstance(raw.get("block"), dict) or (
        isinstance(raw.get("pattern"), str) and "/" in str(raw["pattern"])
    ):
        try:
            return _format_block(_block_from_step(raw, intensity_target))
        except (HTTPException, KeyError, TypeError, ValueError):
            pass
    if "ramp" in raw and isinstance(raw.get("ramp"), list) and len(raw["ramp"]) == 2:
        return f"{_format_minutes(raw.get('minutes'))} ramp {raw['ramp'][0]}→{raw['ramp'][1]}%"
    if "minutes" in raw:
        target = str(raw.get("target") or raw.get("label") or "steady")
        return f"{_format_minutes(raw.get('minutes'))} @ {target}"
    return str(raw.get("label") or "Step")


def _prescription_title_prefix(title: str) -> str | None:
    if " (" in title:
        return title.split(" (", 1)[0].rstrip()
    marker = re.search(
        r"\b(?:\d+\s*[×x]\s*|\d+(?::\d+)?(?:s|min)\b|\d+/\d+)",
        title,
        flags=re.IGNORECASE,
    )
    if marker is None:
        return None
    prefix = title[: marker.start()].rstrip(" -(")
    return prefix or None


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


# ---------------------------------------------------------------------------
# Batch 264 — the coach quotes a real block, and its answer carries one back.
# ---------------------------------------------------------------------------
#
# Until now the only way a conversation reached the plan was a button that
# re-proposed the *stored* session, so an agreed "2 × 10 min of 35s/25s" was
# composed in prose and thrown away. These three helpers are the whole of the
# structured path: the editable block of today's session (so the coach quotes
# what is actually prescribed rather than guessing from a title), a plain
# rendering of a block for Mark-facing copy, and a parser that turns the five
# numbers the coach may change into a validated :class:`EditableIntervalBlock`.
#
# Cadence is deliberately *not* one of those numbers. Every prescribed block
# already carries it, Mark has never negotiated it in conversation, and carrying
# it forward removes one more field the model could invent.


#: The exact keys a coach-proposed change must supply. Closed, and stated to the
#: model in the prompt, because an open shape is an invitation to invent one.
PROPOSED_BLOCK_FIELDS = ("repeat", "workSec", "workPct", "restSec", "restPct")


def editable_snapshot_for(
    structured: dict[str, Any] | None,
    intensity_target: str | None,
) -> IntervalEditorSnapshot | None:
    """Today's editable interval set, or ``None`` when there is not one.

    The snapshot raises for a session with no editable bike block, which is a
    correct answer to "can this be edited?" rather than an error to propagate
    into a chat turn. No verdict is passed: this asks what is editable, not what
    today's adjustment would be.
    """
    try:
        return interval_editor_snapshot(structured, intensity_target)
    except HTTPException:
        return None


def format_interval_block(block: EditableIntervalBlock) -> str:
    """``10 × 40s/20s @ 125%/55%`` — the same phrasing the step labels use."""
    return _format_block(block)


def block_from_proposal(
    payload: Any,
    *,
    current: EditableIntervalBlock,
) -> EditableIntervalBlock:
    """Build a validated block from the five numbers a coach answer may carry.

    Raises :class:`HTTPException` exactly as every other editor entry point does
    when a number is outside the bounds ``validate_interval_block`` enforces, so
    a model-composed change is bounded by the same rules as a hand-typed one.
    """
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The proposed interval change is malformed",
        )
    missing = [field for field in PROPOSED_BLOCK_FIELDS if field not in payload]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"The proposed interval change is missing {', '.join(missing)}",
        )
    block = EditableIntervalBlock(
        repeat=_as_int(payload["repeat"]),
        work=IntervalLeg(
            duration_sec=_as_int(payload["workSec"]),
            power_pct=_as_int(payload["workPct"]),
            cadence_rpm=current.work.cadence_rpm,
        ),
        rest=IntervalLeg(
            duration_sec=_as_int(payload["restSec"]),
            power_pct=_as_int(payload["restPct"]),
            cadence_rpm=current.rest.cadence_rpm,
        ),
    )
    validate_interval_block(block)
    return block
