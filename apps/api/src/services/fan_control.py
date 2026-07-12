"""Overnight bedroom-fan airflow control — pure decision core (Batch 27.2).

The Dreo air-circulator is not a thermostat (it cannot hold a setpoint), so this
maps the live indoor temperature onto a bounded fan target — off, or on at a
speed chosen from a small ladder — against the Batch 9 sleep-disruption
thresholds (19.5 C warning / 20.0 C critical; see
``nudge_alerts.evaluate_thermal_alert``).

This module is pure (no I/O) and exhaustively unit-tested, mirroring
``services/wake_detection.py``. The scheduler integrator
(``scheduler.run_fan_control``) reads the live temp + current fan state, calls
:func:`decide_fan_action`, and applies the result through ``DreoFanClient`` — only
the difference from the current state, so the loop is idempotent.

Design points:

- **Overnight only.** The fan auto-runs within an overnight window; a short
  wind-down just after it ensures a fan still running at wake is turned off,
  without the loop touching the cloud through the day. Outside both it is idle.
- **Hysteresis.** Turn on at :data:`ON_THRESHOLD_C`; once running, keep going
  until the room drops below :data:`OFF_THRESHOLD_C`, so the fan does not flap
  on/off around the threshold.
- **Bounded.** Speeds come from a fixed ladder capped at :data:`MAX_SPEED` (never
  the device maximum of 9), and the loop only ever issues on/off + speed.

The **calibration constants** below are tuned to Mark's documented sleep window and
the #87 wake distribution (median wake 08:22); retune them here if his schedule
shifts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from typing import Literal

Phase = Literal["control", "winddown", "idle"]
Action = Literal["apply", "hold", "no_data", "idle"]

# How often the overnight loop fires (minutes). The scheduler interval and the
# fan-state tick's timestamp quantisation share this single source of truth so a
# coalesced double-fire maps to one idempotent tick per slot (Batch 31).
INTERVAL_MIN = 15

# Overnight control window (profile-local time); wraps midnight.
WINDOW_START = time(21, 30)
WINDOW_END = time(8, 30)
# Wind-down: ensure the fan is off shortly after the window so it is never left
# running into the day (without the loop polling the cloud all day).
WINDDOWN_END = time(9, 0)

# Sleep-disruption thresholds (Batch 9; nudge_alerts.evaluate_thermal_alert).
ON_THRESHOLD_C = 19.5
# Hysteresis floor: once running, stay on until the room falls below this.
OFF_THRESHOLD_C = 19.0

# Temperature -> fan-speed ladder (device speed_range is (1, 9); kept gentle and
# bounded for overnight use). Each entry is (at-or-above C, speed).
SPEED_LADDER: tuple[tuple[float, int], ...] = (
    (19.5, 3),
    (20.0, 5),
    (21.0, 7),
)
# Safety bound: the overnight loop never drives the fan above this.
MAX_SPEED = 7


@dataclass(frozen=True)
class FanState:
    """The fan's currently reported control state."""

    is_on: bool
    fan_speed: int | None = None


@dataclass(frozen=True)
class FanDecision:
    """The target the loop should reconcile the fan to.

    ``action == "apply"`` means the fan differs from the target and should be
    driven to it; any other action is a no-op (the fan is left untouched).
    """

    action: Action
    target_on: bool
    target_speed: int | None
    reason: str


@dataclass(frozen=True)
class FanControlResult:
    """The outcome of one overnight fan-control fire, for persistence (Batch 31).

    ``action`` is a superset of :class:`FanDecision`'s action: it also carries the
    branch outcomes the scheduler resolves — ``auto_off`` (autopilot disabled),
    ``unreachable`` (cloud connect/command failed), and ``winddown`` (the morning
    shut-off) — so the chart can *explain* gaps rather than going blank.
    ``fan_on`` / ``fan_speed`` are the **effective** fan state after the tick, and
    are ``None`` when the fan was not read (auto off, or unreachable).
    """

    action: str
    observed_temp_c: float | None
    fan_on: bool | None
    fan_speed: int | None
    reason: str


@dataclass(frozen=True)
class FanIntent:
    """The autopilot's current intent, for read-only display in the UI."""

    auto_enabled: bool
    # "manual" (auto off) | "control" | "winddown" | "idle" (overnight phases).
    mode: str
    # The intended on/off; ``None`` means unknown — manual mode, or no fresh temp.
    is_on: bool | None
    speed: int | None
    responding_to_c: float | None
    next_on_local_time: str | None = None


