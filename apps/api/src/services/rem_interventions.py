"""Rotating REM-intervention library (Batch 72).

Mark's REM has run low since he got the watch, so the Batch 59 chronic-pattern
card surfaces a REM flag most weeks — but it only ever showed the same two static
lines. This module gives a persistent REM miss a *broader* set of grounded
interventions and hands out only **one or two at a time**, rotated
deterministically week to week so the advice stays focused rather than a static
list he has already read.

It is pure and stateless: the rotation is seeded from the calendar week, so a
given week always yields the same pair (stable within the week, advancing across
weeks) with no persisted cursor and no migration. A measured sleep driver can
bias the week's selection toward the intervention it implicates, keeping the set
responsive to his real data rather than a blind cycle.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

REM_ROTATION_WINDOW = 2


@dataclass(frozen=True)
class RemIntervention:
    """One grounded REM lever. ``template`` may reference sleep-protocol values."""

    id: str
    template: str
    driver_affinity: frozenset[str] = frozenset()


@dataclass(frozen=True)
class RemRotation:
    """How the week's focused set sits inside the wider rotating library."""

    period_label: str
    shown: int
    total: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "periodLabel": self.period_label,
            "shown": self.shown,
            "total": self.total,
        }


# Ordered so consecutive weeks walk through the whole library before repeating.
# Each entry is REM-specific: REM concentrates in the last cycles of the night
# and is fragile to short sleep, alcohol, warmth, late stimulation, and circadian
# drift — the levers below all target one of those.
REM_LIBRARY: tuple[RemIntervention, ...] = (
    RemIntervention(
        id="wake_time_anchor",
        template=(
            "Hold your wake time steady (±30 min) all week — REM loads into the last "
            "cycles, so a fixed wake time protects it most."
        ),
    ),
    RemIntervention(
        id="protect_last_cycle",
        template=(
            "Skip early alarms after a late night; the final 90-minute cycle is the "
            "most REM-rich, so it is the first thing an early wake-up cuts."
        ),
    ),
    RemIntervention(
        id="bedtime_hard_stop",
        template=(
            "Treat {bedtime} as a hard lights-out this week, not a target — REM only "
            "rebounds when the night is long enough to reach it."
        ),
    ),
    RemIntervention(
        id="alcohol_free_evenings",
        template=(
            "Keep the evening alcohol-free before priority nights; even one drink "
            "suppresses first-half REM and fragments the rest."
        ),
    ),
    RemIntervention(
        id="caffeine_cutoff",
        template=(
            "Pull your last caffeine back to early afternoon — its long half-life "
            "quietly delays and thins REM hours later."
        ),
    ),
    RemIntervention(
        id="room_cool_late_cycles",
        template=(
            "Hold the room cool into the early morning (pre-cool to {preCoolTemperatureC}°C, "
            "seal by {sealTargetTime}) — warmth in the back half of the night is when "
            "REM gets disrupted."
        ),
        driver_affinity=frozenset(
            {
                "bedroom_warning_minutes",
                "bedroom_critical_minutes",
                "bedroom_fan_ran_minutes",
                "bedroom_peak_fan_speed",
                "overnight_low_c",
            }
        ),
    ),
    RemIntervention(
        id="evening_light_down",
        template=(
            "Dim screens and overhead lights in the last hour before bed; late bright "
            "light pushes REM later and shallower."
        ),
    ),
    RemIntervention(
        id="wind_down_consistency",
        template=(
            "Run the same wind-down every night (coherence breathing at "
            "{coherenceBreathingTime}) — REM responds to a steady routine more than to "
            "any single trick."
        ),
        driver_affinity=frozenset({"daytime_stress_avg", "sleep_stress_avg"}),
    ),
    RemIntervention(
        id="late_meal_timing",
        template=(
            "Finish the last real food by {latestSnackTime}; late digestion warms your "
            "core through the REM-heavy early morning."
        ),
    ),
    RemIntervention(
        id="stress_offload",
        template=(
            "On busy days, write tomorrow's list down before bed — unresolved stress "
            "preferentially eats REM."
        ),
        driver_affinity=frozenset({"daytime_stress_avg", "sleep_stress_avg"}),
    ),
    RemIntervention(
        id="rem_rebound_recovery",
        template=(
            "After a short or broken night, protect the next full night rather than "
            "catching up early; REM rebounds when you give it the back end of a normal "
            "sleep."
        ),
    ),
    RemIntervention(
        id="late_training_guard",
        template=(
            "Keep hard or late rides off the evening before a priority night — an "
            "activated, warm nervous system delays REM onset."
        ),
        driver_affinity=frozenset({"prev_day_training_load", "resting_heart_rate_bpm"}),
    ),
)

_DEFAULT_PARAMS: dict[str, str] = {
    "bedtime": "23:15",
    "sealTargetTime": "22:00",
    "coherenceBreathingTime": "20:00",
    "latestSnackTime": "21:30",
    "preCoolTemperatureC": "17",
}


def _params(protocol: Mapping[str, Any] | None) -> dict[str, str]:
    params = dict(_DEFAULT_PARAMS)
    if protocol:
        for key in params:
            value = protocol.get(key)
            if isinstance(value, str | int | float):
                params[key] = str(value)
    return params


def render(intervention: RemIntervention, params: Mapping[str, str]) -> str:
    return intervention.template.format(**params)


def _week_period(as_of: date) -> tuple[int, date]:
    """Monotonic week index + the ISO Monday, so a whole Mon–Sun week is stable."""
    monday = as_of - timedelta(days=as_of.weekday())
    return monday.toordinal() // 7, monday


def select_rem_interventions(
    *,
    as_of: date,
    protocol: Mapping[str, Any] | None = None,
    driver_key: str | None = None,
    window: int = REM_ROTATION_WINDOW,
    library: tuple[RemIntervention, ...] = REM_LIBRARY,
) -> tuple[list[str], RemRotation]:
    """Pick the week's focused REM set, rotated deterministically over ``library``.

    The rotation walks ``window`` fresh interventions each week, cycling through the
    whole library before repeating. A measured ``driver_key`` biases the week toward
    the lever it implicates (pinned first, keeping the window size), so a thermal or
    load signal surfaces its REM intervention even if the blind rotation had not
    reached it this week.
    """
    total = len(library)
    if total == 0:
        _, monday = _week_period(as_of)
        return [], RemRotation(period_label=_period_label(monday), shown=0, total=0)
    window = max(1, min(window, total))
    period, monday = _week_period(as_of)
    start = (period * window) % total
    chosen = [library[(start + offset) % total] for offset in range(window)]

    if driver_key is not None:
        affine = next(
            (item for item in library if driver_key in item.driver_affinity),
            None,
        )
        if affine is not None and affine.id not in {item.id for item in chosen}:
            chosen = [affine, *chosen][:window]

    params = _params(protocol)
    actions = [render(item, params) for item in chosen]
    return actions, RemRotation(period_label=_period_label(monday), shown=len(actions), total=total)


def _period_label(monday: date) -> str:
    iso = monday.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"
