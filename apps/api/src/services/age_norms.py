"""Compare a user's metrics against general-population averages for their age.

This is the deterministic core behind the home screen's "How you compare for
your age" surface — Mark explicitly asked to see where he sits against the
average for his age, on top of the "vs your own baseline" read
(``services/metric_baselines.py``). It is intentionally a pure, side-effect-free
module: static reference tables in, a structured comparison out, so it is cheap
to unit-test and never touches the DB or any external service.

Two complementary signals are produced:

* **Fitness age** — Garmin's own age-equivalent for the user's VO2max (already
  synced inside ``daily_metrics.raw_payload``). This is the single most credible
  "vs your age" number because Garmin derives it against its own population
  model, so it is surfaced as the headline.
* **Per-metric vs the age-band average** — VO2max, resting heart rate and
  overnight HRV compared against published general-population averages for the
  user's sex + decade age band. Each row is classified *direction-aware* (a low
  resting HR is good; a high VO2max is good) into an outcome tier so the UI can
  colour it without re-deriving the meaning.

The reference numbers are deliberately coarse, population-level guides — not
clinical values — and the UI frames them as such. Sources are cited per table.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Tone = Literal["good", "warn", "neutral"]
Direction = Literal["higher", "lower"]
Sex = Literal["male", "female"]

# Decade age bands. Each entry is (inclusive_low, inclusive_high, label).
_AGE_BANDS: list[tuple[int, int, str]] = [
    (0, 29, "20–29"),
    (30, 39, "30–39"),
    (40, 49, "40–49"),
    (50, 59, "50–59"),
    (60, 69, "60–69"),
    (70, 200, "70+"),
]


def _band_label(age: int) -> str:
    for low, high, label in _AGE_BANDS:
        if low <= age <= high:
            return label
    return _AGE_BANDS[-1][2]


@dataclass(frozen=True)
class _Norm:
    """One metric's population average, keyed later by sex + band label."""

    label: str
    unit: str
    better: Direction
    # average value per band label, per sex.
    averages: dict[Sex, dict[str, float]]


# --- Reference tables -------------------------------------------------------
# These are general-population *averages* (≈50th percentile), not targets or
# clinical thresholds. They exist to answer "how do I compare to the average
# person my age", which is a deliberately blunt bar.
#
# Resting HR: adult resting heart rate is roughly flat across adult age bands;
#   the population mean sits near ~70–74 bpm (AHA "normal" 60–100). Lower = fitter.
# VO2max (ml/kg/min): ~50th-percentile cardiorespiratory fitness by age/sex,
#   following the ACSM / Cooper Institute normative percentile tables.
# HRV: overnight HRV (Garmin reports an RMSSD-style ms value). Resting RMSSD
#   declines with age; the bands below track that decline for healthy adults
#   (consistent with the Nunan et al. 2010 healthy-adult meta-analysis range).