def loop_phase(
    now: time,
    *,
    window_start: time = WINDOW_START,
    window_end: time = WINDOW_END,
    winddown_end: time = WINDDOWN_END,
) -> Phase:
    """Classify the loop phase from the profile-local time of day.

    The control window wraps midnight (e.g. 21:30 -> 08:30); the wind-down is the
    short tail after it (08:30 -> 09:00).
    """
    if _in_overnight_window(now, window_start, window_end):
        return "control"
    if window_end <= now < winddown_end:
        return "winddown"
    return "idle"


def decide_fan_action(
    *,
    phase: Phase,
    temperature_c: float | None,
    fan_state: FanState,
    on_threshold_c: float = ON_THRESHOLD_C,
    off_threshold_c: float = OFF_THRESHOLD_C,
    max_speed: int = MAX_SPEED,
) -> FanDecision:
    """Decide the fan target for the current phase, temperature, and fan state.

    Idempotent: returns ``action="hold"`` when the fan already matches the target.
    """
    if phase == "idle":
        return FanDecision("idle", fan_state.is_on, fan_state.fan_speed, "outside overnight window")

    if phase == "winddown":
        return _reconcile(
            fan_state, target_on=False, target_speed=None, reason="winddown: ensure off"
        )

    # phase == "control"
    if temperature_c is None:
        # No fresh indoor temperature — never actuate blind; hold the current state.
        return FanDecision(
            "no_data", fan_state.is_on, fan_state.fan_speed, "no fresh indoor temperature"
        )

    # Hysteresis: the on/off boundary depends on whether the fan is already running.
    if fan_state.is_on:
        target_on = temperature_c >= off_threshold_c
    else:
        target_on = temperature_c >= on_threshold_c

    if not target_on:
        return _reconcile(
            fan_state,
            target_on=False,
            target_speed=None,
            reason=f"{temperature_c:.1f}C below threshold",
        )

    target_speed = _speed_for_temp(temperature_c, max_speed)
    return _reconcile(
        fan_state,
        target_on=True,
        target_speed=target_speed,
        reason=f"{temperature_c:.1f}C -> speed {target_speed}",
    )


def describe_fan_intent(now: time, temperature_c: float | None, *, auto_enabled: bool) -> FanIntent:
    """The autopilot's current intent for display — pure, no I/O, no hysteresis.

    Reuses :func:`loop_phase` + :func:`decide_fan_action` against a fresh (off)
    baseline so the card shows whether the loop wants the fan on right now and at
    what speed, without reading the device. ``is_on`` is ``None`` when the answer
    is unknown — manual mode (auto off) or no fresh indoor temperature.
    """
    if not auto_enabled:
        return FanIntent(False, "manual", None, None, temperature_c, next_on_local_time=None)
    phase = loop_phase(now)
    if phase == "idle":
        return FanIntent(
            True,
            "idle",
            False,
            None,
            temperature_c,
            next_on_local_time=_format_time(WINDOW_START),
        )
    if temperature_c is None:
        return FanIntent(True, phase, None, None, None, next_on_local_time=None)
    decision = decide_fan_action(
        phase=phase, temperature_c=temperature_c, fan_state=FanState(is_on=False)
    )
    return FanIntent(
        True,
        phase,
        decision.target_on,
        decision.target_speed,
        temperature_c,
        next_on_local_time=None,
    )


def _reconcile(
    fan_state: FanState, *, target_on: bool, target_speed: int | None, reason: str
) -> FanDecision:
    matches = fan_state.is_on == target_on and (
        not target_on or fan_state.fan_speed == target_speed
    )
    action: Action = "hold" if matches else "apply"
    return FanDecision(action, target_on, target_speed, reason)


def _speed_for_temp(temperature_c: float, max_speed: int) -> int:
    speed = SPEED_LADDER[0][1]
    for lower_bound, ladder_speed in SPEED_LADDER:
        if temperature_c >= lower_bound:
            speed = ladder_speed
    return min(speed, max_speed)


def _in_overnight_window(now: time, start: time, end: time) -> bool:
    if start <= end:
        return start <= now < end
    return now >= start or now < end  # wraps midnight


def _format_time(value: time) -> str:
    return value.strftime("%H:%M")
