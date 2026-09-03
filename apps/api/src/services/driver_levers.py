"""Which measured driver may be offered to Mark as a lever (Batch 231).

Before this module the chronic-pattern card answered "what should I change?" with
a hardcode: :func:`_driver_for_flag` preferred ``prev_day_training_load`` for a
REM miss whatever the measurement said, and the drivers it chose from were
correlated against **sleep score** — a different outcome entirely. On four
consecutive mornings (2026-08-25 to 08-28) that produced, on Home and on
``/sleep`` as well as in the prose:

    "REM has repeatedly missed its age norm; training load is the strongest
    measured lever to check first."

carrying ``coefficient: -0.0464, sampleCount: 115`` in the same object — the
**twelfth of thirteen** drivers, against an outcome that was not REM.

Three rules replace the hardcode, and each one is a gate the false statement
fails:

* **the flag picks its own outcome** — a REM miss ranks drivers of REM, via
  :data:`FLAG_OUTCOMES`;
* **a driver has to be something he could do differently** — a measurement taken
  *with* or *after* the night cannot be a lever no matter how strongly it
  correlates, and neither can weather nobody can change
  (:data:`ACTIONABLE_DRIVERS` / :data:`CONCURRENT_DRIVERS` /
  :data:`UNMITIGABLE_DRIVERS`, which partition ``insights.DRIVER_KEYS``);
* **it has to be worth naming** — enough nights, an unfavourable direction, and
  a correlation above :data:`LEVER_MIN_ABS_R`. Below that the card names no
  driver at all rather than promoting the strongest of a weak field.

What survives is reported as *an association observed in his own data*, with its
known confounds named. Nothing here claims a cause: ``bedroom_peak_fan_speed``
correlates **+0.345** with REM on ten nights precisely because the fan runs when
the room is hot, and an app that told him fan speed lifts REM would be worse than
one that said nothing.

**Batch 249 (HS240-06) added the two gates that make the word "measured" true.**
The card used to carry a ``confidence`` of ``moderate`` or ``high`` chosen purely
from the size of ``|r|``. A word cannot say how sure it is. At the module's own
floor of twenty nights, ``r = 0.15`` carries p = 0.53 and a 95% interval running
from a moderate negative to a moderate positive relationship — a coin flip
labelled ``moderate``. So the word is gone, replaced by the interval and the
sample it came from, and **a lever whose interval crosses zero is not named at
all**: the association's own data cannot say which way it points.

The second gate is calendar time. Measured against production on 2026-09-03,
adjusting for the passage of the seasons moves *every* bedroom driver's
association with REM below this module's 0.15 floor, and moves
``bedroom_peak_fan_speed`` from +0.345 to -0.471 — because the fan ran in a warm
summer that ended. A single-subject time series shares one confounder with every
other: time itself.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from src.services.insights import (
    OUTCOME_OVERNIGHT_AWAKE_MIN,
    OUTCOME_RECOVERY_HRV,
    OUTCOME_REM_SLEEP_MIN,
    OUTCOME_SLEEP_SCORE,
    DriverCorrelation,
)

# Drivers Mark can answer differently: the room he sets before bed, and the
# previous day's load and stress. Fixed before the night's sleep is produced.
ACTIONABLE_DRIVERS = frozenset(
    {
        "bedroom_mean_temp_c",
        "bedroom_min_temp_c",
        "bedroom_max_temp_c",
        "bedroom_warning_minutes",
        "bedroom_critical_minutes",
        "bedroom_fan_ran_minutes",
        "bedroom_peak_fan_speed",
        # Not his to change, but it is the one weather driver with a mitigation
        # already in the protocol — a warm forecast is answered by pre-cooling.
        "overnight_low_c",
        "prev_day_training_load",
        "prev_day_stress_avg",
    }
)

# Measured with, or after, the outcome. ``sleep_stress_avg`` comes off the same
# night's sleep row and ``resting_heart_rate_bpm`` off the wake-morning row, so
# both describe the night rather than precede it. Reportable as an observation;
# never a lever, however strongly they rank — ``sleep_stress_avg`` is REM's
# second-strongest driver at -0.26 over 121 nights.
CONCURRENT_DRIVERS = frozenset({"sleep_stress_avg", "resting_heart_rate_bpm"})

# Antecedent, but nothing in the protocol answers them. Naming overnight wind as
# a lever is the same failure as asking him not to train late.
UNMITIGABLE_DRIVERS = frozenset({"overnight_wind_max_mph", "overnight_relative_humidity_mean_pct"})

# A chronic flag is judged against the outcome it is actually about. Anything
# unlisted falls back to sleep score, which is the metric it summarises.
FLAG_OUTCOMES: Mapping[str, str] = {
    "rem_sleep_pct": OUTCOME_REM_SLEEP_MIN,
    "awake_sleep_pct": OUTCOME_OVERNIGHT_AWAKE_MIN,
    "restless_moments_count": OUTCOME_OVERNIGHT_AWAKE_MIN,
    "hrv_7_day_avg_ms": OUTCOME_RECOVERY_HRV,
    "readiness_score": OUTCOME_RECOVERY_HRV,
}
DEFAULT_FLAG_OUTCOME = OUTCOME_SLEEP_SCORE

# Which way is bad. Overnight awake time is the one outcome where more is worse,
# so an unfavourable driver there has a *positive* coefficient.
OUTCOME_HIGHER_IS_BETTER: Mapping[str, bool] = {
    OUTCOME_SLEEP_SCORE: True,
    OUTCOME_RECOVERY_HRV: True,
    OUTCOME_REM_SLEEP_MIN: True,
    OUTCOME_OVERNIGHT_AWAKE_MIN: False,
}

# Measured against his own data: the thermal findings that say something real
# carry 55-70 nights, while ``bedroom_peak_fan_speed`` carries 10. Twenty is the
# floor that keeps the second kind out without discarding the first.
MIN_LEVER_SAMPLES = 20

# Below this the card says nothing rather than crowning the strongest of a weak
# field. The false statement's own coefficient was 0.046. Batch 249 applies it to
# the calendar-adjusted association rather than the raw one.
LEVER_MIN_ABS_R = 0.15

_FAN_CONFOUND = (
    "The fan runs because the room is already warm, so fan activity tracks warm "
    "nights rather than explaining them."
)

DRIVER_CONFOUNDS: Mapping[str, str] = {
    "bedroom_fan_ran_minutes": _FAN_CONFOUND,
    "bedroom_peak_fan_speed": _FAN_CONFOUND,
    "prev_day_training_load": (
        "Training load is planned around how he already felt, so a hard day and a "
        "good night can share a cause."
    ),
}


@dataclass(frozen=True)
class LeverEvidence:
    """One measured driver that has earned the right to be named as a lever."""

    correlation: DriverCorrelation
    confounds: tuple[str, ...]


def outcome_for_flag(metric_key: str) -> str:
    """The correlation outcome a chronic flag on ``metric_key`` should be read against."""
    return FLAG_OUTCOMES.get(metric_key, DEFAULT_FLAG_OUTCOME)


def is_unfavourable(correlation: DriverCorrelation) -> bool:
    """True when more of this driver goes with a worse outcome.

    Judged on :attr:`DriverCorrelation.effect` — the calendar-adjusted
    coefficient when there is one. ``bedroom_peak_fan_speed`` is why: its raw
    association with REM is *favourable* and its adjusted one is not, and the
    direction the app acts on has to be the direction it believes.
    """
    higher_is_better = OUTCOME_HIGHER_IS_BETTER.get(correlation.outcome, True)
    return correlation.effect < 0 if higher_is_better else correlation.effect > 0


def describe_evidence(correlation: DriverCorrelation) -> str:
    """The interval and the sample, in Mark's register rather than a statistician's.

    Batch 249 replaces the ``moderate``/``high`` word. The point of the sentence
    is that the reader can see how much room the data leaves for the effect to be
    nothing, which is exactly what a word hides.
    """
    nights = f"{correlation.sample_count} nights"
    interval = correlation.interval
    if interval is None:
        return f"Measured over {nights}."
    low, high = sorted(interval, key=abs)
    return (
        f"Measured over {nights}: the link is {abs(correlation.effect):.2f} on a 0-1 scale, "
        f"and the range the data still allows ({abs(low):.2f} to {abs(high):.2f}) stays "
        "on one side of no effect."
    )


def _confounds(correlation: DriverCorrelation) -> tuple[str, ...]:
    """Driver-specific reasons this number may not mean what it looks like.

    That the finding is an association rather than a cause is said once, in the
    summary sentence itself, so it is deliberately not repeated here.
    """
    known = DRIVER_CONFOUNDS.get(correlation.driver)
    return (known,) if known else ()


def select_levers(
    metric_key: str,
    outcomes: Mapping[str, Sequence[DriverCorrelation]],
    *,
    min_samples: int = MIN_LEVER_SAMPLES,
    min_abs_r: float = LEVER_MIN_ABS_R,
) -> list[LeverEvidence]:
    """Every actionable driver of this flag's outcome that has earned naming, ranked.

    One gate, one implementation. Batch 249 made this the plural form so the
    evening sleep projection can share it instead of keeping a second, looser
    copy of the same judgement — which is how an ungated "measured driver"
    reached Home, ``/sleep`` and a push while the careful version sat on the
    chronic card (HS240-11).
    """
    candidates = [
        correlation
        for correlation in outcomes.get(outcome_for_flag(metric_key), ())
        if correlation.driver in ACTIONABLE_DRIVERS
        and correlation.sample_count >= min_samples
        and abs(correlation.effect) >= min_abs_r
        # Batch 249: an association whose interval spans zero cannot say which
        # way it points, so it is not named however large the point estimate.
        and correlation.excludes_zero
        and is_unfavourable(correlation)
    ]
    # ``compute_drivers`` already sorts by the adjusted association; sort again so
    # the choice does not depend on that, and break ties on evidence then name for
    # determinism.
    ranked = sorted(
        candidates,
        key=lambda c: (-abs(c.effect), -c.sample_count, c.driver),
    )
    return [
        LeverEvidence(correlation=correlation, confounds=_confounds(correlation))
        for correlation in ranked
    ]


def select_lever(
    metric_key: str,
    outcomes: Mapping[str, Sequence[DriverCorrelation]],
    *,
    min_samples: int = MIN_LEVER_SAMPLES,
    min_abs_r: float = LEVER_MIN_ABS_R,
) -> LeverEvidence | None:
    """Return the strongest actionable driver of this flag's own outcome, or ``None``.

    ``None`` is a real answer and the common one when the evidence is thin: the
    caller must then say nothing about levers rather than fall back to whatever
    ranked first.
    """
    levers = select_levers(metric_key, outcomes, min_samples=min_samples, min_abs_r=min_abs_r)
    return levers[0] if levers else None
