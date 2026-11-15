"""Batch 389: one number called his sleep score, and his usual figures in whole numbers.

The figures are the row's fixtures, not a stored morning: a night Garmin scores 63 that
the age credit lifts to 71, and a sleep-score lower quartile of 69.75 over whole-number
nights, which a brief would print as "your usual range of 69.75–83".
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from src.models.coaching import MetricBaseline, Sleep
from src.services import verdict_grading
from src.services.chronic_patterns import BaselineBand
from src.services.morning_analysis import _baseline_comparison, _metrics_vs_baselines
from src.services.personal_baselines import (
    WHOLE_NUMBER_METRICS,
    baseline_band_packet,
    whole_range,
    whole_usual,
)
from src.services.sleep_history import BASELINE_SPECS
from src.services.verdict_grading import (
    DOMAIN_SLEEP,
    DomainRating,
    SignalReading,
    _sleep_score,
    grade,
    mark_facing_phrase,
)
from tests.test_batch_295_verdict_grading import _inputs
from tests.test_batch_300_light_week_marked import _light, _sweet_spot
from tests.test_chronic_patterns import _HRV_BASELINE, _hrv_card


def _baseline(
    metric_key: str,
    *,
    median: float,
    lower: float,
    upper: float,
    mean: float = 76.6,
    label: str = "Sleep score",
) -> MetricBaseline:
    return MetricBaseline(
        user_id=uuid.uuid4(),
        metric_key=metric_key,
        metric_label=label,
        source="db_history",
        window_start_date=date(2026, 8, 20),
        window_end_date=date(2026, 11, 11),
        sample_count=84,
        excluded_sample_count=0,
        mean_value=mean,
        median_value=median,
        lower_quartile_value=lower,
        upper_quartile_value=upper,
    )


# -- the rounding ------------------------------------------------------------------------


def test_a_usual_range_rounds_inwards_and_the_usual_half_up() -> None:
    assert whole_range("sleep_score", 69.75, 83.0) == (70, 83)
    assert whole_range("sleep_score", 68.75, 82.25) == (69, 82)
    assert whole_range("body_battery_charge", 62.0, 72.5) == (62, 72)
    # A half rounds up, as he would round it (Python's round() gives 78 for 78.5).
    assert whole_usual("readiness_score", 67.5) == 68
    assert whole_usual("sleep_score", 78.5) == 79
    assert whole_usual("sleep_score", 77.4) == 77
    # Whole figures come back whole and unchanged.
    assert whole_range("readiness_score", 57.0, 77.0) == (57, 77)
    assert whole_usual("readiness_score", 68.0) == 68


def test_other_metrics_keep_their_own_precision() -> None:
    assert "rem_sleep_pct" not in WHOLE_NUMBER_METRICS
    assert whole_range("rem_sleep_pct", 6.785, 13.378) == (6.785, 13.378)
    assert whole_usual("rem_sleep_pct", 9.79) == 9.79
    assert whole_usual("sleep_score", None) is None
    assert whole_range("sleep_score", None, 83.0) == (None, 83)


def test_every_whole_number_baseline_metric_is_listed() -> None:
    """Every baseline the app computes is either whole-number or REM's percentage."""

    keys = {spec.metric_key for spec in BASELINE_SPECS}
    assert keys - WHOLE_NUMBER_METRICS == {"rem_sleep_pct"}
    assert WHOLE_NUMBER_METRICS <= keys


def test_inward_rounding_never_moves_a_whole_reading_across_an_edge() -> None:
    """Inside the printed range exactly when inside the true one, for every whole reading."""

    edges = [quarter / 4 for quarter in range(160, 360)]
    for lower in edges[::3]:
        for upper in (lower + step / 4 for step in range(4, 60, 3)):
            low, high = whole_range("sleep_score", lower, upper)
            assert isinstance(low, int) and isinstance(high, int)
            for reading in range(30, 100):
                assert (lower <= reading <= upper) == (low <= reading <= high), (
                    lower,
                    upper,
                    reading,
                )


def test_a_range_too_narrow_for_a_whole_number_rounds_half_up_and_stays_in_order() -> None:
    low, high = whole_range("sleep_score", 72.25, 72.75)
    assert (low, high) == (72, 73)
    assert low is not None and high is not None and low <= high


# -- the packets -------------------------------------------------------------------------


def test_the_brief_reads_his_usual_sleep_range_in_whole_numbers() -> None:
    """12 Nov's shape: Garmin 63 against a range of 69.75–83 and a usual of 77.5."""

    row = _baseline_comparison(
        _baseline("sleep_score", median=77.5, lower=69.75, upper=83.0), current=63
    )

    assert row["baselineMedian"] == 78
    assert row["lowerQuartile"] == 70
    assert row["upperQuartile"] == 83
    # The difference is taken from the whole usual he reads: 63 against 78.
    assert row["deltaVsBaseline"] == -15
    # The mean is working, never given to him as his usual; it keeps its precision.
    assert row["baselineMean"] == 76.6
    for key in ("baselineMedian", "lowerQuartile", "upperQuartile"):
        assert float(row[key]).is_integer()


