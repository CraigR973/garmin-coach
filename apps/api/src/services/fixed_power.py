"""The fixed-power check: his heart rate at a steady power, read from a ride (Batch 322).

The HRV-guided and progression literature reads aerobic fitness most cleanly from heart
rate at a fixed power: the same watts for the same minutes, ridden in ERG so the power
does not wander. His mid-week Zone 2 ride is exactly that (a 35- to 55-minute block at
65-67% FTP in ERG), so the check needs no new session: every such ride carries one.

:func:`fixed_power_check` finds the ride's longest steady block of at least
:data:`MIN_MINUTES` and reports its power, heart rate and drift. It reads the
``intervals`` a post-ride read already stores, so the same function reads rides stored
before it existed (Batch 319's drift reads them). Pure.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Final

#: The shortest block that counts: the 20 minutes the row names.
MIN_MINUTES: Final = 20
#: Zone 2 or under: above it heart rate drifts for reasons other than fitness.
MAX_PCT_FTP: Final = 76
#: A block whose average sits more than this far from its own target was not held in ERG.
MAX_TARGET_GAP_PCT: Final = 4


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def fixed_power_check(intervals: Sequence[Mapping[str, Any]] | None) -> dict[str, Any] | None:
    """The ride's fixed-power check, or ``None`` when no block qualifies."""

    best: Mapping[str, Any] | None = None
    best_minutes = 0.0
    for interval in intervals or []:
        if not isinstance(interval, Mapping):
            continue
        seconds = _number(interval.get("durationSec"))
        power = _number(interval.get("avgPowerWatts"))
        heart = _number(interval.get("avgHeartRateBpm"))
        pct = _number(interval.get("pctFtp"))
        low = _number(interval.get("targetPctFtpLow"))
        high = _number(interval.get("targetPctFtpHigh"))
        if None in (seconds, power, heart, pct, low, high):
            continue
        assert seconds is not None and pct is not None and low is not None and high is not None
        minutes = seconds / 60
        steady_target = abs(high - low) <= 2  # a steady step, not a ramp
        held = abs(pct - (low + high) / 2) <= MAX_TARGET_GAP_PCT
        if minutes >= MIN_MINUTES and pct <= MAX_PCT_FTP and steady_target and held:
            if minutes > best_minutes:
                best, best_minutes = interval, minutes
    if best is None:
        return None
    return {
        "minutes": round(best_minutes, 1),
        "powerWatts": round(float(best["avgPowerWatts"]), 1),
        "pctFtp": best.get("pctFtp"),
        "avgHeartRateBpm": best.get("avgHeartRateBpm"),
        "hrDriftPct": best.get("hrDriftPct"),
        "label": best.get("label"),
    }
