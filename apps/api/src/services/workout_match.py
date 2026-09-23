"""Does this activity describe the session that was planned? (Batch 278)

``complete_matched_planned_workout`` matched an activity to a planned row on local
date and workout *category* alone, and flipped the row to ``completed`` without
ever testing whether the two described the same session. Mark surfaced both halves
of that on 22 September 2026:

* **the bike** — a Zone-2 ride at 63% FTP with a maximum heart rate of 125 flipped
  ``VO₂ (5 × 2:30 @ 119%)`` to completed;
* **the strength session** — a ``Daily Bodyweight Workout`` flipped
  ``Dumbbells (full-body)`` to completed, which he flagged himself at 10:16:
  *"Note this wasn't dumbbell workout (which I will switch to later in week,
  possibly tomorrow) but daily Bodyweight workout"*.

**The two cases need different evidence and one rule does not cover both**
(Decision #343). Both are deliberately one-sided: the cost of a false positive is
refusing to record a session Mark really did, so every rule here abstains unless it
can prove a contradiction, and abstaining reproduces today's behaviour exactly.

Bike — *executed intensity against the prescription.*
    A prescription whose hardest sustained step is above Zone 2 demands work the
    ride has to show. Whole-ride average and peak power cannot tell a VO2 session
    from a Zone-2 ride — the 22 September ride peaked at 517 W, higher than any
    genuine VO2 session in the plan, because of its 12-second sprints — but
    *normalised* power can. Measured over every ride with a bike prescription since
    15 June 2026 (63 pairings): 22 genuinely-performed hard sessions sat at
    **0.754–0.867** of FTP and the two sessions Mark did not do sat at **0.636 and
    0.664**, with the 38 endurance prescriptions never consulted at all.
    :data:`EXECUTED_ENDURANCE_CEILING` is placed at 0.70 — below the midpoint of
    that gap on purpose, because under-calling a mismatch is the cheaper error.
    A partial attempt at the session is still that session; grading how it went is
    Batch 80's job, not this one's.

Strength — *the modality each side names.*
    Both sides are ``strength_training`` of similar duration, so nothing numeric
    separates them; what separates them is the words. The plan's whole strength
    vocabulary is ``Dumbbells (full-body)``, ``Bodyweight``, ``Strength
    Maintenance`` and ``Recovery Strength + Mobility``; Garmin's is ``Dumbbell
    Workout``, ``Daily``/``Weekly Bodyweight Workout`` and ``Recovery Morning
    Routine``. A contradiction is only claimed when **both** sides name a modality
    and the modalities differ. ``Recovery Morning Routine`` against ``Bodyweight``
    names nothing on the activity side and is therefore left alone — which is
    correct, because the app cannot tell what he did in it.

Over the full production history the two rules together flag 6 pairings — the two
bike mismatches and four ``Daily Bodyweight Workout`` days including the one Mark
reported — and nothing else.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from src.models.coaching import Activity, PlannedWorkout
from src.services.verdict_scaling import ENDURANCE_CEILING_PCT, ir_sustained_work_pct
from src.services.workout_categories import DAY_CATEGORY_CYCLE, DAY_CATEGORY_WEIGHTS

#: A ride's normalised power as a fraction of FTP, below which it never left
#: endurance. See the module docstring for the 63-pairing measurement behind it.
EXECUTED_ENDURANCE_CEILING = 0.70

#: Modality words, lower-cased and matched as substrings of the whole phrase.
#: Deliberately small: every token here appears in Mark's real plan or in Garmin's
#: real activity names, and a token neither side uses can only add false positives.
_WEIGHTED_TOKENS = ("dumbbell", "barbell", "kettlebell", "weights")
_BODYWEIGHT_TOKENS = ("bodyweight", "body weight", "body-weight")

MODALITY_WEIGHTED = "weighted"
MODALITY_BODYWEIGHT = "bodyweight"


def _modality(*phrases: str | None) -> str | None:
    """The modality a set of phrases names, or ``None`` when they name none or both."""
    haystack = " ".join(phrase for phrase in phrases if phrase).lower()
    if not haystack:
        return None
    weighted = any(token in haystack for token in _WEIGHTED_TOKENS)
    bodyweight = any(token in haystack for token in _BODYWEIGHT_TOKENS)
    if weighted == bodyweight:
        # Neither named, or both named in one phrase — no claim either way.
        return None
    return MODALITY_WEIGHTED if weighted else MODALITY_BODYWEIGHT


def _prescription_phrases(planned: PlannedWorkout) -> list[str | None]:
    phrases: list[str | None] = [planned.title, planned.intensity_target]
    structured = planned.structured_workout
    if isinstance(structured, dict):
        summary = structured.get("summary")
        if isinstance(summary, str):
            phrases.append(summary)
        steps = structured.get("steps")
        if isinstance(steps, list):
            for step in steps:
                if isinstance(step, dict) and isinstance(step.get("label"), str):
                    phrases.append(step["label"])
    return phrases


def strength_material_difference(
    planned: PlannedWorkout,
    activity: Activity,
) -> dict[str, Any] | None:
    """A bodyweight session is not a dumbbell session, and vice versa."""
    prescribed = _modality(*_prescription_phrases(planned))
    executed = _modality(activity.activity_name)
    if prescribed is None or executed is None or prescribed == executed:
        return None
    return {
        "kind": "modality_mismatch",
        "reason": (
            f"The plan prescribed a {prescribed} session ({planned.title}) and the "
            f"activity is a {executed} one ({activity.activity_name})."
        ),
        "prescribed": {"title": planned.title, "modality": prescribed},
        "executed": {"activityName": activity.activity_name, "modality": executed},
    }


def bike_material_difference(
    planned: PlannedWorkout,
    activity: Activity,
    *,
    ftp_watts: int | None,
) -> dict[str, Any] | None:
    """A ride that never left endurance did not do a session that demanded more."""
    if not ftp_watts or ftp_watts <= 0:
        return None
    normalized = activity.normalized_power_watts
    if normalized is None or normalized <= 0:
        return None
    # Imported here so the module stays importable from the completion path without
    # pulling the delivery service's HTTP client in at module scope.
    from src.services.workout_delivery import build_structured_workout_ir

    try:
        ir = build_structured_workout_ir(planned, ftp_watts=ftp_watts)
    except HTTPException:
        # A prescription whose target is prose ("VO₂ (see prescription)") cannot be
        # read as a number, so this rule has nothing to say about it.
        return None
    prescribed_pct = ir_sustained_work_pct(ir)
    if prescribed_pct is None or prescribed_pct <= ENDURANCE_CEILING_PCT:
        return None
    executed_fraction = normalized / ftp_watts
    if executed_fraction >= EXECUTED_ENDURANCE_CEILING:
        return None
    return {
        "kind": "intensity_mismatch",
        "reason": (
            f"The plan prescribed sustained work at {prescribed_pct}% of FTP "
            f"({planned.title}) and the ride's normalised power was "
            f"{round(executed_fraction * 100)}% of FTP — it never left endurance."
        ),
        "prescribed": {
            "title": planned.title,
            "sustainedWorkPctFtp": prescribed_pct,
        },
        "executed": {
            "activityName": activity.activity_name,
            "normalizedPowerWatts": normalized,
            "ftpWatts": ftp_watts,
            "normalisedFractionOfFtp": round(executed_fraction, 3),
        },
    }


def material_difference(
    planned: PlannedWorkout,
    activity: Activity,
    *,
    category: str,
    ftp_watts: int | None = None,
) -> dict[str, Any] | None:
    """Why this activity is not the planned session, or ``None`` when it may be.

    ``None`` means "no contradiction proven", which covers both a genuine match and
    every case the rules abstain from. Only the bike and strength categories carry a
    rule; a walk or a mobility session has no prescription precise enough to
    contradict.
    """
    if category == DAY_CATEGORY_CYCLE:
        return bike_material_difference(planned, activity, ftp_watts=ftp_watts)
    if category == DAY_CATEGORY_WEIGHTS:
        return strength_material_difference(planned, activity)
    return None
