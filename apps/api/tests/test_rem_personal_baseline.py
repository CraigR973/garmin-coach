"""Batch 227 — REM is judged against Mark before it is judged against a population.

Over his 428 stored nights Mark's REM median is 10.0% of measured sleep
(IQR 7.1–12.9) against a 50–59 healthy band of 15–23%: **85% of his nights fall
below the floor.** A flag that fires six nights in seven cannot be right or
wrong, and until this batch REM appeared in neither ``BASELINE_SPECS`` nor the
trends ``METRICS`` registry, so no personal distribution existed to say
otherwise. Two call sites also disagreed on the percentage itself.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from src.models.coaching import Sleep
from src.services.age_norms import (
    REM_FRAMING_RULE,
    REM_PCT_BASIS,
    build_age_comparison,
    rem_sleep_pct,
    rem_sleep_pct_for_row,
)
from src.services.experiment_loop import ExperimentLoopService
from src.services.metric_baselines import sample_values
from src.services.morning_analysis import SYSTEM_PROMPT as MORNING_SYSTEM_PROMPT
from src.services.sleep_history import (
    BASELINE_SPECS,
    BaselineSample,
    compute_metric_baselines,
)
from src.services.trends import (
    BUCKET_MONTH,
    METRIC_KEYS,
    TREND_SYSTEM_PROMPT,
    TrendSample,
    compute_trend_windows,
)


def _night(
    day: date, *, deep: int, light: int, rem: int, awake: int, duration: int | None = None
) -> Sleep:
    return Sleep(
        user_id=uuid.uuid4(),
        calendar_date=day,
        deep_sleep_sec=deep,
        light_sleep_sec=light,
        rem_sleep_sec=rem,
        awake_sleep_sec=awake,
        # Garmin's own total-sleep figure, which excludes awake.
        duration_sec=duration if duration is not None else deep + light + rem,
    )


# The real 2026-08-25 night, the one that read two different percentages.
_AUG_25 = _night(date(2026, 8, 25), deep=4440, light=18180, rem=4440, awake=1500, duration=27060)


# --- 227.3: one percentage per night ---------------------------------------


def test_the_two_call_sites_agree_on_one_percentage_for_one_night() -> None:
    """`experiment_loop` divided by `duration_sec` (16.41%) and `age_norms` by
    measured sleep including awake (15.55%) — one above the 50–59 band floor and
    one below it, for the same sleep."""
    observation = ExperimentLoopService.__new__(ExperimentLoopService)
    # `remSleepPct` is written into every experiment's nightly observation from
    # one shared `common` block, so any slug proves the same call site.
    _, metrics = observation._observation(
        "collagen",
        day=date(2026, 8, 25),
        context={"sleep": _AUG_25, "manual": None},
    )

    age_row = next(
        row
        for row in build_age_comparison(
            age=57,
            sex="male",
            vo2max=None,
            resting_heart_rate_bpm=None,
            hrv_overnight_ms=None,
            fitness_age=None,
            duration_sec=_AUG_25.duration_sec,
            deep_sleep_sec=_AUG_25.deep_sleep_sec,
            light_sleep_sec=_AUG_25.light_sleep_sec,
            rem_sleep_sec=_AUG_25.rem_sleep_sec,
            awake_sleep_sec=_AUG_25.awake_sleep_sec,
        ).sleep_rows
        if row.metric_key == "rem_sleep_pct"
    )

    # One underlying measurement; the two surfaces differ only in how many
    # decimals they display (the age table rounds to 1, the observation to 2).
    shared = rem_sleep_pct_for_row(_AUG_25)
    assert shared == pytest.approx(15.5462, abs=0.001)
    assert metrics["remSleepPct"] == round(shared, 2) == 15.55
    assert age_row.value == round(shared, 1) == 15.5
    assert sample_values(_AUG_25, None)["rem_sleep_pct"] == shared

    # The old `duration_sec` denominator is what produced the second number.
    assert _AUG_25.rem_sleep_sec / _AUG_25.duration_sec * 100 == pytest.approx(16.41, abs=0.01)
    # Both sit ABOVE the 50–59 floor on this night. The authored row said they
    # straddled it; measured over all 428 stored nights the split only flips the
    # verdict on 13 of them (3.0%), and 2026-08-25 is not one — which is why the
    # defect is a consistency defect rather than a safety one.
    assert min(shared, 16.41) > 15.0


def test_the_split_can_flip_the_band_verdict_on_the_nights_that_do_straddle() -> None:
    """13 of Mark's 428 nights land between the two denominators, and on those
    the choice alone decides whether the app calls the night healthy."""
    straddling = _night(date(2026, 3, 26), deep=6000, light=19440, rem=4560, awake=2100)

    by_measured_sleep = rem_sleep_pct_for_row(straddling)
    by_total_sleep = straddling.rem_sleep_sec / straddling.duration_sec * 100

    assert by_measured_sleep is not None
    assert by_measured_sleep < 15.0 <= by_total_sleep
    # One definition now, so the packet can never carry both readings at once.
    assert sample_values(straddling, None)["rem_sleep_pct"] == by_measured_sleep


def test_the_denominator_constant_still_says_measured_sleep() -> None:
    """Renamed by Batch 230. This only ever checked the constant's own wording,
    while its old name — ``test_the_denominator_is_named_where_the_number_is
    _surfaced`` — promised it checked the packet. It did not, ``REM_PCT_BASIS``
    reached no packet at all, and the model wrote "9.8% of sleep" about a total
    containing 35 minutes of wakefulness with this test passing throughout. The
    packet-level claim now lives in
    ``test_batch230_reconcilable_figures.test_the_denominator_is_named_in_a_packet
    _not_only_in_a_constant``; this keeps only the claim it can actually make.
    """
    assert "measured sleep" in REM_PCT_BASIS
    assert "awake" in REM_PCT_BASIS.lower()


def test_rem_pct_is_none_without_a_measured_night() -> None:
    assert rem_sleep_pct(None, None, None, None) is None
    assert rem_sleep_pct_for_row(None) is None


# --- 227.2: a personal baseline and a trend series -------------------------


def test_rem_is_a_tracked_baseline_and_a_trend_metric() -> None:
    assert "rem_sleep_pct" in {spec.metric_key for spec in BASELINE_SPECS}
    assert "rem_sleep_pct" in METRIC_KEYS


def test_baselines_compute_over_a_rem_bearing_history() -> None:
    """The distribution Batch 221 has no access to: quartiles over stored nights."""
    nights = [
        _night(date(2026, 8, 1 + i), deep=4000, light=18000, rem=rem, awake=1500)
        for i, rem in enumerate((1800, 2400, 3000, 3600, 4200, 4800, 5400))
    ]
    samples = [
        BaselineSample(calendar_date=n.calendar_date, values=sample_values(n, None)) for n in nights
    ]

    rem_row = next(
        row
        for row in compute_metric_baselines(samples, source="db_history")
        if row["metric_key"] == "rem_sleep_pct"
    )

    assert rem_row["metric_label"] == "REM sleep"
    assert rem_row["sample_count"] == 7
    assert rem_row["median_value"] == pytest.approx(13.28, abs=0.05)
    assert rem_row["lower_quartile_value"] < rem_row["median_value"]
    assert rem_row["upper_quartile_value"] > rem_row["median_value"]


def test_rem_gets_a_month_over_month_series() -> None:
    samples = [TrendSample(day=date(2026, 7, 1 + i), rem_sleep_pct=8.0 + i) for i in range(6)] + [
        TrendSample(day=date(2026, 8, 1 + i), rem_sleep_pct=12.0 + i) for i in range(6)
    ]

    windows = compute_trend_windows(samples, bucket=BUCKET_MONTH)

    july = next(w for w in windows if w.key == "2026-07").metrics["rem_sleep_pct"]
    august = next(w for w in windows if w.key == "2026-08").metrics["rem_sleep_pct"]
    assert july.sample_count == 6 and august.sample_count == 6
    assert august.mean > july.mean


# --- 227.4: what the flag is allowed to say --------------------------------


def test_morning_prompt_puts_his_own_baseline_before_the_age_band() -> None:
    assert "metricsVsBaselines.rem_sleep_pct" in MORNING_SYSTEM_PROMPT
    # Batch 230 moved the wording into the shared rule; the ordering claim is the
    # part that has to survive, so it is asserted against the rule's own text.
    assert "own stored median and quartiles FIRST" in REM_FRAMING_RULE
    # An unusually good night must be recognisable as one.
    assert "above his own upper quartile is good" in REM_FRAMING_RULE
    assert "described as good even when it sits below the age band" in REM_FRAMING_RULE


def test_trends_prompt_reads_rem_against_personal_baselines_first() -> None:
    assert "REM against personalBaselines" in TREND_SYSTEM_PROMPT
    assert REM_FRAMING_RULE in TREND_SYSTEM_PROMPT


def test_a_below_band_night_can_still_be_above_his_own_upper_quartile() -> None:
    """The case the age band alone could never express: 74 REM minutes is a very
    good night for Mark and still sits under the 15% floor."""
    good_night = _night(date(2026, 8, 26), deep=4200, light=19800, rem=4440, awake=1800)

    pct = rem_sleep_pct_for_row(good_night)

    assert pct is not None
    assert pct < 15.0  # below the 50–59 band floor
    assert pct > 12.9  # above his own 428-night upper quartile