_NORMS: dict[str, _Norm] = {
    "resting_heart_rate_bpm": _Norm(
        label="Resting HR",
        unit=" bpm",
        better="lower",
        averages={
            "male": {"20–29": 70, "30–39": 71, "40–49": 71, "50–59": 71, "60–69": 72, "70+": 73},
            "female": {"20–29": 74, "30–39": 74, "40–49": 74, "50–59": 74, "60–69": 74, "70+": 74},
        },
    ),
    "vo2max": _Norm(
        label="VO₂max",
        unit="",
        better="higher",
        averages={
            "male": {"20–29": 44, "30–39": 42, "40–49": 38, "50–59": 31, "60–69": 27, "70+": 23},
            "female": {"20–29": 36, "30–39": 34, "40–49": 31, "50–59": 25, "60–69": 22, "70+": 20},
        },
    ),
    "hrv_overnight_ms": _Norm(
        label="HRV (overnight)",
        unit=" ms",
        better="higher",
        averages={
            "male": {"20–29": 55, "30–39": 45, "40–49": 38, "50–59": 30, "60–69": 25, "70+": 22},
            "female": {"20–29": 55, "30–39": 45, "40–49": 36, "50–59": 28, "60–69": 24, "70+": 21},
        },
    ),
    "sleep_duration_hours": _Norm(
        label="Duration",
        unit=" h",
        better="higher",
        averages={
            "male": {
                "20–29": 7.9,
                "30–39": 7.7,
                "40–49": 7.4,
                "50–59": 7.1,
                "60–69": 6.8,
                "70+": 6.5,
            },
            "female": {
                "20–29": 7.9,
                "30–39": 7.7,
                "40–49": 7.4,
                "50–59": 7.1,
                "60–69": 6.8,
                "70+": 6.5,
            },
        },
    ),
    "deep_sleep_pct": _Norm(
        label="Deep",
        unit="%",
        better="higher",
        averages={
            "male": {"20–29": 20, "30–39": 19, "40–49": 18, "50–59": 17, "60–69": 16, "70+": 15},
            "female": {"20–29": 20, "30–39": 19, "40–49": 18, "50–59": 17, "60–69": 16, "70+": 15},
        },
    ),
    "light_sleep_pct": _Norm(
        label="Light",
        unit="%",
        better="lower",
        averages={
            "male": {"20–29": 50, "30–39": 51, "40–49": 52, "50–59": 53, "60–69": 54, "70+": 55},
            "female": {"20–29": 50, "30–39": 51, "40–49": 52, "50–59": 53, "60–69": 54, "70+": 55},
        },
    ),
    "rem_sleep_pct": _Norm(
        label="REM",
        unit="%",
        better="higher",
        averages={
            "male": {"20–29": 24, "30–39": 23, "40–49": 22, "50–59": 21, "60–69": 20, "70+": 19},
            "female": {"20–29": 24, "30–39": 23, "40–49": 22, "50–59": 21, "60–69": 20, "70+": 19},
        },
    ),
    "awake_sleep_pct": _Norm(
        label="Awake",
        unit="%",
        better="lower",
        averages={
            "male": {"20–29": 6, "30–39": 7, "40–49": 8, "50–59": 9, "60–69": 10, "70+": 11},
            "female": {"20–29": 6, "30–39": 7, "40–49": 8, "50–59": 9, "60–69": 10, "70+": 11},
        },
    ),
    "restless_moments_count": _Norm(
        label="Restless",
        unit="",
        better="lower",
        averages={
            "male": {"20–29": 10, "30–39": 11, "40–49": 12, "50–59": 13, "60–69": 14, "70+": 15},
            "female": {"20–29": 10, "30–39": 11, "40–49": 12, "50–59": 13, "60–69": 14, "70+": 15},
        },
    ),
}


@dataclass(frozen=True)
class AgeComparisonRow:
    metric_key: str
    label: str
    value: float
    unit: str
    age_average: float
    age_band: str
    better_direction: Direction
    tone: Tone
    descriptor: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "metricKey": self.metric_key,
            "label": self.label,
            "value": self.value,
            "unit": self.unit,
            "ageAverage": self.age_average,
            "ageBand": self.age_band,
            "betterDirection": self.better_direction,
            "tone": self.tone,
            "descriptor": self.descriptor,
        }


@dataclass(frozen=True)
class AgeComparison:
    age: int | None
    age_band: str | None
    fitness_age: int | None
    fitness_age_delta: int | None  # chronological - fitness_age; positive = "younger"
    fitness_age_tone: Tone | None
    rows: list[AgeComparisonRow] = field(default_factory=list)
    sleep_rows: list[AgeComparisonRow] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "age": self.age,
            "ageBand": self.age_band,
            "fitnessAge": self.fitness_age,
            "fitnessAgeDelta": self.fitness_age_delta,
            "fitnessAgeTone": self.fitness_age_tone,
            "rows": [row.to_dict() for row in self.rows],
            "sleepRows": [row.to_dict() for row in self.sleep_rows],
        }


def _classify(value: float, average: float, better: Direction) -> tuple[Tone, str]:
    """Direction-aware outcome tier of ``value`` against the population average.

    ``gap`` is signed so positive always means "better than average" regardless
    of whether higher or lower is the desirable direction. Descriptors are
    outcome-framed (better/below in terms of *good*) so a green tone always reads
    as "better than average" — e.g. a resting HR well *below* average is good.
    """
    if average <= 0:
        return "neutral", "About average"
    raw_gap = (value - average) / average
    gap = raw_gap if better == "higher" else -raw_gap
    if gap >= 0.15:
        return "good", "Much better than average"
    if gap >= 0.04:
        return "good", "Better than average"
    if gap > -0.04:
        return "neutral", "About average"
    if gap > -0.15:
        return "warn", "Below average"
    return "warn", "Well below average"


