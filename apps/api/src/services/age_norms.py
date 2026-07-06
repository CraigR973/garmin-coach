"""Compare a user's metrics against general-population references for their age.

This is the deterministic core behind the home screen's "How you compare for
your age" surface — Mark explicitly asked to see where he sits against the
norm for his age, on top of the "vs your own baseline" read
(``services/metric_baselines.py``). It is intentionally a pure, side-effect-free
module: static reference tables in, a structured comparison out, so it is cheap
to unit-test and never touches the DB or any external service.

Two complementary signals are produced:

* **Fitness age** — Garmin's own age-equivalent for the user's VO2max (already
  synced inside ``daily_metrics.raw_payload``). This is the single most credible
  "vs your age" number because Garmin derives it against its own population
  model, so it is surfaced as the headline.
* **Per-metric vs the age reference** — VO2max, resting heart rate and overnight
  HRV compared against published general-population *averages* for the user's
  sex + decade age band; sleep-stage mix (REM/Deep/Light/Awake %, duration)
  compared against a **healthy age band** (Batch 61) rather than a single point.

Batch 61 replaces the single-average sleep comparison (which flagged anything
below the midpoint as "below average", so genuinely-normal-for-57 sleep read as
poor) with a ``(low, high)`` healthy band per sex × decade. A value anywhere
inside the band is neutral/good; only a value meaningfully outside it (past a
small tolerance) warns. Sleep-stage bands are anchored to Ohayon et al. 2004
(*Sleep* 27(7):1255) — the canonical meta-analysis of sleep architecture across
the lifespan — with REM% declining ~0.6%/decade and SWS (deep) declining most,
light + awake rising. **Restless** is Garmin-proprietary with no defensible
population band, so it is shown for context only and never classified.

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
    """One metric's reference, keyed later by sex + band label.

    Fitness metrics carry a single population ``averages`` point, classified
    direction-aware. Sleep-stage metrics instead resolve a ``(low, high)``
    healthy band from :data:`_SLEEP_BANDS` (Batch 61). ``descriptive_only``
    metrics (Restless) are shown for context but never classified against an
    age norm — they have no defensible population band.
    """

    label: str
    unit: str
    better: Direction
    # Single population average per band label, per sex (fitness + descriptive).
    averages: dict[Sex, dict[str, float]] | None = None
    descriptive_only: bool = False


# --- Reference tables -------------------------------------------------------
# Fitness metrics are general-population *averages* (≈50th percentile), not
# targets or clinical thresholds. They answer "how do I compare to the average
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
    # Sleep-stage metrics: band-classified (see _SLEEP_BANDS), no single average.
    "sleep_duration_hours": _Norm(label="Duration", unit=" h", better="higher"),
    "deep_sleep_pct": _Norm(label="Deep", unit="%", better="higher"),
    "light_sleep_pct": _Norm(label="Light", unit="%", better="lower"),
    "rem_sleep_pct": _Norm(label="REM", unit="%", better="higher"),
    "awake_sleep_pct": _Norm(label="Awake", unit="%", better="lower"),
    # Restless: Garmin-proprietary count with no defensible population band —
    # shown for context only (never warns). Kept for the personal-baseline read.
    "restless_moments_count": _Norm(
        label="Restless",
        unit="",
        better="lower",
        averages={
            "male": {"20–29": 10, "30–39": 11, "40–49": 12, "50–59": 13, "60–69": 14, "70+": 15},
            "female": {"20–29": 10, "30–39": 11, "40–49": 12, "50–59": 13, "60–69": 14, "70+": 15},
        },
        descriptive_only=True,
    ),
}

# --- Healthy sleep-stage bands (Batch 61) -----------------------------------
# ``(low, high)`` healthy range per sex × decade, expressed as a percentage of
# measured sleep (Deep/Light/REM/Awake) or hours (Duration). Male == female for
# the stage-mix rows: sleep architecture percentages are broadly sex-similar and
# the literature does not support a defensible sex split at this resolution, so
# we do not invent one.
#
# Anchored to the male 50–59 row (locked at /batch-start): REM 15–23%, Deep
# 12–20%, Light 48–62%, Awake ≤12%, Duration 6.5–8.0 h. Other decades step
# directionally from Ohayon et al. 2004 (REM ~-0.6%/decade; deep/SWS the steepest
# decline; light + awake rise with age; total sleep time shortens).
_MALE_FEMALE = ("male", "female")


def _both(bands: dict[str, tuple[float, float]]) -> dict[Sex, dict[str, tuple[float, float]]]:
    return {sex: dict(bands) for sex in _MALE_FEMALE}  # type: ignore[misc]


_SLEEP_BANDS: dict[str, dict[Sex, dict[str, tuple[float, float]]]] = {
    "rem_sleep_pct": _both(
        {
            "20–29": (18, 26),
            "30–39": (17, 25),
            "40–49": (16, 24),
            "50–59": (15, 23),
            "60–69": (14, 22),
            "70+": (13, 21),
        }
    ),
    "deep_sleep_pct": _both(
        {
            "20–29": (15, 23),
            "30–39": (14, 22),
            "40–49": (13, 21),
            "50–59": (12, 20),
            "60–69": (11, 19),
            "70+": (10, 18),
        }
    ),
    "light_sleep_pct": _both(
        {
            "20–29": (45, 59),
            "30–39": (46, 60),
            "40–49": (47, 61),
            "50–59": (48, 62),
            "60–69": (49, 63),
            "70+": (50, 64),
        }
    ),
    "awake_sleep_pct": _both(
        {
            "20–29": (0, 9),
            "30–39": (0, 10),
            "40–49": (0, 11),
            "50–59": (0, 12),
            "60–69": (0, 13),
            "70+": (0, 14),
        }
    ),
    "sleep_duration_hours": _both(
        {
            "20–29": (7.0, 8.5),
            "30–39": (6.9, 8.4),
            "40–49": (6.7, 8.2),
            "50–59": (6.5, 8.0),
            "60–69": (6.3, 7.8),
            "70+": (6.0, 7.5),
        }
    ),
}

# Fraction of a band's width tolerated just outside it before a value warns, so
# an edge value is neutral rather than a fail.
_BAND_TOLERANCE_FRACTION = 0.15

# Garmin's own young-adult "optimal" stage-% ranges (from ``sleepScores`` —
# remPercentage/deepPercentage/lightPercentage ``optimalStart``/``optimalEnd``).
# These are the targets Garmin scores against regardless of age, so surfacing
# them next to the age band makes the divergence explicit on the Sleep page
# (Batch 61 opt-in contrast). Awake/duration have no clean young-adult % target.
_GARMIN_YOUNG_TARGET: dict[str, tuple[float, float]] = {
    "rem_sleep_pct": (21, 31),
    "deep_sleep_pct": (16, 33),
    "light_sleep_pct": (30, 64),
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
    # Healthy band (Batch 61) for sleep-stage rows; ``None`` for average rows.
    band_low: float | None = None
    band_high: float | None = None
    # Garmin's young-adult target range, only for stage-% rows where Garmin
    # exposes a defensible optimalStart/optimalEnd pair.
    garmin_target_low: float | None = None
    garmin_target_high: float | None = None

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
            "bandLow": self.band_low,
            "bandHigh": self.band_high,
            "garminTargetLow": self.garmin_target_low,
            "garminTargetHigh": self.garmin_target_high,
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
    """Direction-aware outcome tier of ``value`` against a population average.

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


