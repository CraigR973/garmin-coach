"""Tests for the overnight bedroom-fan airflow control (Batch 27.2).

The pure decision core (``services/fan_control``) is exercised exhaustively across
window phases, thresholds, the speed ladder, hysteresis, and idempotency. The
scheduler integrator (``scheduler._apply_fan_control``) is tested with a fake
DreoFanClient so the command wiring and graceful degradation are covered without
network, a real fan, or a database.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

import pytest

from src import scheduler
from src.services.dreo_fan import DreoConnectionError, DreoFanState
from src.services.fan_control import (
    MAX_SPEED,
    FanState,
    decide_fan_action,
    loop_phase,
)

# -- loop_phase ------------------------------------------------------------


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (time(21, 30), "control"),  # window start (inclusive)
        (time(23, 0), "control"),
        (time(2, 0), "control"),  # wraps midnight
        (time(8, 29), "control"),
        (time(8, 30), "winddown"),  # window end -> wind-down
        (time(8, 59), "winddown"),
        (time(9, 0), "idle"),  # wind-down end (exclusive)
        (time(12, 0), "idle"),
        (time(21, 29), "idle"),  # just before the window
    ],
)
def test_loop_phase(now: time, expected: str) -> None:
    assert loop_phase(now) == expected


# -- decide_fan_action: phases & data --------------------------------------


def test_idle_never_acts() -> None:
    decision = decide_fan_action(
        phase="idle", temperature_c=25.0, fan_state=FanState(is_on=True, fan_speed=7)
    )
    assert decision.action == "idle"


def test_no_fresh_temperature_holds() -> None:
    decision = decide_fan_action(
        phase="control", temperature_c=None, fan_state=FanState(is_on=True, fan_speed=5)
    )
    assert decision.action == "no_data"
    assert decision.target_on is True  # holds current state, issues no command


def test_winddown_turns_a_running_fan_off() -> None:
    decision = decide_fan_action(
        phase="winddown", temperature_c=22.0, fan_state=FanState(is_on=True, fan_speed=5)
    )
    assert decision.action == "apply"
    assert decision.target_on is False


def test_winddown_holds_when_already_off() -> None:
    decision = decide_fan_action(
        phase="winddown", temperature_c=22.0, fan_state=FanState(is_on=False)
    )
    assert decision.action == "hold"
    assert decision.target_on is False


# -- decide_fan_action: thresholds & speed ladder --------------------------


def test_below_threshold_stays_off() -> None:
    decision = decide_fan_action(
        phase="control", temperature_c=18.0, fan_state=FanState(is_on=False)
    )
    assert decision.action == "hold"
    assert decision.target_on is False


def test_turns_on_at_threshold() -> None:
    decision = decide_fan_action(
        phase="control", temperature_c=19.5, fan_state=FanState(is_on=False)
    )
    assert decision.action == "apply"
    assert decision.target_on is True
    assert decision.target_speed == 3


@pytest.mark.parametrize(
    ("temperature_c", "expected_speed"),
    [
        (19.5, 3),
        (19.9, 3),
        (20.0, 5),
        (20.9, 5),
        (21.0, 7),
        (24.0, 7),  # bounded at MAX_SPEED, never the device max of 9
    ],
)
def test_speed_ladder_is_bounded(temperature_c: float, expected_speed: int) -> None:
    decision = decide_fan_action(
        phase="control", temperature_c=temperature_c, fan_state=FanState(is_on=False)
    )
    assert decision.target_on is True
    assert decision.target_speed == expected_speed
    assert decision.target_speed <= MAX_SPEED


# -- decide_fan_action: hysteresis -----------------------------------------


def test_hysteresis_does_not_turn_on_between_off_and_on_thresholds() -> None:
    # 19.2C is above the 19.0 off-threshold but below the 19.5 on-threshold: an
    # already-off fan must stay off (no flapping just under the on-threshold).
    decision = decide_fan_action(
        phase="control", temperature_c=19.2, fan_state=FanState(is_on=False)
    )
    assert decision.action == "hold"
    assert decision.target_on is False


def test_hysteresis_keeps_running_between_thresholds() -> None:
    # Same 19.2C, but the fan is already on: it keeps running until below 19.0.
    decision = decide_fan_action(
        phase="control", temperature_c=19.2, fan_state=FanState(is_on=True, fan_speed=3)
    )
    assert decision.action == "hold"
    assert decision.target_on is True


def test_drops_below_off_threshold_turns_off() -> None:
    decision = decide_fan_action(
        phase="control", temperature_c=18.9, fan_state=FanState(is_on=True, fan_speed=3)
    )
    assert decision.action == "apply"
    assert decision.target_on is False


# -- decide_fan_action: idempotency ----------------------------------------


def test_idempotent_when_already_at_target() -> None:
    decision = decide_fan_action(
        phase="control", temperature_c=20.0, fan_state=FanState(is_on=True, fan_speed=5)
    )
    assert decision.action == "hold"


def test_adjusts_speed_when_band_changes() -> None:
    decision = decide_fan_action(
        phase="control", temperature_c=20.0, fan_state=FanState(is_on=True, fan_speed=3)
    )
    assert decision.action == "apply"
    assert decision.target_speed == 5


# -- integrator: _fresh_temperature_c --------------------------------------


class _Reading:
    def __init__(self, temperature_c: float, captured_at_utc: datetime) -> None:
        self.temperature_c = temperature_c
        self.captured_at_utc = captured_at_utc


def test_fresh_temperature_c_returns_value_when_recent() -> None:
    now_local = datetime.now(UTC)
    reading = _Reading(20.04, now_local.replace(tzinfo=None))
    assert scheduler._fresh_temperature_c(reading, now_local) == 20.0  # rounded to 0.1


def test_fresh_temperature_c_drops_stale_reading() -> None:
    now_local = datetime.now(UTC)
    stale = _Reading(20.0, (now_local - timedelta(hours=2)).replace(tzinfo=None))
    assert scheduler._fresh_temperature_c(stale, now_local) is None


def test_fresh_temperature_c_handles_missing_reading() -> None:
    assert scheduler._fresh_temperature_c(None, datetime.now(UTC)) is None


# -- integrator: _apply_fan_control ----------------------------------------


class FakeFanClient:
    def __init__(
        self, *, is_on: bool = False, fan_speed: int = 7, connect_error: Exception | None = None
    ) -> None:
        self._state = DreoFanState(is_on=is_on, fan_speed=fan_speed, preset_mode="turbo")
        self._connect_error = connect_error
        self.calls: list[tuple] = []
        self.closed = False

    def connect(self) -> None:
        self.calls.append(("connect",))
        if self._connect_error is not None:
            raise self._connect_error

    def read_state(self) -> DreoFanState:
        return self._state

    def power(self, on: bool) -> None:
        self.calls.append(("power", on))

    def set_speed(self, speed: int) -> None:
        self.calls.append(("set_speed", speed))

    def close(self) -> None:
        self.closed = True


def _install_fake(monkeypatch: pytest.MonkeyPatch, fake: FakeFanClient) -> None:
    monkeypatch.setattr(scheduler, "DreoFanClient", lambda: fake)


async def test_apply_degrades_gracefully_when_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeFanClient(connect_error=DreoConnectionError("transport not ready"))
    _install_fake(monkeypatch, fake)
    # Must not raise; must not attempt any control command.
    await scheduler._apply_fan_control("control", 21.0)
    assert fake.calls == [("connect",)]


async def test_apply_turns_on_and_sets_speed(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeFanClient(is_on=False, fan_speed=7)
    _install_fake(monkeypatch, fake)
    await scheduler._apply_fan_control("control", 20.0)
    assert ("power", True) in fake.calls
    assert ("set_speed", 5) in fake.calls
    assert fake.closed


async def test_apply_is_idempotent_when_already_at_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeFanClient(is_on=True, fan_speed=5)
    _install_fake(monkeypatch, fake)
    await scheduler._apply_fan_control("control", 20.0)
    assert not any(call[0] in {"power", "set_speed"} for call in fake.calls)
    assert fake.closed


async def test_apply_winddown_turns_off(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeFanClient(is_on=True, fan_speed=5)
    _install_fake(monkeypatch, fake)
    await scheduler._apply_fan_control("winddown", None)
    assert ("power", False) in fake.calls
    assert ("set_speed", 5) not in fake.calls


# -- integrator: configuration gate ----------------------------------------


def test_fan_control_configured_reflects_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scheduler.settings, "dreo_username", "")
    monkeypatch.setattr(scheduler.settings, "dreo_password", "")
    monkeypatch.setattr(scheduler.settings, "dreo_token", "")
    assert scheduler._fan_control_configured() is False

    monkeypatch.setattr(scheduler.settings, "dreo_username", "mark@example.com")
    monkeypatch.setattr(scheduler.settings, "dreo_password", "pw")
    assert scheduler._fan_control_configured() is True
