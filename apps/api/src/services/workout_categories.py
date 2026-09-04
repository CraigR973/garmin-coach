from __future__ import annotations

from dataclasses import dataclass

DAY_CATEGORY_CYCLE = "cycle"
DAY_CATEGORY_WEIGHTS = "weights"
DAY_CATEGORY_FLEXIBILITY = "flexibility"
DAY_CATEGORY_WALK = "walk"
DAY_CATEGORY_REST = "rest"

#: The workout-type vocabulary, mirroring ``packages/shared/src/workoutTypes.ts``
#: entry for entry (Batch 253, CR236-05). ``PlannedWorkout.workout_type`` is
#: unconstrained free text classified by ten separate pieces of code — nine here
#: and one in TypeScript — and the two languages implemented **different rules**:
#: sets plus prefixes here, regexes there. They disagreed for values the app's own
#: label map lists. ``flexibility`` and ``deliberate_walk`` classified as
#: ``flexibility``/``walk`` in the app and ``weights`` here; a bare ``vo2`` or
#: ``endurance`` classified as ``cycle`` there and ``weights`` here. Latent, because
#: production holds seven values that classify identically — and live the moment
#: the block generator, the quick-add sheet or a hand-authored plan writes an
#: eighth, with the app and the coach then disagreeing about what kind of day it is
#: and nothing erroring anywhere.
WORKOUT_TYPE_CATEGORY: dict[str, str] = {
    "bike_z2": DAY_CATEGORY_CYCLE,
    "bike_endurance": DAY_CATEGORY_CYCLE,
    "bike_recovery": DAY_CATEGORY_CYCLE,
    "bike_tempo": DAY_CATEGORY_CYCLE,
    "bike_sweet_spot": DAY_CATEGORY_CYCLE,
    "bike_threshold": DAY_CATEGORY_CYCLE,
    "bike_vo2": DAY_CATEGORY_CYCLE,
    # Bare discipline words. TypeScript already classified these as ``cycle`` by
    # regex while this side's set lookup sent them to ``weights``; naming them
    # resolves the divergence the way a human reads them rather than the way the
    # stricter side happened to fall.
    "z2": DAY_CATEGORY_CYCLE,
    "endurance": DAY_CATEGORY_CYCLE,
    "recovery_ride": DAY_CATEGORY_CYCLE,
    "tempo": DAY_CATEGORY_CYCLE,
    "sweet_spot": DAY_CATEGORY_CYCLE,
    "threshold": DAY_CATEGORY_CYCLE,
    "vo2": DAY_CATEGORY_CYCLE,
    "strength": DAY_CATEGORY_WEIGHTS,
    "strength_maintenance": DAY_CATEGORY_WEIGHTS,
    "strength_recovery": DAY_CATEGORY_WEIGHTS,
    "mobility": DAY_CATEGORY_FLEXIBILITY,
    "flexibility": DAY_CATEGORY_FLEXIBILITY,
    "walk": DAY_CATEGORY_WALK,
    "walking": DAY_CATEGORY_WALK,
    "walk_recovery": DAY_CATEGORY_WALK,
    "deliberate_walk": DAY_CATEGORY_WALK,
}

WORKOUT_TYPES: frozenset[str] = frozenset(WORKOUT_TYPE_CATEGORY)

#: Retained because callers read them; derived from the one table so they cannot
#: drift from it.
WORKOUT_TYPE_CYCLE = {k for k, v in WORKOUT_TYPE_CATEGORY.items() if v == DAY_CATEGORY_CYCLE}
WORKOUT_TYPE_WEIGHTS = {k for k, v in WORKOUT_TYPE_CATEGORY.items() if v == DAY_CATEGORY_WEIGHTS}
WORKOUT_TYPE_FLEXIBILITY = {
    k for k, v in WORKOUT_TYPE_CATEGORY.items() if v == DAY_CATEGORY_FLEXIBILITY
}
WORKOUT_TYPE_WALK = {k for k, v in WORKOUT_TYPE_CATEGORY.items() if v == DAY_CATEGORY_WALK}


@dataclass(frozen=True)
class DayState:
    categories: list[str]
    label: str
    is_rest: bool


def category_for_workout_type(workout_type: str | None) -> str:
    """The one Python classifier. Mirrors ``categoryForWorkoutType`` exactly.

    The three prefix fallbacks are deliberate and are the same three TypeScript
    applies, so a ``bike_something_new`` reaching the column before the vocabulary
    catches up classifies identically on both sides rather than differently.
    Anything else is ``weights`` — the historical default, kept as the default on
    both sides so the two cannot diverge on the unknown case either.
    """
    value = (workout_type or "").strip().lower()
    known = WORKOUT_TYPE_CATEGORY.get(value)
    if known is not None:
        return known
    if value.startswith("bike_"):
        return DAY_CATEGORY_CYCLE
    if value.startswith("strength_"):
        return DAY_CATEGORY_WEIGHTS
    if value.startswith("walk_"):
        return DAY_CATEGORY_WALK
    return DAY_CATEGORY_WEIGHTS


def is_known_workout_type(value: str) -> bool:
    return value.strip().lower() in WORKOUT_TYPE_CATEGORY


def day_state_for_workout_types(workout_types: list[str]) -> DayState:
    categories: list[str] = []
    for workout_type in workout_types:
        category = category_for_workout_type(workout_type)
        if category not in categories:
            categories.append(category)
    if not categories:
        return DayState(categories=[DAY_CATEGORY_REST], label="Rest", is_rest=True)
    labels = {
        DAY_CATEGORY_CYCLE: "Cycle",
        DAY_CATEGORY_WEIGHTS: "Weights",
        DAY_CATEGORY_FLEXIBILITY: "Flexibility",
        DAY_CATEGORY_WALK: "Walk",
    }
    return DayState(
        categories=categories,
        label=" + ".join(labels[category] for category in categories),
        is_rest=False,
    )


def is_bike_workout_type(workout_type: str | None) -> bool:
    return category_for_workout_type(workout_type) == DAY_CATEGORY_CYCLE


def normalise_workout_type(value: str | None) -> str:
    """Coerce a written ``workout_type`` into the shared vocabulary.

    Batch 253 (CR236-05). Three writers put unvalidated text into this column, and
    one of them is the **model**: ``block_generator`` writes
    ``str(workout["workoutType"])`` straight from generated JSON. A value outside
    the vocabulary does not error anywhere — it silently classifies, possibly
    differently in each language, and the app and the coach then disagree about
    what kind of day it is.

    Normalising rather than rejecting is deliberate. A ``CHECK`` constraint was
    considered and **not** taken: its failure mode is a 500 during plan generation
    on a column ten call sites already read defensively, which is worse than the
    misclassification it would prevent. This coerces case and whitespace, keeps any
    value the vocabulary or its three prefixes recognise, and otherwise leaves the
    value intact so nothing is silently renamed — the classifier's shared default
    then applies identically on both sides.
    """
    normalised = (value or "").strip().lower()
    return normalised or "strength"