def _classify_band(value: float, low: float, high: float, better: Direction) -> tuple[Tone, str]:
    """Band-aware outcome tier of ``value`` against a healthy age range.

    Anywhere inside the band is good ("healthy for your age"). Beyond the band
    on the *desirable* side (more REM/deep/sleep, less light/awake) is still
    good. Beyond it on the concerning side is neutral within a small tolerance,
    and only warns past that tolerance — so an edge value never reads as a fail.
    """
    if low <= value <= high:
        return "good", "Healthy for your age"
    tolerance = _BAND_TOLERANCE_FRACTION * (high - low)
    if better == "higher":
        # Concern is being below the band; above it is genuinely good.
        if value > high:
            return "good", "Above the healthy range for your age"
        if value >= low - tolerance:
            return "neutral", "Just below the healthy range for your age"
        return "warn", "Below the healthy range for your age"
    # better == "lower": concern is being above the band; below it is fine.
    if value < low:
        return "good", "Below the typical range for your age"
    if value <= high + tolerance:
        return "neutral", "Just above the healthy range for your age"
    return "warn", "Above the healthy range for your age"


def _round(value: float) -> float:
    return round(value, 1)


def _sleep_stage_pct(stage_sec: int | None, total_sec: int | None) -> float | None:
    if stage_sec is None or total_sec is None or total_sec <= 0:
        return None
    return (stage_sec / total_sec) * 100.0


