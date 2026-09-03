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
    Zone-2 prescription anchor** (:data:`ENDURANCE_PRESCRIPTION_PCT`). A step at
    or below that anchor is held; a higher endurance step is eased to it.

``adjust_ir_for_verdict`` (delivery transform), ``interval_workout_editor.scale_block``
(editor preset), and the morning narrative/``verdictAdjustment`` packet all go
through :func:`ease_amber_power_pct`, so the numbers agree everywhere.

Batch 215 gives **Red** the same endurance-awareness, reversing the half of
Decision #61 that made Red a blanket half-duration cut capped at
:data:`RECOVERY_CAP_PCT` (Decision #293). A ride that is *already* Zone 2 is not a
stimulus Red needs to delete: sustained low intensity builds sleep pressure without
the sympathetic arousal harder work produces, so gutting it works against the Red
rule's own purpose. Red now splits on what the ride actually is:

  * **already endurance** (:func:`ir_is_endurance`): keep the ride in Zone 2,
    easing upper-endurance work to the 67% prescription anchor, and take a light duration cut
    (:data:`RED_ENDURANCE_DURATION_SCALE`);
  * **anything harder**, or a day already carrying another session: the original
    recovery substitution, unchanged — half duration, every step capped at
    :data:`RECOVERY_CAP_PCT`, which deliberately *does* drop below Zone 2.

The Red-never-VO2 guarantee is untouched by this: a VO2 ride can never be
"already endurance", so it always takes the recovery substitution, and
:func:`blocks_red_vo2` still gates the push independently.

Batch 243 makes the ladder monotonic and preserves interval protocols. Red's
endurance cut can no longer leave more work than Amber, a companion session
tightens Amber to the edge of its 20–30% duration band, and repeated work/rest
legs are removed as whole repetitions instead of being shortened into a different
protocol. Continuous endurance blocks may still be shortened; their duration is
the dose rather than a defining work/rest geometry.

Every function here is pure (IR/int/bool in, IR/int/bool out) so the safety
properties stay unit-testable without a database. The *facts* a caller needs to
supply — today's verdict, and whether the day already holds another session — are
resolved by the callers, which already load them.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

# Verdict-driven adjustment knobs (percentage points of FTP unless noted).
AMBER_DURATION_SCALE = 0.75  # 25% cut keeps inside the 20-30% Amber band
# A second session makes the day's total the dose. Amber therefore uses the
# cautious edge of its existing 20–30% band rather than ignoring that load.
AMBER_COMPANION_DURATION_SCALE = 0.70
RED_DURATION_SCALE = 0.5
# Batch 215: Red's duration cut for a ride that is *already* Zone 2. Still a
# material reduction — a Red morning must not deliver a Green-looking session —
# but it keeps the sustained easy work that builds sleep pressure, which the old
# blanket half-cut deleted (Decision #293).
RED_ENDURANCE_DURATION_SCALE = 0.70
ZONE_DROP_PCT = 13  # one training zone is ~13 percentage points of FTP
HIT_FLOOR_PCT = 106  # VO2/anaerobic work begins around 106% FTP
AMBER_POWER_CAP_PCT = 94  # Amber removes HIT: cap at the top of Sweet Spot
RECOVERY_CAP_PCT = 60  # Red easy-spin ceiling — guarantees no VO2
MIN_POWER_PCT = 45
# Top of Zone 2 (endurance). At or below this a working interval is already easy,
# so the ride remains eligible for the endurance path.
ENDURANCE_CEILING_PCT = 75
# Mark's plan-level Zone-2 anchor. This is a prescription, not a classification:
# compromised-day work between 68% and the ceiling is brought back to this value.
ENDURANCE_PRESCRIPTION_PCT = 67


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


def ir_is_endurance(ir: dict[str, Any] | None) -> bool:
    """True when a structured-workout IR's hardest *working* step is already Zone 2.

    Batch 215: this is the predicate Red splits on. It reads the hardest working
    interval rather than the average, so a ride that is mostly Zone 2 but carries
    one harder block is *not* endurance and still takes the recovery substitution —
    the same conservative direction :func:`ir_has_vo2` takes.
    """
    steps = ir.get("steps") if isinstance(ir, dict) else None
    if not isinstance(steps, list):
        return False
    primary = _primary_work_step([s for s in steps if isinstance(s, dict)])
    if primary is None:
        return False
    return _step_power(primary) <= ENDURANCE_CEILING_PCT


#: A session with one of these statuses adds no load to the day, so it never
#: withdraws Red's endurance allowance.
_WEIGHTLESS_SESSION_STATUSES = frozenset({"skipped", "removed", "cancelled"})


def companion_session_present(other_session_statuses: Iterable[str | None]) -> bool:
    """The Batch 215.5 combined-load fact, as one shared rule.

    Callers pass the statuses of the day's *other* active sessions — they already
    hold them — and this decides whether any of them counts as load. Keeping the
    rule here rather than at each call site is what stops the delivery rail and the
    morning packet drifting apart on the same day, which is the whole point of this
    module.
    """
    return any(
        str(status or "planned").strip().lower() not in _WEIGHTLESS_SESSION_STATUSES
        for status in other_session_statuses
    )


def red_holds_endurance(ir: dict[str, Any] | None, *, companion_session: bool = False) -> bool:
    """Whether Red keeps this ride's Zone-2 shape instead of substituting recovery.

    ``companion_session`` is the Batch 215.5 combined-load gate: with another
    session already scheduled the same day, the day's *total* is what matters, so
    the endurance allowance is withdrawn and Red reverts to the recovery
    substitution. The caller resolves the flag; this stays a pure predicate.
    """
    return not companion_session and ir_is_endurance(ir)


def red_duration_scale(ir: dict[str, Any] | None, *, companion_session: bool = False) -> float:
    """Red's duration scale for this ride — light on Zone 2, halved on anything else."""
    if red_holds_endurance(ir, companion_session=companion_session):
        return RED_ENDURANCE_DURATION_SCALE
    return RED_DURATION_SCALE


def amber_duration_scale(*, companion_session: bool = False) -> float:
    """Amber's duration scale, tightened when another session shares the day."""
    return AMBER_COMPANION_DURATION_SCALE if companion_session else AMBER_DURATION_SCALE


def red_power_cap_pct(ir: dict[str, Any] | None, *, companion_session: bool = False) -> int:
    """Red's working-intensity ceiling — the 67% anchor on an endurance ride."""
    if red_holds_endurance(ir, companion_session=companion_session):
        return ENDURANCE_PRESCRIPTION_PCT
    return RECOVERY_CAP_PCT


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

    * **At/below the prescription anchor** (``<= 67%``): keep the intensity — a
      Zone-2 ride is not dropped into recovery; only its duration is cut.
    * **Upper endurance** (``68-75%``): keep the endurance classification but
      ease the prescription to Mark's 67% Zone-2 anchor.
    * **Harder** (tempo/sweet-spot/threshold/VO2): drop one zone, but never below
      the Zone-2 prescription anchor, and cap at the top of Sweet Spot so no HIT/VO2 or
      threshold work survives.

    Deterministic and pure, so the delivery transform, the editor preset, and the
    narrative all quote the same number for a given planned intensity.
    """
    if power_pct <= ENDURANCE_PRESCRIPTION_PCT:
        return power_pct
    dropped = max(power_pct - ZONE_DROP_PCT, ENDURANCE_PRESCRIPTION_PCT)
    return min(dropped, AMBER_POWER_CAP_PCT)


def _adjust_step(
    step: dict[str, Any],
    *,
    duration_sec: int,
    power_cap: int,
    ease: Callable[[int], int] | None,
) -> dict[str, Any]:
    phase = str(step.get("phase") or "interval")

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
        "durationSec": duration_sec,
        "powerStartPct": start,
        "powerEndPct": end,
    }
    cadence = step.get("cadenceRpm")
    if cadence:
        new_step["cadenceRpm"] = cadence
    return new_step


def _repeat_identity(step: dict[str, Any]) -> tuple[str, str, int, int] | None:
    """Parse the canonical ``<label> work|recovery i/n`` expanded-step suffix."""
    label = str(step.get("label") or "")
    try:
        prefix_and_leg, position = label.rsplit(" ", 1)
        prefix, leg = prefix_and_leg.rsplit(" ", 1)
        index_text, total_text = position.split("/", 1)
        index, total = int(index_text), int(total_text)
    except (ValueError, TypeError):
        return None
    if leg not in {"work", "recovery"} or total < 1 or index < 1 or index > total:
        return None
    return prefix, leg, index, total


def _scaled_durations(
    steps: list[dict[str, Any]], indices: list[int], target_total: int
) -> dict[int, int]:
    """Scale divisible steps to an exact total while keeping every duration positive."""
    if not indices or target_total <= 0:
        return {}
    source_total = sum(max(1, int(steps[index].get("durationSec", 0))) for index in indices)
    if source_total <= 0:
        return {}
    target_total = max(len(indices), target_total)
    durations = {
        index: max(
            1,
            round(max(1, int(steps[index].get("durationSec", 0))) * target_total / source_total),
        )
        for index in indices
    }
    delta = target_total - sum(durations.values())
    # Put rounding residue on the longest step; one-second corrections cannot
    # distort a protocol and make the total deterministic.
    anchor = max(indices, key=lambda index: durations[index])
    durations[anchor] = max(1, durations[anchor] + delta)
    return durations


def _closest_prefix_count(unit_totals: list[int], target_total: float) -> int:
    """Number of leading repetitions whose whole duration is closest to target."""
    cumulative = 0
    candidates = [(abs(target_total), 0)]
    for count, duration in enumerate(unit_totals, start=1):
        cumulative += duration
        candidates.append((abs(cumulative - target_total), count))
    # Equal-distance ties choose fewer reps: the cautious direction for an eased day.
    return min(candidates, key=lambda item: (item[0], item[1]))[1]


def _adjust_steps_preserving_geometry(
    steps: list[dict[str, Any]],
    *,
    duration_scale: float,
    power_cap: int,
    ease: Callable[[int], int] | None,
) -> list[dict[str, Any]]:
    """Adjust duration without changing a repeated interval's work/rest geometry.

    Expanded repeat legs are indivisible: easing removes complete trailing
    repetitions and rewrites their ``i/n`` labels. Warm-up/cool-down steps stay at
    full length while the target permits it, and continuous interval blocks absorb
    the exact remaining duration. If the cautious target is shorter than the fixed
    opening/closing total, every divisible step is shortened proportionally while
    atomic repeats remain indivisible. If no interval effort survives, the whole
    plan becomes a continuous recovery substitution instead of an ungradable shell.
    """
    if not steps:
        return []
    source_total = sum(max(1, int(step.get("durationSec", 0))) for step in steps)
    target_total = max(1, round(source_total * duration_scale))

    candidate_groups: dict[tuple[str, int], dict[int, list[int]]] = {}
    candidate_parts: dict[int, tuple[str, str, int, int]] = {}
    for step_index, step in enumerate(steps):
        identity = _repeat_identity(step)
        if identity is None:
            continue
        prefix, leg, repeat_index, repeat_total = identity
        candidate_parts[step_index] = identity
        candidate_groups.setdefault((prefix, repeat_total), {}).setdefault(repeat_index, []).append(
            step_index
        )
    # A one-leg ``work 1/1`` is how the source editor serializes a continuous
    # block, not an interval protocol. It remains divisible. A work/recovery pair
    # is geometry even at 1/1, and any multi-repeat set is atomic by definition.
    atomic_keys = {
        key
        for key, repeats in candidate_groups.items()
        if key[1] > 1
        or any(
            candidate_parts[index][1] == "recovery"
            for indices in repeats.values()
            for index in indices
        )
    }
    repeat_groups = {
        key: repeats for key, repeats in candidate_groups.items() if key in atomic_keys
    }
    repeat_parts = {
        index: identity
        for index, identity in candidate_parts.items()
        if (identity[0], identity[3]) in atomic_keys
    }

    fixed_indices = [
        index
        for index, step in enumerate(steps)
        if index not in repeat_parts and str(step.get("phase") or "interval") != "interval"
    ]
    continuous_indices = [
        index
        for index, step in enumerate(steps)
        if index not in repeat_parts and str(step.get("phase") or "interval") == "interval"
    ]
    fixed_total = sum(max(1, int(steps[index].get("durationSec", 0))) for index in fixed_indices)

    keep_repeats: dict[tuple[str, int], set[int]] = {}
    if target_total <= fixed_total:
        divisible_durations = _scaled_durations(
            steps, fixed_indices + continuous_indices, target_total
        )
        fixed_durations = {
            index: duration
            for index, duration in divisible_durations.items()
            if index in fixed_indices
        }
        continuous_durations = {
            index: duration
            for index, duration in divisible_durations.items()
            if index in continuous_indices
        }
    else:
        fixed_durations = {
            index: max(1, int(steps[index].get("durationSec", 0))) for index in fixed_indices
        }
        interval_budget = target_total - fixed_total
        continuous_total = sum(
            max(1, int(steps[index].get("durationSec", 0))) for index in continuous_indices
        )
        group_totals = {
            key: sum(
                max(1, int(steps[index].get("durationSec", 0)))
                for indices in repeats.values()
                for index in indices
            )
            for key, repeats in repeat_groups.items()
        }
        interval_source_total = continuous_total + sum(group_totals.values())
        kept_repeat_total = 0
        repeat_units: dict[tuple[str, int], list[tuple[int, int]]] = {}
        for key, repeats in repeat_groups.items():
            ordered_repeats = sorted(repeats)
            unit_totals = [
                sum(max(1, int(steps[index].get("durationSec", 0))) for index in repeats[number])
                for number in ordered_repeats
            ]
            repeat_units[key] = list(zip(ordered_repeats, unit_totals, strict=True))
            share = (
                interval_budget * group_totals[key] / interval_source_total
                if interval_source_total
                else 0.0
            )
            keep_count = _closest_prefix_count(unit_totals, share)
            kept = set(ordered_repeats[:keep_count])
            keep_repeats[key] = kept
            kept_repeat_total += sum(unit_totals[:keep_count])

        # Whole repetitions are discrete. If the initial proportional choice
        # leaves too little duration even with every fixed/continuous second, add
        # the shortest next repetition. Conversely, remove a trailing repetition
        # if the atomic work alone exceeds the target. Fixed easy steps then absorb
        # the small residue, preserving the exact overall dose where possible.
        while kept_repeat_total + fixed_total + continuous_total < target_total:
            candidates = [
                (duration, key, repeat_index)
                for key, units in repeat_units.items()
                for repeat_index, duration in units
                if repeat_index == len(keep_repeats.get(key, set())) + 1
            ]
            if not candidates:
                break
            duration, key, repeat_index = min(candidates)
            keep_repeats.setdefault(key, set()).add(repeat_index)
            kept_repeat_total += duration

        while kept_repeat_total > target_total:
            candidates = [
                (duration, key, repeat_index)
                for key, units in repeat_units.items()
                for repeat_index, duration in units
                if repeat_index in keep_repeats.get(key, set())
                and repeat_index == max(keep_repeats[key])
            ]
            if not candidates:
                break
            duration, key, repeat_index = min(
                candidates,
                key=lambda item: abs((kept_repeat_total - item[0]) - target_total),
            )
            keep_repeats[key].remove(repeat_index)
            kept_repeat_total -= duration

        remaining = max(0, target_total - kept_repeat_total)
        fixed_target = min(fixed_total, remaining)
        fixed_durations = _scaled_durations(steps, fixed_indices, fixed_target)
        continuous_target = min(
            continuous_total,
            max(0, remaining - fixed_target),
        )
        continuous_durations = _scaled_durations(steps, continuous_indices, continuous_target)

    adjusted: list[dict[str, Any]] = []
    for index, step in enumerate(steps):
        identity = repeat_parts.get(index)
        if identity is not None:
            prefix, leg, repeat_index, repeat_total = identity
            kept = keep_repeats.get((prefix, repeat_total), set())
            if repeat_index not in kept:
                continue
            duration = max(1, int(step.get("durationSec", 0)))
            changed = dict(step)
            changed["label"] = f"{prefix} {leg} {repeat_index}/{len(kept)}"
        elif index in fixed_durations:
            duration = fixed_durations[index]
            changed = step
        elif index in continuous_durations:
            duration = continuous_durations[index]
            changed = step
        else:
            continue
        next_step = _adjust_step(
            changed,
            duration_sec=duration,
            power_cap=power_cap,
            ease=ease,
        )
        adjusted.append(next_step)
    source_has_interval = any(str(step.get("phase") or "interval") == "interval" for step in steps)
    adjusted_has_interval = any(step["phase"] == "interval" for step in adjusted)
    if not adjusted or (source_has_interval and not adjusted_has_interval):
        # A valid manually-authored workout may contain only one work/recovery
        # pair and no divisible warm-up/cool-down (Decision #161). Removing that
        # sole repetition can produce an empty workout or only an easy fixed-step
        # shell, so take the other sanctioned easing route: change the session
        # type to one continuous, genuinely easy recovery effort. Its 60%-FTP
        # ceiling keeps load monotonic even when the source pair contains a long
        # 45%-FTP recovery.
        recovery_pct = min(power_cap, RECOVERY_CAP_PCT)
        recovery_source = {
            "label": "Recovery substitution",
            "phase": "interval",
            "durationSec": target_total,
            "powerStartPct": recovery_pct,
            "powerEndPct": recovery_pct,
        }
        adjusted = [
            _adjust_step(
                recovery_source,
                duration_sec=target_total,
                power_cap=recovery_pct,
                ease=None,
            )
        ]
    return adjusted


def adjust_ir_for_verdict(
    base_ir: dict[str, Any],
    verdict: str | None,
    *,
    companion_session: bool = False,
) -> dict[str, Any]:
    """Return a verdict-adjusted copy of a structured-workout IR.

    * **Green** (or unknown): proceed as planned — the IR is returned unchanged
      apart from an ``origin``/``adjustment`` annotation.
    * **Amber**: cut the total duration to 70–75% and ease working intervals via
      :func:`ease_amber_power_pct` — a hard interval drops a zone (never below the
      Zone-2 anchor) and HIT is capped away, while an already-endurance ride stays
      at or below 67%. Repeated protocols lose whole reps; divisible easy steps
      absorb any residue needed to preserve the exact total.
    * **Red** on an **already-endurance** ride (Batch 215): hold or anchor the
      planned Zone-2 intensity at 67% and take the lighter
      ``RED_ENDURANCE_DURATION_SCALE`` cut. The hard
      work is still gone — there is none to remove — and the easy work that builds
      sleep pressure survives.
    * **Red** on anything harder, or on a day already carrying another session:
      substitute an easy recovery spin — half duration and every step capped at
      ``RECOVERY_CAP_PCT``, which guarantees the output can never be a VO2 push.
    """
    status = _normalize_verdict(verdict)
    raw_steps = base_ir.get("steps")
    steps = [s for s in raw_steps if isinstance(s, dict)] if isinstance(raw_steps, list) else []
    original_name = str(base_ir.get("name") or "Workout")

    if status == "Amber":
        duration_scale = amber_duration_scale(companion_session=companion_session)
        power_cap = AMBER_POWER_CAP_PCT
        ease: Callable[[int], int] | None = ease_amber_power_pct
        origin, name_prefix = "amber_regeneration", "Amber-adjusted"
    elif status == "Red":
        duration_scale = red_duration_scale(base_ir, companion_session=companion_session)
        power_cap = red_power_cap_pct(base_ir, companion_session=companion_session)
        ease = None
        if red_holds_endurance(base_ir, companion_session=companion_session):
            origin, name_prefix = "red_endurance_hold", "Red-adjusted"
        else:
            origin, name_prefix = "red_substitution", "Recovery substitution"
    else:
        unchanged = dict(base_ir)
        unchanged["origin"] = "as_planned"
        unchanged["adjustment"] = {"verdict": status or "Unknown", "changed": False}
        return unchanged

    removed_hit = any(_step_power(step) >= HIT_FLOOR_PCT for step in steps)
    new_steps = _adjust_steps_preserving_geometry(
        steps,
        duration_scale=duration_scale,
        power_cap=power_cap,
        ease=ease,
    )
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
        "durationScalePct": (
            round(sum(int(step["durationSec"]) for step in new_steps) / basis_total * 100)
            if basis_total > 0
            else round(duration_scale * 100)
        ),
        "zoneDropPct": zone_drop_pts,
        "powerCapPct": power_cap,
        "removedHit": removed_hit,
        # True only when the transform literally kept an already-Zone-2
        # intensity, rather than easing upper endurance to the 67% anchor.
        "enduranceHold": _holds_endurance(base_ir, status, companion_session=companion_session),
        "basisName": original_name,
        "basisTotalDurationSec": basis_total,
    }
    if status in {"Amber", "Red"}:
        adjusted["adjustment"]["companionSession"] = companion_session
    return adjusted


def _holds_endurance(
    base_ir: dict[str, Any], status: str | None, *, companion_session: bool
) -> bool:
    raw_steps = base_ir.get("steps")
    steps = (
        [step for step in raw_steps if isinstance(step, dict)]
        if isinstance(raw_steps, list)
        else []
    )
    primary = _primary_work_step(steps)
    already_at_anchor = primary is not None and _step_power(primary) <= ENDURANCE_PRESCRIPTION_PCT
    if status == "Amber":
        return ir_is_endurance(base_ir) and already_at_anchor
    if status == "Red":
        return (
            red_holds_endurance(base_ir, companion_session=companion_session) and already_at_anchor
        )
    return False


def verdict_duration_scale(
    base_ir: dict[str, Any],
    verdict: str | None,
    *,
    companion_session: bool = False,
) -> float | None:
    """The duration scale :func:`adjust_ir_for_verdict` will apply, or ``None`` on Green.

    Exposed for callers that need the nominal verdict ladder. The canonical IR
    transform may report a nearby actual percentage when an interval protocol can
    only be shortened by removing whole repetitions.
    """
    status = _normalize_verdict(verdict)
    if status == "Amber":
        return amber_duration_scale(companion_session=companion_session)
    if status == "Red":
        return red_duration_scale(base_ir, companion_session=companion_session)
    return None


def verdict_power_pct(
    power_pct: int,
    base_ir: dict[str, Any],
    verdict: str | None,
    *,
    companion_session: bool = False,
) -> int:
    """One working interval's intensity after the verdict adjustment.

    The per-step half of :func:`adjust_ir_for_verdict`, so the editor preset and the
    delivery transform cannot drift apart on intensity either.
    """
    status = _normalize_verdict(verdict)
    if status == "Amber":
        return _clamp_power(ease_amber_power_pct(power_pct), AMBER_POWER_CAP_PCT)
    if status == "Red":
        return _clamp_power(
            power_pct, red_power_cap_pct(base_ir, companion_session=companion_session)
        )
    return power_pct


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
    base_ir: dict[str, Any],
    verdict: str | None,
    *,
    companion_session: bool = False,
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

    adjusted = adjust_ir_for_verdict(base_ir, status, companion_session=companion_session)
    adjusted_steps = [s for s in adjusted.get("steps", []) if isinstance(s, dict)]
    base_primary = _primary_work_step(base_steps)
    adjusted_primary = _primary_work_step(adjusted_steps)
    planned_power = _step_power(base_primary) if base_primary is not None else None
    adjusted_power = _step_power(adjusted_primary) if adjusted_primary is not None else None
    adjustment = adjusted.get("adjustment")
    duration_scale_pct = (
        adjustment.get("durationScalePct") if isinstance(adjustment, dict) else None
    )

    summary: dict[str, Any] = {
        "verdict": status,
        "changed": True,
        "durationScalePct": duration_scale_pct,
        "plannedDurationMin": _total_minutes(base_ir, base_steps),
        "adjustedDurationMin": _total_minutes(adjusted, adjusted_steps),
        "plannedWorkPowerPct": planned_power,
        "adjustedWorkPowerPct": adjusted_power,
        # Read off the outcome rather than the verdict name: upper endurance is
        # still classified as endurance but is not described as held when it was
        # eased to the 67% prescription anchor.
        "intensityHeldAtEndurance": (
            planned_power is not None
            and adjusted_power == planned_power
            and planned_power <= ENDURANCE_PRESCRIPTION_PCT
        ),
        "removedHit": bool(
            adjusted.get("adjustment", {}).get("removedHit")
            if isinstance(adjusted.get("adjustment"), dict)
            else False
        ),
        "enduranceCeilingPct": ENDURANCE_CEILING_PCT,
        "endurancePrescriptionPct": ENDURANCE_PRESCRIPTION_PCT,
        "source": "deterministic",
        "classificationImpact": "none",
    }
    if status in {"Amber", "Red"}:
        summary["companionSession"] = companion_session
    return summary