def _round(value: float) -> float:
    return round(value, 1)


def _sleep_stage_pct(stage_sec: int | None, total_sec: int | None) -> float | None:
    if stage_sec is None or total_sec is None or total_sec <= 0:
        return None
    return (stage_sec / total_sec) * 100.0


def _build_rows(
    *,
    candidates: dict[str, float | None],
    band: str,
    resolved_sex: Sex,
) -> list[AgeComparisonRow]:
    rows: list[AgeComparisonRow] = []
    for metric_key, value in candidates.items():
        if value is None:
            continue
        norm = _NORMS[metric_key]
        average = norm.averages[resolved_sex].get(band)
        if average is None:
            continue
        tone, descriptor = _classify(float(value), average, norm.better)
        rows.append(
            AgeComparisonRow(
                metric_key=metric_key,
                label=norm.label,
                value=_round(float(value)),
                unit=norm.unit,
                age_average=_round(average),
                age_band=band,
                better_direction=norm.better,
                tone=tone,
                descriptor=descriptor,
            )
        )
    return rows


def build_age_comparison(
    *,
    age: int | None,
    sex: Sex | str | None,
    vo2max: float | None,
    resting_heart_rate_bpm: float | None,
    hrv_overnight_ms: float | None,
    fitness_age: int | None,
    duration_sec: int | None = None,
    deep_sleep_sec: int | None = None,
    light_sleep_sec: int | None = None,
    rem_sleep_sec: int | None = None,
    awake_sleep_sec: int | None = None,
    restless_moments_count: int | None = None,
) -> AgeComparison:
    """Compare the supplied metrics against population averages for ``age``.

    Everything is optional and degrades gracefully: a missing ``age`` yields an
    empty comparison; a missing metric simply drops that row; an unknown ``sex``
    defaults to male (the primary user, Mark). Idempotent and pure.
    """
    resolved_sex: Sex = "female" if str(sex).lower() == "female" else "male"

    fitness_age_delta: int | None = None
    fitness_age_tone: Tone | None = None
    if fitness_age is not None and age is not None:
        fitness_age_delta = age - fitness_age
        if fitness_age_delta >= 2:
            fitness_age_tone = "good"
        elif fitness_age_delta <= -2:
            fitness_age_tone = "warn"
        else:
            fitness_age_tone = "neutral"

    if age is None:
        return AgeComparison(
            age=None,
            age_band=None,
            fitness_age=fitness_age,
            fitness_age_delta=fitness_age_delta,
            fitness_age_tone=fitness_age_tone,
            rows=[],
            sleep_rows=[],
        )

    band = _band_label(age)
    metric_rows = _build_rows(
        band=band,
        resolved_sex=resolved_sex,
        candidates={
            "vo2max": vo2max,
            "resting_heart_rate_bpm": resting_heart_rate_bpm,
            "hrv_overnight_ms": hrv_overnight_ms,
        },
    )
    measured_sleep_sec = sum(
        stage
        for stage in (deep_sleep_sec, light_sleep_sec, rem_sleep_sec, awake_sleep_sec)
        if stage is not None
    )
    sleep_rows = _build_rows(
        band=band,
        resolved_sex=resolved_sex,
        candidates={
            "sleep_duration_hours": (duration_sec / 3600.0) if duration_sec is not None else None,
            "deep_sleep_pct": _sleep_stage_pct(deep_sleep_sec, measured_sleep_sec),
            "light_sleep_pct": _sleep_stage_pct(light_sleep_sec, measured_sleep_sec),
            "rem_sleep_pct": _sleep_stage_pct(rem_sleep_sec, measured_sleep_sec),
            "awake_sleep_pct": _sleep_stage_pct(awake_sleep_sec, measured_sleep_sec),
            "restless_moments_count": float(restless_moments_count)
            if restless_moments_count is not None
            else None,
        },
    )

    return AgeComparison(
        age=age,
        age_band=band,
        fitness_age=fitness_age,
        fitness_age_delta=fitness_age_delta,
        fitness_age_tone=fitness_age_tone,
        rows=metric_rows,
        sleep_rows=sleep_rows,
    )
