"""What a comparable metric has to declare before it can be compared (Batch 275).

`evaluate_group_compare` has always been generic over `LabeledNight.value`; only
its caller pinned the metric, to age-adjusted sleep. Opening that up is what lets
the app answer the question Mark asked on 19 September 2026 — *does my HRV drop in
recovery weeks?* — instead of spending three paragraphs declining to call it
established, which it was right to do because nothing had tested it.

**Making the comparator generic is not enough on its own** (275.2, Decision #344).
Two of the three things a metric needs were missing, and one was already there:

* **A threshold in its own units.** `GROUP_THRESHOLD = 3.0` is commented
  *"age-adjusted sleep points = a meaningful gap"*. Three of anything else means
  something entirely different: three milliseconds of HRV is 0.6 of Mark's
  night-to-night standard deviation, three beats of resting heart rate is **two
  whole standard deviations**, and three minutes of sleep is under a tenth of one.
  A single constant across metrics is a different question asked of each one.
* **A direction.** `evaluate_group_compare` hardcoded *recovery lower than build
  ⇒ supported*, which is right for sleep score and HRV and exactly backwards for
  resting heart rate, where lower is better.
* **A variance-aware statistic — which already exists.** The row proposed adding
  one; Batch 249 (HS240-07) had already shipped it. `mean_difference_interval` is
  a Welch 95% confidence interval and `interval_excludes_zero` gates every
  directional verdict on it. Nothing here weakens that gate.

**Every threshold below is 0.3 of that metric's own measured standard deviation**,
rounded to a unit a person would use — the same effect size for every metric
rather than the same number. 0.3 SD is not invented: it is what the shipped sleep
threshold already is (3.0 against a measured SD of 10.67), so this generalises the
existing decision instead of replacing it. The standard deviations were measured on
2026-09-23 over Mark's last 120 days, one row per calendar date, morning phase
preferred for `daily_metrics` (the observation he was actually given — see
`daily_metric_phase`).

The threshold answers "is this gap big enough to be worth anything?"; the interval
answers "is it real?". Both have to pass, and neither substitutes for the other.
"""

from __future__ import annotations

from dataclasses import dataclass

SOURCE_SLEEP = "sleep"
SOURCE_DAILY_METRICS = "daily_metrics"


@dataclass(frozen=True)
class ComparableMetric:
    """One metric a group comparison may be run on.

    ``threshold`` is in ``units``, never in points of something else, and
    ``higher_is_better`` is read rather than assumed.
    """

    key: str
    label: str
    units: str
    source: str
    attribute: str
    #: Read when ``attribute`` is null — today only age-adjusted sleep, which has
    #: always fallen back to the raw score rather than dropping the night.
    fallback_attribute: str | None
    threshold: float
    higher_is_better: bool
    #: The dispersion the threshold was derived from, kept so a later reader can
    #: check the arithmetic instead of trusting the number.
    measured_sd: float
    measured_n: int

    def worse_delta(self, recovery_mean: float, build_mean: float) -> float:
        """How much *worse* the recovery arm is, in this metric's own direction.

        Positive means the recovery arm is worse, whichever way the metric points.
        """
        delta = recovery_mean - build_mean
        return -delta if self.higher_is_better else delta

    def format_value(self, value: float) -> str:
        return f"{value:.1f} {self.units}".strip()


#: Measured over Mark's last 120 days on 2026-09-23. Thresholds are 0.3 SD, rounded.
COMPARABLE_METRICS: dict[str, ComparableMetric] = {
    metric.key: metric
    for metric in (
        # 3.0 is unchanged from Batch 22, and is 0.28 SD — the precedent the rest
        # of this table follows. Changing it would move the answer to an
        # experiment that already has one.
        ComparableMetric(
            key="age_adjusted_sleep_score",
            label="age-adjusted sleep score",
            units="points",
            source=SOURCE_SLEEP,
            attribute="age_adjusted_score",
            fallback_attribute="score",
            threshold=3.0,
            higher_is_better=True,
            measured_sd=10.67,
            measured_n=118,
        ),
        # The metric Mark's 19 September question is about. It lives in
        # ``daily_metrics``, which is why the sleep-only comparator could not reach it.
        ComparableMetric(
            key="hrv_last_night_avg_ms",
            label="overnight HRV",
            units="ms",
            source=SOURCE_DAILY_METRICS,
            attribute="hrv_last_night_avg_ms",
            fallback_attribute=None,
            threshold=1.5,
            higher_is_better=True,
            measured_sd=5.16,
            measured_n=118,
        ),
        # Lower is better. Its SD is 1.47 bpm, so the old flat 3.0 would have been
        # two standard deviations — a threshold nothing could ever cross.
        ComparableMetric(
            key="resting_heart_rate_bpm",
            label="resting heart rate",
            units="bpm",
            source=SOURCE_DAILY_METRICS,
            attribute="resting_heart_rate_bpm",
            fallback_attribute=None,
            threshold=0.5,
            higher_is_better=False,
            measured_sd=1.47,
            measured_n=121,
        ),
        ComparableMetric(
            key="time_in_bed_min",
            label="time in bed",
            units="min",
            source=SOURCE_SLEEP,
            attribute="duration_sec",
            fallback_attribute=None,
            threshold=10.0,
            higher_is_better=True,
            measured_sd=32.21,
            measured_n=121,
        ),
        ComparableMetric(
            key="rem_sleep_min",
            label="REM sleep",
            units="min",
            source=SOURCE_SLEEP,
            attribute="rem_sleep_sec",
            fallback_attribute=None,
            threshold=6.0,
            higher_is_better=True,
            measured_sd=20.56,
            measured_n=121,
        ),
        # Lower is better.
        ComparableMetric(
            key="awake_min",
            label="time awake overnight",
            units="min",
            source=SOURCE_SLEEP,
            attribute="awake_sleep_sec",
            fallback_attribute=None,
            threshold=5.0,
            higher_is_better=False,
            measured_sd=17.76,
            measured_n=121,
        ),
    )
}

#: Attributes stored in seconds that the comparison reports in minutes.
SECONDS_ATTRIBUTES = frozenset({"duration_sec", "rem_sleep_sec", "awake_sleep_sec"})

DEFAULT_METRIC_KEY = "age_adjusted_sleep_score"


def comparable_metric(key: str | None) -> ComparableMetric | None:
    """The metric ``key`` names, or ``None`` when nothing here can compare it."""
    if not isinstance(key, str):
        return None
    return COMPARABLE_METRICS.get(key.strip())


def metric_value(metric: ComparableMetric, row: object) -> float | None:
    """Read ``metric`` off a ``Sleep`` or ``DailyMetric`` row, in ``metric.units``."""
    raw = getattr(row, metric.attribute, None)
    if raw is None and metric.fallback_attribute is not None:
        raw = getattr(row, metric.fallback_attribute, None)
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if metric.attribute in SECONDS_ATTRIBUTES:
        return value / 60.0
    return value