def test_the_metrics_rows_carry_whole_figures_for_both_sleep_scores_and_rem_keeps_its_own() -> None:
    baselines = [
        _baseline("sleep_score", median=77.5, lower=69.75, upper=83.0),
        _baseline(
            "age_adjusted_sleep_score",
            median=82.5,
            lower=75.75,
            upper=87.0,
            label="Age-adjusted sleep score",
        ),
        _baseline("rem_sleep_pct", median=9.79, lower=6.785, upper=13.378, label="REM sleep"),
    ]
    sleep = Sleep(user_id=uuid.uuid4(), calendar_date=date(2026, 11, 12), score=63)

    rows = {row["metricKey"]: row for row in _metrics_vs_baselines(None, sleep, baselines, 71)}

    garmin = rows["sleep_score"]
    assert (garmin["currentValue"], garmin["lowerQuartile"], garmin["upperQuartile"]) == (
        63,
        70,
        83,
    )
    adjusted = rows["age_adjusted_sleep_score"]
    assert adjusted["currentValue"] == 71
    assert (adjusted["baselineMedian"], adjusted["lowerQuartile"]) == (83, 76)
    assert adjusted["deltaVsBaseline"] == -12
    rem = rows["rem_sleep_pct"]
    assert (rem["lowerQuartile"], rem["upperQuartile"]) == (6.785, 13.378)


def test_the_coach_review_and_trends_bands_are_whole_too() -> None:
    bands = baseline_band_packet(
        [
            _baseline("sleep_score", median=77.5, lower=68.75, upper=82.25),
            _baseline("rem_sleep_pct", median=9.79, lower=6.785, upper=13.378),
        ]
    )

    assert bands["sleep_score"]["lowerQuartile"] == 69
    assert bands["sleep_score"]["upperQuartile"] == 82
    assert bands["sleep_score"]["median"] == 78
    assert bands["sleep_score"]["mean"] == 76.6
    assert bands["rem_sleep_pct"]["lowerQuartile"] == 6.785
    assert bands["rem_sleep_pct"]["median"] == 9.79


def test_the_chronic_evidence_line_reads_a_whole_floor_and_counts_the_same_misses() -> None:
    """A fractional floor of 44.75 is said as 45; the 43s still miss it and the 46s do not."""

    whole_card, _ = _hrv_card()
    band = _HRV_BASELINE["hrv_7_day_avg_ms"]
    fractional = {
        "hrv_7_day_avg_ms": BaselineBand(
            metric_key=band.metric_key,
            label=band.label,
            lower_quartile=44.75,
            upper_quartile=48.25,
            median=band.median,
            mean=band.mean,
            sample_count=band.sample_count,
        )
    }
    card, _ = _hrv_card(baselines=fractional)

    assert card.evidence[0] == "On 18 of 28 mornings the 7-day average missed personal floor 45."
    assert card.evidence == whole_card.evidence


# -- the name ----------------------------------------------------------------------------


def _sleep_reading(domains: tuple[DomainRating, ...]) -> SignalReading:
    sleep = next(item for item in domains if item.domain == DOMAIN_SLEEP)
    return next(signal for signal in sleep.signals if signal.signal == "sleep_score")


def test_an_age_adjusted_reading_says_which_score_it_is() -> None:
    verdict = grade(_inputs(sleep_score=71, raw_offset=8))

    reading = _sleep_reading(verdict.domains)
    assert (reading.value, reading.garmin_score, reading.rating) == (71, 63, "mild")
    assert reading.reason == "Age-adjusted sleep score 71 is fair."
    assert "Sleep mild: Age-adjusted sleep score 71 is fair." in verdict.reasons
    # The packet's shape is unchanged: the reason line names the score.
    assert "garminScore" not in reading.to_packet()
    assert set(reading.to_packet()) == {
        "domain",
        "signal",
        "rating",
        "value",
        "reference",
        "reason",
    }


def test_a_very_poor_age_adjusted_night_is_named_too() -> None:
    reading = _sleep_score(57, signal="sleep_score", garmin_score=50)

    assert reading.rating == "marked"
    assert reading.reason == "Age-adjusted sleep score 57 is very poor."
    assert reading.garmin_score == 50


