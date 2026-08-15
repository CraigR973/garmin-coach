"""Canonical verdict/ease scaling — one deterministic source of truth.

Batch 173.2: an Amber morning eased the *same* ride to four different intensities
because four code paths each scaled it their own way — the KB rule ("cut duration
and remove HIT", keeps a Zone-2 ride at 67% FTP), the narrative ("drop a zone"),
the interval-editor "Scale down" preset (``×0.9`` → 60%), and the delivery
transform (``−13pt`` → 54%). The last two dropped an already-endurance ride *below*
Zone 2, which is why Mark hand-reset the editor's 60% back to 67% on 2026-07-29.

This module is the single rule they all now share:

  * cut duration to :data:`AMBER_DURATION_SCALE` (a 25% cut, inside the 20-30% band);
  * remove HIT — cap working intensity at :data:`AMBER_POWER_CAP_PCT` (the top
    of the app's Sweet Spot range, rather than leaving former VO2 work at
    threshold);
  * drop hard intervals one zone (:data:`ZONE_DROP_PCT`) **but never below the
    Zone-2 floor** (:data:`ENDURANCE_CEILING_PCT`); a step already at or below that
    ceiling is endurance already, so its intensity is *held* and only the duration
    is cut.

``adjust_ir_for_verdict`` (delivery transform), ``interval_workout_editor.scale_block``
(editor preset), and the morning narrative/``verdictAdjustment`` packet all go
through :func:`ease_amber_power_pct`, so the numbers agree everywhere. Red keeps its
own recovery-substitution shape (everything capped at :data:`RECOVERY_CAP_PCT`, which
deliberately *does* drop below Zone 2 — recovery is the point).

Every function here is pure (IR/int in, IR/int out) so the safety properties stay
unit-testable without a database.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

# Verdict-driven adjustment knobs (percentage points of FTP unless noted).
AMBER_DURATION_SCALE = 0.75  # 25% cut keeps inside the 20-30% Amber band
RED_DURATION_SCALE = 0.5
ZONE_DROP_PCT = 13  # one training zone is ~13 percentage points of FTP
HIT_FLOOR_PCT = 106  # VO2/anaerobic work begins around 106% FTP
AMBER_POWER_CAP_PCT = 94  # Amber removes HIT: cap at the top of Sweet Spot
RECOVERY_CAP_PCT = 60  # Red easy-spin ceiling — guarantees no VO2
MIN_POWER_PCT = 45
# Top of Zone 2 (endurance). At or below this a working interval is already easy,
# so an Amber ease cuts its duration only and never drops it into recovery.
ENDURANCE_CEILING_PCT = 75


def _normalize_verdict(value: str | None) -> str | None:
    if not value:
        return None
    return {"green": "Green", "amber": "Amber", "red": "Red"}.get(value.strip().lower())


def _step_power(step: dict[str, Any]) -> int:
    return max(int(step.get("powerStartPct", 0)), int(step.get("powerEndPct", 0)))


def ir_has_vo2(ir: dict[str, Any] | None) -> bool:
    """True when any step in a structured-workout IR reaches VO2/anaerobic
    intensity (>= ``HIT_FLOOR_PCT`` of FTP)."""
    steps = ir.get("steps") if isinstance(ir, dict) else None
    if not isinstance(steps, list):
        return False
    return any(isinstance(step, dict) and _step_power(step) >= HIT_FLOOR_PCT for step in steps)


def blocks_red_vo2(verdict: str | None, ir: dict[str, Any] | None) -> bool:
    """The Red-never-VO2 *delivery* guarantee, as a pure predicate.

    A proposal carrying VO2 intensity must never be pushed on a day whose morning
    verdict is Red. Returns True when the push should be blocked. Keeping this a
    pure function (verdict + IR in, bool out) makes the safety property unit-
    testable without a database, matching the Batch 13 design (Decision #61).
    """
    return _normalize_verdict(verdict) == "Red" and ir_has_vo2(ir)


def _clamp_power(value: int, cap: int) -> int:
    return max(MIN_POWER_PCT, min(value, cap))


def ease_amber_power_pct(power_pct: int) -> int:
    """The canonical Amber working-interval intensity after easing (Batch 173.2).

    * **Already endurance** (``<= ENDURANCE_CEILING_PCT``): keep the intensity —
      a Zone-2 ride is not dropped into recovery; only its duration is cut. This
      is what Mark's 67% ride should stay at.
    * **Harder** (tempo/sweet-spot/threshold/VO2): drop one zone, but never below
      the Zone-2 ceiling, and cap at the top of Sweet Spot so no HIT/VO2 or
      threshold work survives.

    Deterministic and pure, so the delivery transform, the editor preset, and the
    narrative all quote the same number for a given planned intensity.
    """
    if power_pct <= ENDURANCE_CEILING_PCT:
        return power_pct
    dropped = max(power_pct - ZONE_DROP_PCT, ENDURANCE_CEILING_PCT)
    return min(dropped, AMBER_POWER_CAP_PCT)


def _adjust_step(
    step: dict[str, Any],
    *,
    duration_scale: float,
    power_cap: int,
    ease: Callable[[int], int] | None,
) -> dict[str, Any]:
    phase = str(step.get("phase") or "interval")
    duration = max(1, round(int(step.get("durationSec", 0)) * duration_scale))

    def _power(key: str) -> int:
        raw = int(step.get(key, 0))
        # "Drop a zone" applies to the working intervals; warm-up/cool-down ramps
        # are already easy, so they keep their shape but still honour the cap.
        if ease is not None and phase == "interval":
            raw = ease(raw)
        return _clamp_power(raw, power_cap)

    start = _power("powerStartPct")
    end = _power("powerEndPct")
    new_step: dict[str, Any] = {
        "label": step.get("label", "Step"),
        "phase": phase,
        "kind": "ramp" if start != end else "steady",
        "durationSec": duration,
        "powerStartPct": start,
        "powerEndPct": end,
    }
    cadence = step.get("cadenceRpm")
    if cadence:
        new_step["cadenceRpm"] = cadence
    return new_step


def adjust_ir_for_verdict(base_ir: dict[str, Any], verdict: str | None) -> dict[str, Any]:
    """Return a verdict-adjusted copy of a structured-workout IR.

    * **Green** (or unknown): proceed as planned — the IR is returned unchanged
      apart from an ``origin``/``adjustment`` annotation.
    * **Amber**: cut every step to 75% duration and ease the working intervals via
      :func:`ease_amber_power_pct` — a hard interval drops a zone (never below the
      Zone-2 floor) and HIT is capped away, while an already-endurance ride keeps
      its intensity and is only shortened.
    * **Red**: substitute an easy recovery spin — half duration and every step
      capped at ``RECOVERY_CAP_PCT``, which guarantees the output can never be a
      VO2 push.
    """
    status = _normalize_verdict(verdict)
    raw_steps = base_ir.get("steps")
    steps = [s for s in raw_steps if isinstance(s, dict)] if isinstance(raw_steps, list) else []
    original_name = str(base_ir.get("name") or "Workout")

    if status == "Amber":
        duration_scale, power_cap = AMBER_DURATION_SCALE, AMBER_POWER_CAP_PCT
        ease: Callable[[int], int] | None = ease_amber_power_pct
        origin, name_prefix = "amber_regeneration", "Amber-adjusted"
    elif status == "Red":
        duration_scale, power_cap, ease = RED_DURATION_SCALE, RECOVERY_CAP_PCT, None
        origin, name_prefix = "red_substitution", "Recovery substitution"
    else:
        unchanged = dict(base_ir)
        unchanged["origin"] = "as_planned"
        unchanged["adjustment"] = {"verdict": status or "Unknown", "changed": False}
        return unchanged

    removed_hit = any(_step_power(step) >= HIT_FLOOR_PCT for step in steps)
    new_steps = [
        _adjust_step(step, duration_scale=duration_scale, power_cap=power_cap, ease=ease)
        for step in steps
    ]
    basis_total = int(
        base_ir.get("totalDurationSec") or sum(int(step.get("durationSec", 0)) for step in steps)
    )
    # The actual points shed from the hardest working interval — 0 when an
    # already-endurance ride was only shortened, so the annotation stays honest.
    zone_drop_pts = 0
    if ease is not None:
        for step in steps:
            if str(step.get("phase") or "interval") == "interval":
                before = _step_power(step)
                zone_drop_pts = max(zone_drop_pts, before - ease(before))

    adjusted = dict(base_ir)
    adjusted["steps"] = new_steps
    adjusted["totalDurationSec"] = sum(int(step["durationSec"]) for step in new_steps)
    adjusted["name"] = f"{name_prefix}: {original_name}"
    adjusted["origin"] = origin
    adjusted["cadenceCriticalExpanded"] = True
    adjusted["adjustment"] = {
        "verdict": status,
        "changed": True,
        "durationScalePct": round(duration_scale * 100),
        "zoneDropPct": zone_drop_pts,
        "powerCapPct": power_cap,
        "removedHit": removed_hit,
        "basisName": original_name,
        "basisTotalDurationSec": basis_total,
    }
    return adjusted


def adjust_ir_for_chronic_deload(
    base_ir: dict[str, Any],
    action: dict[str, Any],
) -> dict[str, Any]:
    """Build the Batch 171 lighter proposal without changing the daily verdict.

    The Amber transform supplies the established 25% duration cut, Zone-2-aware
    ease, and HIT removal. The persisted annotation then names chronic evidence—not
    a verdict—as the reason, so the normal propose → approve → push rail can surface
    and deliver it without implying that Green became Amber.
    """

    adjusted = adjust_ir_for_verdict(base_ir, "Amber")
    basis_name = str(base_ir.get("name") or "Workout")
    raw_adjustment = adjusted.get("adjustment")
    adjustment = dict(raw_adjustment) if isinstance(raw_adjustment, dict) else {}
    adjustment.update(
        {
            "verdict": None,
            "reason": "sustained_recovery_strain",
            "chronicAction": {
                "kind": action.get("kind"),
                "triggerSources": list(action.get("triggerSources") or []),
                "recoveryMarkers": list(action.get("recoveryMarkers") or []),
                "redMorningCount": action.get("redMorningCount"),
                "reasons": list(action.get("reasons") or []),
                "verdictImpact": "none",
            },
        }
    )
    adjusted["name"] = f"Chronic deload: {basis_name}"
    adjusted["origin"] = "chronic_deload"
    adjusted["adjustment"] = adjustment
    return adjusted


def _primary_work_step(steps: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The hardest working interval (or the hardest step if none are tagged)."""
    working = [s for s in steps if str(s.get("phase") or "interval") == "interval"]
    pool = working or steps
    return max(pool, key=_step_power) if pool else None


def _total_minutes(ir: dict[str, Any], steps: list[dict[str, Any]]) -> int:
    total = int(ir.get("totalDurationSec") or sum(int(s.get("durationSec", 0)) for s in steps))
    return round(total / 60)


def summarize_verdict_adjustment(
    base_ir: dict[str, Any], verdict: str | None
) -> dict[str, Any] | None:
    """The deterministic Amber/Red adjustment, summarised for the morning packet.

    Explanatory only (``classificationImpact="none"``): it reports what the shared
    transform *does* to today's ride — planned vs adjusted duration and the primary
    working intensity — so the narrative and brief-chat quote the app's own figures
    instead of guessing. Returns ``None`` on a Green/unknown verdict or when the IR
    has no steps, and never influences the verdict or the numbers.
    """
    status = _normalize_verdict(verdict)
    if status not in {"Amber", "Red"}:
        return None
    raw_steps = base_ir.get("steps")
    base_steps = (
        [s for s in raw_steps if isinstance(s, dict)] if isinstance(raw_steps, list) else []
    )
    if not base_steps:
        return None

    adjusted = adjust_ir_for_verdict(base_ir, status)
    adjusted_steps = [s for s in adjusted.get("steps", []) if isinstance(s, dict)]
    base_primary = _primary_work_step(base_steps)
    adjusted_primary = _primary_work_step(adjusted_steps)
    planned_power = _step_power(base_primary) if base_primary is not None else None
    adjusted_power = _step_power(adjusted_primary) if adjusted_primary is not None else None
    duration_scale = RED_DURATION_SCALE if status == "Red" else AMBER_DURATION_SCALE

    return {
        "verdict": status,
        "changed": True,
        "durationScalePct": round(duration_scale * 100),
        "plannedDurationMin": _total_minutes(base_ir, base_steps),
        "adjustedDurationMin": _total_minutes(adjusted, adjusted_steps),
        "plannedWorkPowerPct": planned_power,
        "adjustedWorkPowerPct": adjusted_power,
        "intensityHeldAtEndurance": (
            status == "Amber"
            and planned_power is not None
            and planned_power <= ENDURANCE_CEILING_PCT
        ),
        "removedHit": bool(
            adjusted.get("adjustment", {}).get("removedHit")
            if isinstance(adjusted.get("adjustment"), dict)
            else False
        ),
        "enduranceCeilingPct": ENDURANCE_CEILING_PCT,
        "source": "deterministic",
        "classificationImpact": "none",
    }
