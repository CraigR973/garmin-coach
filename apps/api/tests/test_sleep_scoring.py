"""Tests for the age-adjusted sleep score (services/sleep_scoring.py).

Covers the credit model chosen at /batch-start (Batch 61, DECISIONS #135): it
lifts Garmin's raw score only for stages that are age-appropriate but scored
against a young-adult target, and it does so under two structural guards —
a downgrade guard (never below raw) and a calibration guard (all-optimal ≈ raw).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.services.sleep_scoring import age_adjusted_sleep_score, age_adjusted_sleep_score_for_row

# Percentages are for a 57-year-old male. His 50–59 healthy bands:
#   REM 15–23%, Deep 12–20%, Light 48–62%, Awake 0–12%.


@dataclass(frozen=True)
class SleepRow:
    score: int | None
    age_adjusted_score: int | None
    factors_json: dict[str, Any]
    deep_sleep_sec: int | None
    light_sleep_sec: int | None
    rem_sleep_sec: int | None
    awake_sleep_sec: int | None


def _factors(**qualifiers: str) -> dict[str, Any]:
    """A Garmin ``sleepScores``-shaped dict with the given component qualifiers.

    Keys are the real Garmin component keys (``remPercentage`` etc.).
    """
    key_map = {
        "rem": "remPercentage",
        "deep": "deepPercentage",
        "light": "lightPercentage",
        "awake": "awakeCount",
    }
    return {key_map[name]: {"qualifierKey": q} for name, q in qualifiers.items()}


def _secs(rem: float, deep: float, light: float, awake: float) -> dict[str, int]:
    """Stage seconds whose shares equal the given percentages (they sum to 100)."""
    return {
        "rem_sleep_sec": int(rem * 60),
        "deep_sleep_sec": int(deep * 60),
        "light_sleep_sec": int(light * 60),
        "awake_sleep_sec": int(awake * 60),
    }


def _score(garmin: int, factors: dict[str, Any], secs: dict[str, int]) -> int | None:
    return age_adjusted_sleep_score(
        garmin_score=garmin, factors_json=factors, age=57, sex="male", **secs
    )


def test_rem_penalised_but_age_normal_night_rises() -> None:
    # REM 19% is inside the 50–59 band but Garmin flags FAIR against its
    # young-adult 21–31% target: the one age-driven penalty is credited back.
    factors = _factors(rem="FAIR", deep="GOOD", light="GOOD", awake="GOOD")
    secs = _secs(rem=19, deep=16, light=60, awake=5)
    assert _score(79, factors, secs) == 83  # +4 for the single REM upgrade


def test_calibration_all_optimal_reproduces_garmin() -> None:
    # Every stage already GOOD on Garmin's own bands -> zero credit -> raw score.
    factors = _factors(rem="GOOD", deep="GOOD", light="GOOD", awake="GOOD")
    secs = _secs(rem=19, deep=16, light=60, awake=5)
    assert _score(88, factors, secs) == 88


def test_downgrade_guard_genuinely_bad_night_is_not_rescued() -> None:
    # REM and Deep are low even for age (warn, not just below Garmin's young
    # target): the age band agrees they are poor, so no credit is awarded.
    factors = _factors(rem="POOR", deep="POOR", light="FAIR", awake="GOOD")
    secs = _secs(rem=8, deep=6, light=80, awake=6)
    assert _score(50, factors, secs) == 50


def test_score_is_never_below_raw() -> None:
    # Even if the age band is *worse* than Garmin's verdict, credit floors at 0.
    factors = _factors(rem="EXCELLENT", deep="EXCELLENT", light="EXCELLENT", awake="EXCELLENT")
    secs = _secs(rem=8, deep=6, light=80, awake=6)  # all age-warn
    assert _score(72, factors, secs) == 72


def test_credit_is_capped() -> None:
    # All four stages age-normal but Garmin-POOR would be +8 each; capped at +12.
    factors = _factors(rem="POOR", deep="POOR", light="POOR", awake="POOR")
    secs = _secs(rem=19, deep=16, light=55, awake=5)
    assert _score(60, factors, secs) == 72  # 60 + min(12, 4 * 2 * 4)


def test_awake_penalty_removed_when_age_normal() -> None:
    factors = _factors(rem="GOOD", deep="GOOD", light="GOOD", awake="FAIR")
    secs = _secs(rem=19, deep=16, light=55, awake=10)  # 10% awake is in 0–12 band
    assert _score(80, factors, secs) == 84


def test_result_clamps_to_100() -> None:
    factors = _factors(rem="POOR", deep="POOR")
    secs = _secs(rem=19, deep=16, light=55, awake=10)
    assert _score(96, factors, secs) == 100


def test_missing_age_returns_raw_score() -> None:
    factors = _factors(rem="FAIR")
    secs = _secs(rem=19, deep=16, light=60, awake=5)
    assert (
        age_adjusted_sleep_score(
            garmin_score=79, factors_json=factors, age=None, sex="male", **secs
        )
        == 79
    )


def test_missing_factors_returns_raw_score() -> None:
    secs = _secs(rem=19, deep=16, light=60, awake=5)
    assert (
        age_adjusted_sleep_score(garmin_score=79, factors_json=None, age=57, sex="male", **secs)
        == 79
    )


def test_none_garmin_score_returns_none() -> None:
    factors = _factors(rem="FAIR")
    secs = _secs(rem=19, deep=16, light=60, awake=5)
    assert (
        age_adjusted_sleep_score(
            garmin_score=None, factors_json=factors, age=57, sex="male", **secs
        )
        is None
    )


def test_row_adapter_recomputes_only_when_profile_age_is_known() -> None:
    row = SleepRow(
        score=79,
        age_adjusted_score=99,
        factors_json=_factors(rem="FAIR", deep="GOOD", light="GOOD", awake="GOOD"),
        **_secs(rem=19, deep=16, light=60, awake=5),
    )

    assert age_adjusted_sleep_score_for_row(row, age=57, sex="male") == 83
    assert age_adjusted_sleep_score_for_row(row, age=None, sex="male") == 99
