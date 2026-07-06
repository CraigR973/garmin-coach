"""Age-adjusted sleep score — a real recompute against age bands (Batch 61).

Replaces the flat Garmin "+4" (DECISIONS #14). Garmin scores each sleep stage
against a *young-adult* optimal band (e.g. REM optimal 21–31%), so a 57-year-old's
age-normal stage mix is penalised and the flat +4 merely nudges that penalty.
This module re-qualifies the age-sensitive stages (REM/Deep/Light/Awake) against
the healthy band for the user's age (``services/age_norms``) and awards *credit*
only where Garmin marked a stage down against its young target but the age band
accepts the value.

Two guarantees, both structural to the credit model rather than bolted-on
clamps (DECISIONS #135, settled at /batch-start over a calibrated rebuild):

* **Downgrade guard** — credit is never negative, so the age-adjusted score is
  never below Garmin's raw score. A night is only ever eased, never hardened.
* **Calibration guard** — a night already optimal on Garmin's own bands earns
  zero credit and reproduces Garmin's score exactly. We swap the target bands;
  we do not invent a new scale.

Pure and side-effect-free: Garmin's raw score + its stored per-stage sub-scores
(``Sleep.factors_json``) + stage seconds + age/sex in, an int score out. When
inputs are insufficient (no age, no Garmin sub-scores) it returns the raw score
unchanged — honest, and still within the downgrade guard.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from src.services.age_norms import Tone, classify_sleep_stage

# Garmin's per-component qualifier, worst → best.
_QUALIFIER_ORDINAL: dict[str, int] = {"POOR": 0, "FAIR": 1, "GOOD": 2, "EXCELLENT": 3}

# The age-band judgement tops out at "good" (in-band); it is deliberately mapped
# level with Garmin's "GOOD" so being inside your healthy range never scores
# *above* Garmin's own good verdict — it only lifts a young-target penalty.
_TONE_ORDINAL: dict[Tone, int] = {"warn": 0, "neutral": 1, "good": 2}

# Points credited per one-step qualifier upgrade (age band kinder than Garmin's
# young-adult judgement). One upgrade ≈ the old flat +4; multiple stack, capped,
# so a single age-normal-but-penalised stage lands where the old +4 did while a
# night penalised on nothing age-relevant gets no lift.
_POINTS_PER_STEP = 4
_MAX_STEPS_PER_COMPONENT = 2
_MAX_CREDIT = 12

# (age-band metric key in age_norms, Garmin factors_json component key).
# Awake maps to Garmin's ``awakeCount`` sub-score (awakening count, not a %),
# so it only ever *removes* a Garmin awake penalty when the awake share is
# age-normal — it never invents one.
_AGE_SENSITIVE: tuple[tuple[str, str], ...] = (
    ("rem_sleep_pct", "remPercentage"),
    ("deep_sleep_pct", "deepPercentage"),
    ("light_sleep_pct", "lightPercentage"),
    ("awake_sleep_pct", "awakeCount"),
)


class SleepScoreFields(Protocol):
    """Structural shape shared by ORM ``Sleep`` rows and test doubles."""

    score: int | None
    age_adjusted_score: int | None
    factors_json: dict[str, Any]
    deep_sleep_sec: int | None
    light_sleep_sec: int | None
    rem_sleep_sec: int | None
    awake_sleep_sec: int | None


def _pct(stage_sec: int | None, measured_sec: int) -> float | None:
    if stage_sec is None or measured_sec <= 0:
        return None
    return (stage_sec / measured_sec) * 100.0


def _garmin_ordinal(factors_json: Mapping[str, Any], key: str) -> int | None:
    component = factors_json.get(key)
    if not isinstance(component, Mapping):
        return None
    qualifier = component.get("qualifierKey")
    if not isinstance(qualifier, str):
        return None
    return _QUALIFIER_ORDINAL.get(qualifier.upper())


def _age_credit(
    *,
    factors_json: Mapping[str, Any] | None,
    deep_sleep_sec: int | None,
    light_sleep_sec: int | None,
    rem_sleep_sec: int | None,
    awake_sleep_sec: int | None,
    age: int | None,
    sex: str | None,
) -> int:
    """Summed, capped, non-negative credit for age-appropriate stages Garmin
    penalised against its young-adult targets."""
    if not isinstance(factors_json, Mapping) or age is None:
        return 0
    measured = sum(
        stage
        for stage in (deep_sleep_sec, light_sleep_sec, rem_sleep_sec, awake_sleep_sec)
        if stage is not None
    )
    if measured <= 0:
        return 0

    stage_pct = {
        "rem_sleep_pct": _pct(rem_sleep_sec, measured),
        "deep_sleep_pct": _pct(deep_sleep_sec, measured),
        "light_sleep_pct": _pct(light_sleep_sec, measured),
        "awake_sleep_pct": _pct(awake_sleep_sec, measured),
    }

    total = 0
    for age_key, garmin_key in _AGE_SENSITIVE:
        value = stage_pct[age_key]
        if value is None:
            continue
        garmin_ord = _garmin_ordinal(factors_json, garmin_key)
        if garmin_ord is None:
            continue
        age_tone = classify_sleep_stage(age_key, value, age, sex)
        if age_tone is None:
            continue
        steps = min(_MAX_STEPS_PER_COMPONENT, max(0, _TONE_ORDINAL[age_tone] - garmin_ord))
        total += steps * _POINTS_PER_STEP
    return min(_MAX_CREDIT, total)


def age_adjusted_sleep_score(
    *,
    garmin_score: int | None,
    factors_json: Mapping[str, Any] | None,
    deep_sleep_sec: int | None,
    light_sleep_sec: int | None,
    rem_sleep_sec: int | None,
    awake_sleep_sec: int | None,
    age: int | None,
    sex: str | None,
) -> int | None:
    """Garmin's raw sleep score lifted only for stages that are age-appropriate
    but scored against a young-adult target. ``None`` when there is no raw score.
    """
    if garmin_score is None:
        return None
    credit = _age_credit(
        factors_json=factors_json,
        deep_sleep_sec=deep_sleep_sec,
        light_sleep_sec=light_sleep_sec,
        rem_sleep_sec=rem_sleep_sec,
        awake_sleep_sec=awake_sleep_sec,
        age=age,
        sex=sex,
    )
    return min(100, garmin_score + credit)


def age_adjusted_sleep_score_for_row(
    row: SleepScoreFields | None,
    *,
    age: int | None,
    sex: str | None,
) -> int | None:
    """Central stored-row adapter.

    When the caller has profile age/sex, recompute from raw Garmin inputs. When
    it does not, keep the stored column so historical rollups remain forward-only
    instead of silently changing without enough context.
    """
    if row is None:
        return None
    if age is None:
        return row.age_adjusted_score
    computed = age_adjusted_sleep_score(
        garmin_score=row.score,
        factors_json=row.factors_json,
        deep_sleep_sec=row.deep_sleep_sec,
        light_sleep_sec=row.light_sleep_sec,
        rem_sleep_sec=row.rem_sleep_sec,
        awake_sleep_sec=row.awake_sleep_sec,
        age=age,
        sex=sex,
    )
    return computed if computed is not None else row.age_adjusted_score
