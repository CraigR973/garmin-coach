"""Batch 231: a lever Mark already keeps is not an intervention, it is a description."""

from __future__ import annotations

from datetime import date, timedelta

from src.services.coaching_state import KB_SECTION_BUILDERS
from src.services.experiment_evaluation import REM_MIN_PER_RESPONSE
from src.services.rem_interventions import REM_LIBRARY, select_rem_interventions
from src.services.standing_habits import (
    SECTION,
    complied_intervention_ids,
    habit_statements,
    standing_habits_content,
)

_MONDAY = date(2026, 8, 24)

# What Mark actually told the coach, four times over, in his own words. The
# statement is provenance; only ``interventionIds`` changes behaviour.
_ALCOHOL_HABIT = {
    "habits": [
        {
            "id": "rarely-drinks",
            "statement": (
                "Rarely drinks — social occasions perhaps six times a year, "
                "and a couple of drinks on holiday."
            ),
            "interventionIds": ["alcohol_free_evenings"],
            "recordedOn": "2026-08-28",
            "source": "coach chat 2026-08-08 / 2026-08-20",
        }
    ]
}


def test_the_section_is_seeded_empty() -> None:
    """A habit that suppresses advice is a human's call, never the seed's."""
    assert SECTION in KB_SECTION_BUILDERS
    assert standing_habits_content() == {"habits": []}
    assert complied_intervention_ids(standing_habits_content()) == frozenset()


def test_a_malformed_section_suppresses_nothing() -> None:
    for section in (None, {}, {"habits": "yes"}, {"habits": [None, 7]}, {"habits": [{}]}):
        assert complied_intervention_ids(section) == frozenset()  # type: ignore[arg-type]
    assert complied_intervention_ids({"habits": [{"interventionIds": ["", "  "]}]}) == frozenset()


def test_recorded_habits_are_readable_back() -> None:
    assert complied_intervention_ids(_ALCOHOL_HABIT) == frozenset({"alcohol_free_evenings"})
    assert habit_statements(_ALCOHOL_HABIT)[0].startswith("Rarely drinks")


def test_a_lever_he_already_complies_with_is_never_issued() -> None:
    """The whole library is walked and the complied lever never appears.

    Weekly rotation means a single week proves nothing — the blind cycle reaches
    every lever eventually, which is exactly how ``alcohol_free_evenings`` would
    resurface.
    """
    complied = complied_intervention_ids(_ALCOHOL_HABIT)
    for week in range(len(REM_LIBRARY) * 2):
        _, rotation = select_rem_interventions(
            as_of=_MONDAY + timedelta(days=7 * week),
            complied_intervention_ids=complied,
        )
        assert "alcohol_free_evenings" not in rotation.intervention_ids


def test_the_card_reports_the_library_it_can_actually_offer() -> None:
    """ "2 of 12" would be a false count once two levers are suppressed."""
    complied = frozenset({"alcohol_free_evenings", "evening_light_down"})
    _, rotation = select_rem_interventions(as_of=_MONDAY, complied_intervention_ids=complied)
    assert rotation.total == len(REM_LIBRARY) - 2
    assert rotation.shown == 2


def test_a_driver_pinned_lever_is_still_suppressed_when_he_complies() -> None:
    """Driver affinity must not smuggle a complied lever back in.

    ``late_training_guard`` is pinned by a ``prev_day_training_load`` driver, and
    it is one of the two levers Mark could never answer differently.
    """
    complied = frozenset({"late_training_guard"})
    for week in range(len(REM_LIBRARY)):
        actions, rotation = select_rem_interventions(
            as_of=_MONDAY + timedelta(days=7 * week),
            driver_key="prev_day_training_load",
            complied_intervention_ids=complied,
        )
        assert "late_training_guard" not in rotation.intervention_ids
        assert all("late rides" not in action for action in actions)


def test_suppressing_almost_everything_still_returns_a_valid_rotation() -> None:
    keep = "wake_time_anchor"
    complied = frozenset(item.id for item in REM_LIBRARY if item.id != keep)
    actions, rotation = select_rem_interventions(as_of=_MONDAY, complied_intervention_ids=complied)
    assert rotation.intervention_ids == (keep,)
    assert rotation.total == 1
    assert rotation.shown == len(actions) == 1


def test_suppressing_the_whole_library_issues_nothing() -> None:
    complied = frozenset(item.id for item in REM_LIBRARY)
    actions, rotation = select_rem_interventions(as_of=_MONDAY, complied_intervention_ids=complied)
    assert actions == []
    assert rotation.intervention_ids == ()
    assert rotation.total == 0


def test_the_experiment_can_only_conclude_on_levers_that_are_still_asked() -> None:
    """Why this exists at all, stated as a test.

    The evaluator needs ``REM_MIN_PER_RESPONSE`` applied *and* not-applied nights
    per intervention. A lever he always keeps can never produce a not-applied
    night, so it would be asked forever and concluded never. Suppression is what
    makes the comparison reachable.
    """
    assert REM_MIN_PER_RESPONSE >= 1
    complied = complied_intervention_ids(_ALCOHOL_HABIT)
    issued: set[str] = set()
    for week in range(len(REM_LIBRARY)):
        _, rotation = select_rem_interventions(
            as_of=_MONDAY + timedelta(days=7 * week),
            complied_intervention_ids=complied,
        )
        issued.update(rotation.intervention_ids)
    assert issued and not issued & complied


def test_a_stored_assignment_reports_the_library_it_was_issued_from() -> None:
    """A historical "2 of N" must not silently re-count against today's library."""
    import uuid

    from src.services.experiment_loop import RemAssignment, rotation_from_assignment

    issued = RemAssignment(
        analysis_id=uuid.uuid4(),
        period_label="2026-W35",
        window_start=_MONDAY,
        window_end=_MONDAY + timedelta(days=6),
        interventions=({"id": "wake_time_anchor", "action": "Hold your wake time steady."},),
        library_total=11,
    )
    rotation = rotation_from_assignment(issued)
    assert rotation is not None
    assert rotation.total == 11

    # A row written before Batch 231 carries no count; the library was whole then.
    pre_231 = RemAssignment(
        analysis_id=uuid.uuid4(),
        period_label="2026-W34",
        window_start=_MONDAY - timedelta(days=7),
        window_end=_MONDAY - timedelta(days=1),
        interventions=({"id": "wake_time_anchor", "action": "Hold your wake time steady."},),
    )
    pre_rotation = rotation_from_assignment(pre_231)
    assert pre_rotation is not None
    assert pre_rotation.total == len(REM_LIBRARY)