def test_garmins_own_number_keeps_the_plain_name() -> None:
    # No age credit: the number is Garmin's.
    verdict = grade(_inputs(sleep_score=72))
    reading = _sleep_reading(verdict.domains)
    assert reading.garmin_score is None
    assert reading.reason == "Sleep score 72 is fair."
    assert verdict.summary == "One thing is a little off: a fair night's sleep (score 72)."
    # The raw-score pass is Garmin's number by definition.
    assert _sleep_score(63, signal="sleep_score").reason == "Sleep score 63 is fair."
    assert _sleep_score(None, signal="sleep_score", garmin_score=None).reason == "No sleep score."


# -- Craig's words: option C (15 Nov) ----------------------------------------------------


def test_home_names_the_age_adjusted_score_with_garmins_beside_it() -> None:
    verdict = grade(_inputs(sleep_score=71, raw_offset=8))

    assert verdict.summary == (
        "One thing is a little off: a fair night's sleep (age-adjusted score 71; "
        "Garmin's score 63)."
    )


def test_a_very_poor_age_adjusted_night_reads_the_same_way() -> None:
    verdict = grade(_inputs(sleep_score=57, raw_offset=7))

    assert verdict.age_credit_guard_applied is False
    assert verdict.summary == (
        "One thing is clearly off: a very poor night's sleep (age-adjusted score 57; "
        "Garmin's score 50)."
    )


def test_a_fair_night_his_readiness_confirms_names_both_scores() -> None:
    verdict = grade(_inputs(sleep_score=71, raw_offset=8, readiness="LOW"))

    assert verdict.summary == (
        "One thing is clearly off: last night's sleep (age-adjusted score 71; Garmin's "
        "score 63), which your readiness says left you less recovered than the score "
        "suggests."
    )


def test_the_phrase_follows_the_reading_it_is_given() -> None:
    named = _sleep_score(70, signal="sleep_score", garmin_score=62)
    plain = _sleep_score(70, signal="sleep_score", garmin_score=70)

    assert mark_facing_phrase(named) == (
        "a fair night's sleep (age-adjusted score 70; Garmin's score 62)"
    )
    assert mark_facing_phrase(plain) == "a fair night's sleep (score 70)"


@pytest.mark.parametrize(
    ("adjusted", "garmin", "readiness", "acwr"),
    [
        (71, 63, "HIGH", 1.0),
        (71, 63, "LOW", 1.0),
        (57, 50, "HIGH", 1.0),
        (76, 68, "HIGH", 1.6),
        (80, 72, "LOW", 1.6),
        (62, 55, "MODERATE", 1.0),
        (74, 66, "HIGH", 1.0),
        (73, 73, "LOW", 1.0),
    ],
)
def test_naming_the_score_never_moves_a_rating(
    monkeypatch: pytest.MonkeyPatch, adjusted: int, garmin: int, readiness: str, acwr: float
) -> None:
    """The colour, the hold, every domain, the guard and the actions are what they were."""

    inputs = _inputs(
        sleep_score=adjusted, raw_offset=adjusted - garmin, readiness=readiness, acwr=acwr
    )
    named = grade(inputs)

    plain_reading = verdict_grading._sleep_score

    def without_name(
        score: int | None, *, signal: str, garmin_score: int | None = None
    ) -> SignalReading:
        return plain_reading(score, signal=signal)

    monkeypatch.setattr(verdict_grading, "_sleep_score", without_name)
    unnamed = grade(inputs)

    assert (named.status, named.held, named.floor) == (unnamed.status, unnamed.held, unnamed.floor)
    assert named.age_credit_guard_applied == unnamed.age_credit_guard_applied
    assert [(d.domain, d.rating, d.confirmed_by_readiness) for d in named.domains] == [
        (d.domain, d.rating, d.confirmed_by_readiness) for d in unnamed.domains
    ]
    assert [a.action for a in named.actions] == [a.action for a in unnamed.actions]
    # Only the sleep line's name can differ, and only when the two scores differ.
    changed = [(a, b) for a, b in zip(named.reasons, unnamed.reasons, strict=True) if a != b]
    if garmin == adjusted:
        assert changed == []
    else:
        assert all(a == b.replace("Sleep score", "Age-adjusted sleep score") for a, b in changed)


def test_the_guard_explains_itself_on_garmins_own_number() -> None:
    """When the credit alone would have made the day Green, the line gives Garmin's score.

    Garmin 55 lifted to 63 on a planned light week (Batch 300's case): the guard holds the
    day, the one-line reason is the raw pass's ("score 55", Garmin's own number, plain),
    and the engine's reason line names the age-adjusted 63.
    """

    verdict = grade(_light([_sweet_spot()], sleep_score=63, raw_offset=8))

    assert verdict.age_credit_guard_applied is True
    assert verdict.summary == "One thing is clearly off: a very poor night's sleep (score 55)."
    reading = _sleep_reading(verdict.domains)
    assert (reading.value, reading.garmin_score) == (63, 55)
    assert "Sleep mild: Age-adjusted sleep score 63 is fair." in verdict.reasons