def _sleep_band(metric_key: str, band_label: str, resolved_sex: Sex) -> tuple[float, float] | None:
    per_sex = _SLEEP_BANDS.get(metric_key)
    if per_sex is None:
        return None
    return per_sex[resolved_sex].get(band_label)


def sleep_stage_band(
    metric_key: str, age: int | None, sex: Sex | str | None
) -> tuple[float, float] | None:
    """Public band lookup so the age-adjusted score (``services/sleep_scoring``)
    re-qualifies a stage against the very same healthy range the UI shows.
    """
    if age is None:
        return None
    resolved_sex: Sex = "female" if str(sex).lower() == "female" else "male"
    return _sleep_band(metric_key, _band_label(age), resolved_sex)


def classify_sleep_stage(
    metric_key: str, value: float, age: int | None, sex: Sex | str | None
) -> Tone | None:
    """Band tone for a sleep-stage ``value`` — the age-band judgement the
    age-adjusted score credits against. ``None`` when no band applies (unknown
    age or a non-banded metric). Shares :func:`_classify_band`'s tolerance so the
    score and the UI never disagree about what is "healthy for your age".
    """
    band = sleep_stage_band(metric_key, age, sex)
    norm = _NORMS.get(metric_key)
    if band is None or norm is None:
        return None
    tone, _ = _classify_band(value, band[0], band[1], norm.better)
    return tone


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
        numeric = float(value)

        stage_band = _sleep_band(metric_key, band, resolved_sex)
        if stage_band is not None:
            low, high = stage_band
            tone, descriptor = _classify_band(numeric, low, high, norm.better)
            garmin_target = _GARMIN_YOUNG_TARGET.get(metric_key)
            rows.append(
                AgeComparisonRow(
                    metric_key=metric_key,
                    label=norm.label,
                    value=_round(numeric),
                    unit=norm.unit,
                    age_average=_round((low + high) / 2),
                    age_band=band,
                    better_direction=norm.better,
                    tone=tone,
                    descriptor=descriptor,
                    band_low=_round(low),
                    band_high=_round(high),
                    garmin_target_low=_round(garmin_target[0]) if garmin_target else None,
                    garmin_target_high=_round(garmin_target[1]) if garmin_target else None,
                )
            )
            continue

        average = norm.averages[resolved_sex].get(band) if norm.averages else None

        if norm.descriptive_only:
            rows.append(
                AgeComparisonRow(
                    metric_key=metric_key,
                    label=norm.label,
                    value=_round(numeric),
                    unit=norm.unit,
                    age_average=_round(average) if average is not None else _round(numeric),
                    age_band=band,
                    better_direction=norm.better,
                    tone="neutral",
                    descriptor="Shown for context — no age range",
                )
            )
            continue

        if average is None:
            continue
        tone, descriptor = _classify(numeric, average, norm.better)
        rows.append(
            AgeComparisonRow(
                metric_key=metric_key,
                label=norm.label,
                value=_round(numeric),
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
    """Compare the supplied metrics against age references for ``age``.

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
