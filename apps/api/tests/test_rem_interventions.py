from __future__ import annotations

from datetime import date, timedelta

from src.services.rem_interventions import (
    REM_LIBRARY,
    REM_ROTATION_WINDOW,
    STRONG_GRADES,
    select_rem_interventions,
)

# 2026-07-06 is a Monday, so week-anchored rotation is easy to reason about.
_MONDAY = date(2026, 7, 6)


def test_library_has_unique_ids_and_renders() -> None:
    ids = [item.id for item in REM_LIBRARY]
    assert len(ids) == len(set(ids))
    assert len(REM_LIBRARY) >= 8  # broad enough to rotate, not a static pair
    # Every template renders with default params (no missing placeholder).
    for week in range(len(REM_LIBRARY)):
        actions, _ = select_rem_interventions(as_of=_MONDAY + timedelta(days=7 * week))
        assert all(action for action in actions)


def test_rotation_is_stable_within_a_calendar_week() -> None:
    monday, sunday = _MONDAY, _MONDAY + timedelta(days=6)
    assert select_rem_interventions(as_of=monday) == select_rem_interventions(as_of=sunday)


def test_rotation_carries_stable_ids_for_the_exact_rendered_actions() -> None:
    actions, rotation = select_rem_interventions(as_of=_MONDAY)

    assert len(rotation.intervention_ids) == len(actions) == rotation.shown
    assert len(set(rotation.intervention_ids)) == rotation.shown
    assert list(rotation.actions) == actions
    assert rotation.to_dict()["interventionIds"] == list(rotation.intervention_ids)


def test_rotation_walks_whole_library_before_repeating() -> None:
    weeks = len(REM_LIBRARY) // REM_ROTATION_WINDOW
    shown: list[tuple[str, ...]] = []
    for week in range(weeks):
        actions, rotation = select_rem_interventions(as_of=_MONDAY + timedelta(days=7 * week))
        assert rotation.shown == REM_ROTATION_WINDOW
        assert rotation.total == len(REM_LIBRARY)
        shown.append(tuple(actions))

    # Consecutive weeks never repeat an intervention...
    for earlier, later in zip(shown, shown[1:], strict=False):
        assert set(earlier).isdisjoint(later)
    # ...and one full cycle covers every lever exactly once.
    flat = [action for week in shown for action in week]
    assert len(set(flat)) == len(REM_LIBRARY)
    # The cycle wraps back to the start.
    wrapped, _ = select_rem_interventions(as_of=_MONDAY + timedelta(days=7 * weeks))
    assert tuple(wrapped) == shown[0]


def test_measured_driver_pins_its_intervention_every_week() -> None:
    # A thermal driver should always surface the room-temperature REM lever,
    # even in weeks the blind rotation would not have reached it.
    for week in range(len(REM_LIBRARY)):
        as_of = _MONDAY + timedelta(days=7 * week)
        actions, rotation = select_rem_interventions(
            as_of=as_of, driver_key="bedroom_critical_minutes"
        )
        assert rotation.shown == REM_ROTATION_WINDOW
        assert any("pre-cool to" in action for action in actions)


def test_driver_bias_does_not_duplicate_when_already_scheduled() -> None:
    # Find the week whose blind rotation already contains the thermal lever, then
    # confirm the driver bias leaves it unchanged (no duplicate, window preserved).
    for week in range(len(REM_LIBRARY)):
        as_of = _MONDAY + timedelta(days=7 * week)
        blind, _ = select_rem_interventions(as_of=as_of)
        if any("pre-cool to" in action for action in blind):
            biased, _ = select_rem_interventions(as_of=as_of, driver_key="overnight_low_c")
            assert biased == blind
            break


def test_protocol_values_render_into_templates() -> None:
    actions, _ = select_rem_interventions(
        as_of=_MONDAY,
        protocol={"preCoolTemperatureC": 16, "sealTargetTime": "21:45"},
        driver_key="overnight_low_c",
    )
    room = next(action for action in actions if "pre-cool to" in action)
    assert "16°C" in room
    assert "21:45" in room


# ---------------------------------------------------------------------------
# Batch 250 (HS240-10): the library stops speaking about all twelve in one voice
# ---------------------------------------------------------------------------


