"""Batch 253 (CR236-05): one workout-type vocabulary, in two languages.

``PlannedWorkout.workout_type`` is unconstrained free text that **ten** separate
pieces of code classified — nine in Python, one in TypeScript — with the two
languages implementing different rules: explicit sets plus prefixes here, regexes
there. They disagreed for values the app's own label map lists.

The divergence was latent, not live: production holds seven values and all seven
classify identically. It becomes live the moment the block generator, the quick-add
sheet or a hand-authored plan writes an eighth — and the symptom is the app and the
coach disagreeing about what kind of day it is, with no error anywhere.

This test reads the TypeScript table directly rather than restating it, so a value
added on one side and not the other fails CI.
"""

from __future__ import annotations

import re
from pathlib import Path

from src.services.workout_categories import (
    WORKOUT_TYPE_CATEGORY,
    category_for_workout_type,
    is_known_workout_type,
)

SHARED_TABLE = Path(__file__).parents[3] / "packages" / "shared" / "src" / "workoutTypes.ts"


def _typescript_vocabulary() -> dict[str, str]:
    source = SHARED_TABLE.read_text(encoding="utf-8")
    body = source[
        source.index("export const WORKOUT_TYPE_CATEGORY = {") : source.index(
            "} as const satisfies"
        )
    ]
    return {key: value for key, value in re.findall(r"^\s{2}(\w+):\s*'(\w+)',", body, re.M)}


def test_the_two_languages_classify_the_same_vocabulary_identically() -> None:
    assert _typescript_vocabulary() == WORKOUT_TYPE_CATEGORY


def test_the_four_values_that_used_to_diverge_now_agree() -> None:
    # ``flexibility`` and ``deliberate_walk`` were ``weights`` here and
    # ``flexibility``/``walk`` in the app; a bare ``vo2``/``endurance`` was
    # ``weights`` here and ``cycle`` there.
    assert category_for_workout_type("flexibility") == "flexibility"
    assert category_for_workout_type("deliberate_walk") == "walk"
    assert category_for_workout_type("vo2") == "cycle"
    assert category_for_workout_type("endurance") == "cycle"


def test_the_seven_values_production_actually_holds_are_unchanged() -> None:
    """Measured against production on 2026-09-04, not assumed.

    The finding recorded four; there are seven. All seven classified identically
    before this change and must still, or the vocabulary has silently re-labelled
    Mark's existing plan.
    """
    assert {
        "bike_endurance": "cycle",
        "strength_maintenance": "weights",
        "bike_vo2": "cycle",
        "bike_sweet_spot": "cycle",
        "mobility": "flexibility",
        "strength_recovery": "weights",
        "bike_recovery": "cycle",
    } == {
        value: category_for_workout_type(value)
        for value in (
            "bike_endurance",
            "strength_maintenance",
            "bike_vo2",
            "bike_sweet_spot",
            "mobility",
            "strength_recovery",
            "bike_recovery",
        )
    }


def test_the_prefix_fallbacks_match_the_typescript_ones() -> None:
    assert category_for_workout_type("bike_something_new") == "cycle"
    assert category_for_workout_type("strength_something_new") == "weights"
    assert category_for_workout_type("walk_something_new") == "walk"


def test_an_unknown_value_defaults_to_weights_on_both_sides() -> None:
    assert category_for_workout_type("kayaking") == "weights"
    assert category_for_workout_type(None) == "weights"
    assert category_for_workout_type("") == "weights"


def test_case_and_space_are_normalised() -> None:
    assert category_for_workout_type("  BIKE_VO2  ") == "cycle"


def test_membership_is_answerable() -> None:
    assert is_known_workout_type("bike_vo2")
    assert not is_known_workout_type("kayaking")
