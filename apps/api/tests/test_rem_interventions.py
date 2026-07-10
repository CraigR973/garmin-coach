from __future__ import annotations

from datetime import date, timedelta

from src.services.rem_interventions import (
    REM_LIBRARY,
    REM_ROTATION_WINDOW,
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
