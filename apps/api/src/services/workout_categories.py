from __future__ import annotations

from dataclasses import dataclass

DAY_CATEGORY_CYCLE = "cycle"
DAY_CATEGORY_WEIGHTS = "weights"
DAY_CATEGORY_FLEXIBILITY = "flexibility"
DAY_CATEGORY_REST = "rest"

WORKOUT_TYPE_CYCLE = {
    "bike_vo2",
    "bike_sweet_spot",
    "bike_threshold",
    "bike_tempo",
    "bike_endurance",
    "bike_recovery",
}
WORKOUT_TYPE_WEIGHTS = {"strength_recovery", "strength_maintenance"}
WORKOUT_TYPE_FLEXIBILITY = {"mobility"}


@dataclass(frozen=True)
class DayState:
    categories: list[str]
    label: str
    is_rest: bool


def category_for_workout_type(workout_type: str | None) -> str:
    value = (workout_type or "").strip().lower()
    if value in WORKOUT_TYPE_CYCLE or value.startswith("bike_"):
        return DAY_CATEGORY_CYCLE
    if value in WORKOUT_TYPE_WEIGHTS or value.startswith("strength_"):
        return DAY_CATEGORY_WEIGHTS
    if value in WORKOUT_TYPE_FLEXIBILITY:
        return DAY_CATEGORY_FLEXIBILITY
    return DAY_CATEGORY_WEIGHTS


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
    }
    return DayState(
        categories=categories,
        label=" + ".join(labels[category] for category in categories),
        is_rest=False,
    )


def is_bike_workout_type(workout_type: str | None) -> bool:
    return category_for_workout_type(workout_type) == DAY_CATEGORY_CYCLE