def test_every_lever_carries_a_graded_mechanism_and_a_reason() -> None:
    """A lever added without grading it must not inherit A-grade authority.

    The field defaults to ``C`` for exactly that reason, and the note exists so a
    future reader does not have to re-derive the grade from the literature.
    """
    for item in REM_LIBRARY:
        assert item.evidence_grade in {"A", "B", "C", "D"}
        assert item.grade_note.strip(), item.id


def test_the_four_invented_mechanisms_no_longer_state_a_rem_claim() -> None:
    """HS240-10 graded these four D or C on the *mechanism*, not the action.

    None is deleted — several are good sleep hygiene — but the sentence that told
    Mark something untrue about his own body is gone in each case: caffeine does
    not measurably cut REM, breathing routines have no REM evidence, late meals do
    not warm the core through the early morning, and stress is classically linked
    to *shorter* REM latency, not less REM.
    """
    by_id = {item.id: item for item in REM_LIBRARY}

    assert "quietly delays and thins REM" not in by_id["caffeine_cutoff"].template
    assert "total sleep and deep sleep" in by_id["caffeine_cutoff"].template

    assert "more than to any single trick" not in by_id["wind_down_consistency"].template
    assert "untested" in by_id["wind_down_consistency"].template

    assert "warms your core" not in by_id["late_meal_timing"].template
    assert "not established" in by_id["late_meal_timing"].template

    assert "preferentially eats REM" not in by_id["stress_offload"].template

    # REM has no depth dimension, so "shallower" was describing nothing.
    assert "shallower" not in by_id["evening_light_down"].template

    # The dose claim outran the evidence: low-dose REM effects are inconsistent.
    assert "even one drink" not in by_id["alcohol_free_evenings"].template

    # Evening exercise does not harm sleep except very close to bed.
    assert "hard or late rides off the evening" not in by_id["late_training_guard"].template
    assert "within an hour of bed" in by_id["late_training_guard"].template


def test_the_two_levers_marks_own_data_confirms_are_graded_a() -> None:
    """Batch 250 measured the back-loading mechanism directly: Q4 carries 50.9%."""
    by_id = {item.id: item for item in REM_LIBRARY}
    assert by_id["wake_time_anchor"].evidence_grade == "A"
    assert by_id["protect_last_cycle"].evidence_grade == "A"
    assert "50.9%" in by_id["protect_last_cycle"].grade_note


def test_every_week_carries_at_least_one_established_mechanism() -> None:
    """The rotation was blind, so a week could be two invented mechanisms.

    Strong and weak levers now rotate on separate cursors, filled strong-first.
    Checked across a full cycle and then some, so no week is exempt.
    """
    for week in range(len(REM_LIBRARY) + 2):
        _, rotation = select_rem_interventions(as_of=_MONDAY + timedelta(days=7 * week))
        grades = rotation.to_dict()["evidenceGrades"]
        assert grades, rotation.period_label
        assert any(grade in STRONG_GRADES for grade in grades.values()), rotation.period_label


def test_the_rotation_still_walks_every_lever_before_repeating() -> None:
    """Biasing toward the strong levers must not silently retire the weak ones.

    They were re-worded, not deleted: the action in each is sensible even where
    its REM mechanism was not.
    """
    weeks = len(REM_LIBRARY) // REM_ROTATION_WINDOW
    seen: set[str] = set()
    for week in range(weeks):
        _, rotation = select_rem_interventions(as_of=_MONDAY + timedelta(days=7 * week))
        seen.update(rotation.intervention_ids)
    assert seen == {item.id for item in REM_LIBRARY}


def test_a_library_with_no_strong_levers_still_rotates() -> None:
    """Standing habits can remove every A and B lever; the weak ones must still run."""
    strong_ids = frozenset(item.id for item in REM_LIBRARY if item.evidence_grade in STRONG_GRADES)
    actions, rotation = select_rem_interventions(
        as_of=_MONDAY, complied_intervention_ids=strong_ids
    )
    assert actions
    assert rotation.total == len(REM_LIBRARY) - len(strong_ids)
    assert set(rotation.intervention_ids).isdisjoint(strong_ids)
