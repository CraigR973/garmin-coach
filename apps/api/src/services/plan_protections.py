"""Fixed safeguards and comparison for a proposed training plan (Batch 334)."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, Final

from src.services.workout_delivery import expand_structured_steps

# Plan No. 3 peaks at 20 minutes above 106% FTP (weeks 10 and 11). The extra
# ten minutes allows an edit without accepting the review's 72-minute example.
MAX_VO2_WORK_MINUTES: Final = 30
VO2_THRESHOLD_PCT: Final = 106

TEST_CAUTION: Final = (
    "This change removes or alters the ramp test. Without that test, your next FTP "
    "and the ride targets based on it will not be checked in this plan."
)
VO2_CAUTION: Final = (
    "This change removes or greatly reduces a VO₂ session. The plan will have less "
    "of the hard work it was built around."
)
RECOVERY_CAUTION: Final = (
    "This change makes a recovery week heavier. Its lighter load is there to let "
    "you recover before the next build weeks."
)
PLAN_THREE_VO2_RATIONALE: Final = (
    "This proposal uses 30/30s then 30/15s for VO₂, rather than the longer 2–3-minute "
    "progression you wrote on 28 Aug. It follows the app's existing VO₂ protocol table; "
    "it has not compared the two approaches for you. Talk it through or change the "
    "sessions before accepting."
)


def _vo2_work_seconds(structured: Mapping[str, Any], intensity_target: str | None) -> float:
    """Count the whole session, including matching sets and partial high-power ramps."""

    steps = expand_structured_steps(dict(structured), intensity_target)
    seconds = 0.0
    for step in steps:
        start = float(step.get("powerStartPct") or 0)
        end = float(step.get("powerEndPct") or 0)
        duration = float(step.get("durationSec") or 0)
        low, high = min(start, end), max(start, end)
        if high <= VO2_THRESHOLD_PCT:
            continue
        if low > VO2_THRESHOLD_PCT:
            seconds += duration
        elif high > low:
            seconds += duration * (high - VO2_THRESHOLD_PCT) / (high - low)
    return seconds


def vo2_work_minutes(structured: Mapping[str, Any], intensity_target: str | None) -> float:
    """The whole-session dose rounded for display in a change summary."""

    return round(_vo2_work_seconds(structured, intensity_target) / 60, 2)


def dose_refusal(structured: Mapping[str, Any], intensity_target: str | None) -> str | None:
    seconds = _vo2_work_seconds(structured, intensity_target)
    if seconds <= MAX_VO2_WORK_MINUTES * 60:
        return None
    minutes = math.ceil(seconds / 60 * 100) / 100
    return (
        f"That session would have {minutes:g} min above {VO2_THRESHOLD_PCT}% FTP across "
        f"all its sets. The limit is {MAX_VO2_WORK_MINUTES} min: Plan No. 3 peaks at "
        "20 min, with a 10 min margin. Shorten the efforts or reduce the sets."
    )


def _sessions(draft: Mapping[str, Any]) -> list[tuple[Mapping[str, Any], Mapping[str, Any]]]:
    return [
        (week, workout)
        for week in draft.get("weeks") or []
        if isinstance(week, Mapping)
        for workout in week.get("workouts") or []
        if isinstance(workout, Mapping)
    ]


def _dose(workout: Mapping[str, Any]) -> float:
    structured = workout.get("structuredWorkout")
    if not isinstance(structured, Mapping) or structured.get("format") != "bike":
        return 0
    return vo2_work_minutes(structured, workout.get("intensityTarget"))


def protection_cautions(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[str]:
    """Warnings selected from actual before/after content, independent of model words."""

    # Compare with the proposal as well as this edit. Several individually small
    # changes can otherwise remove most VO₂ work or gradually fill a recovery week.
    from datetime import date

    from src.services.plan_changes import _rebuild, normalise_draft

    working = normalise_draft(before)
    proposal = working["proposal"]
    original = _rebuild(
        working,
        start=date.fromisoformat(proposal["startDate"]),
        days=proposal["days"],
    )
    baseline = {str(workout.get("id")): workout for _, workout in _sessions(original)}
    old = {str(workout.get("id")): workout for _, workout in _sessions(before)}
    new = {str(workout.get("id")): workout for _, workout in _sessions(after)}
    cautions: list[str] = []
    for key, workout in old.items():
        changed = new.get(key)
        if workout.get("kind") == "test" and (
            changed is None
            or changed.get("kind") != "test"
            or changed.get("structuredWorkout") != workout.get("structuredWorkout")
        ):
            cautions.append(TEST_CAUTION)
        previous_dose = _dose(workout)
        baseline_dose = _dose(baseline.get(key, workout))
        if (
            workout.get("kind") == "vo2"
            and baseline_dose > 0
            and (changed is None or _dose(changed) < baseline_dose / 2)
            and (changed is None or _dose(changed) < previous_dose)
        ):
            cautions.append(VO2_CAUTION)
    before_weeks = {
        int(week.get("weekNumber") or 0): int(week.get("totalMin") or 0)
        for week in before.get("weeks") or []
        if isinstance(week, Mapping) and week.get("blockType") == "recovery"
    }
    baseline_weeks = {
        int(week.get("weekNumber") or 0): int(week.get("totalMin") or 0)
        for week in original.get("weeks") or []
        if isinstance(week, Mapping) and week.get("blockType") == "recovery"
    }
    for week in after.get("weeks") or []:
        if not isinstance(week, Mapping) or week.get("blockType") != "recovery":
            continue
        number = int(week.get("weekNumber") or 0)
        previous = before_weeks.get(number, 0)
        current = int(week.get("totalMin") or 0)
        baseline_total = baseline_weeks.get(number, previous)
        if previous and baseline_total and current > previous and current > baseline_total * 1.1:
            cautions.append(RECOVERY_CAUTION)
    return list(dict.fromkeys(cautions))


def _snapshot(draft: Mapping[str, Any]) -> dict[str, Any]:
    test = next(
        (
            f"{workout['workoutDate']}: {workout['title']}"
            for _, workout in _sessions(draft)
            if workout.get("kind") == "test"
        ),
        None,
    )
    vo2 = {
        int(week["weekNumber"]): (
            f"{workout['workoutDate']}: {workout['title']} · {_dose(workout):g} min above 106% FTP"
        )
        for week, workout in _sessions(draft)
        if workout.get("kind") == "vo2"
    }
    recovery = {
        int(week["weekNumber"]): int(week.get("totalMin") or 0)
        for week in draft.get("weeks") or []
        if isinstance(week, Mapping) and week.get("blockType") == "recovery"
    }
    return {"test": test, "vo2": vo2, "recovery": recovery}


def plan_comparison(draft: Mapping[str, Any]) -> dict[str, Any]:
    """The stored proposal's deterministic rebuild beside the edited draft."""

    # A lazy import avoids a cycle: plan_changes itself uses the dose and cautions above.
    from datetime import date

    from src.services.plan_changes import _rebuild, normalise_draft

    working = normalise_draft(draft)
    proposal = working["proposal"]
    original = _rebuild(
        working,
        start=date.fromisoformat(proposal["startDate"]),
        days=proposal["days"],
    )
    before, after = _snapshot(original), _snapshot(working)
    return {
        "test": {"asProposed": before["test"], "yourPlan": after["test"]},
        "vo2Sessions": [
            {
                "week": week,
                "asProposed": before["vo2"].get(week),
                "yourPlan": after["vo2"].get(week),
            }
            for week in sorted(before["vo2"].keys() | after["vo2"].keys())
        ],
        "recoveryWeeks": [
            {
                "week": week,
                "asProposed": before["recovery"].get(week),
                "yourPlan": after["recovery"].get(week),
            }
            for week in sorted(before["recovery"].keys() | after["recovery"].keys())
        ],
    }
