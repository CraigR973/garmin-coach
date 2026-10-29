"""Garmin's training-readiness factors, kept with each morning (Batch 322).

Garmin's readiness score is built from six factors (sleep last night, recovery time, the
acute load ratio, HRV, sleep history and stress history), each a percentage of its best
with a short feedback word. The sync has stored the whole payload in
``daily_metrics.raw_payload["training_readiness"]`` since Batch 205, but no morning kept
the factors, so no review could ask which one moved his readiness. The morning packet now
keeps them, as Garmin gave them. Pure.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

#: Garmin's factor names, and the packet's.
FACTORS: Final = (
    ("sleepScore", "sleep"),
    ("recoveryTime", "recoveryTime"),
    ("acwr", "loadRatio"),
    ("hrv", "hrv"),
    ("sleepHistory", "sleepHistory"),
    ("stressHistory", "stressHistory"),
)


def readiness_factors(raw_payload: Any) -> dict[str, Any] | None:
    """The six factors from a daily row's raw payload, or ``None`` when Garmin gave none."""

    if not isinstance(raw_payload, Mapping):
        return None
    readiness = raw_payload.get("training_readiness")
    if isinstance(readiness, list):
        readiness = readiness[0] if readiness else None
    if not isinstance(readiness, Mapping):
        return None
    factors = {
        name: {
            "percent": readiness.get(f"{garmin}FactorPercent"),
            "feedback": readiness.get(f"{garmin}FactorFeedback"),
        }
        for garmin, name in FACTORS
        if readiness.get(f"{garmin}FactorPercent") is not None
    }
    if not factors:
        return None
    return {
        "score": readiness.get("score"),
        "level": readiness.get("level"),
        "factors": factors,
        "source": "Garmin training readiness, as Garmin gave it",
    }
