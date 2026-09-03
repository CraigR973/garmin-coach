"""Batch 231: which measured driver may be called a lever, and which may not.

Batch 249 added the two gates that decide whether "measured" is a word this app
has earned — a 95% interval that stays on one side of zero, and an adjustment for
calendar time — so several of these fixtures now name nothing where they used to
name something. That is the point: on the real production packets the honest
answer is that no lever has ever cleared the bar.
"""

from __future__ import annotations

import pytest

from src.services.driver_levers import (
    ACTIONABLE_DRIVERS,
    CONCURRENT_DRIVERS,
    LEVER_MIN_ABS_R,
    MIN_LEVER_SAMPLES,
    UNMITIGABLE_DRIVERS,
    describe_evidence,
    outcome_for_flag,
    select_lever,
    select_levers,
)
from src.services.insights import (
    DRIVER_KEYS,
    OUTCOME_OVERNIGHT_AWAKE_MIN,
    OUTCOME_RECOVERY_HRV,
    OUTCOME_REM_SLEEP_MIN,
    OUTCOME_SLEEP_SCORE,
    DriverCorrelation,
    correlation_interval,
)
from src.services.rem_interventions import REM_LIBRARY

# The real stored ``driver_correlation`` packet for 2026-08-27, the morning after
# the false statement first appeared. Kept verbatim so the regression is pinned
# to production data rather than to a shape invented to pass.
PROD_REM_DRIVERS_2026_08_27 = [
    ("bedroom_peak_fan_speed", 0.3449, 10),
    ("sleep_stress_avg", -0.2597, 121),
    ("bedroom_warning_minutes", -0.2388, 64),
    ("bedroom_critical_minutes", -0.2346, 64),
    ("bedroom_min_temp_c", -0.2289, 64),
    ("bedroom_mean_temp_c", -0.2234, 64),
    ("bedroom_max_temp_c", -0.2094, 64),
    ("bedroom_fan_ran_minutes", -0.1949, 55),
    ("overnight_low_c", -0.1753, 70),
    ("overnight_wind_max_mph", 0.1532, 70),
    ("resting_heart_rate_bpm", -0.1507, 121),
    ("prev_day_training_load", -0.0783, 115),
    ("prev_day_stress_avg", 0.0479, 120),
]

PROD_SLEEP_SCORE_DRIVERS_2026_08_27 = [
    ("bedroom_peak_fan_speed", 0.4828, 10),
    ("sleep_stress_avg", -0.4715, 121),
    ("resting_heart_rate_bpm", -0.3160, 121),
    ("bedroom_warning_minutes", -0.2871, 64),
    ("prev_day_training_load", -0.0464, 115),
]


# The calendar-adjusted partials for the same drivers, measured against
# production on 2026-09-03 by re-running the real ``_driver_records`` and
# partialling out the day ordinal. Every one of them falls below the module's own
# 0.15 floor, and ``bedroom_peak_fan_speed`` changes sign: the fan ran through a
# warm summer that ended.
PROD_REM_PARTIALS_2026_09_03 = {
    "bedroom_peak_fan_speed": -0.4714,
    "sleep_stress_avg": -0.2851,
    "bedroom_critical_minutes": -0.1586,
    "bedroom_min_temp_c": -0.1496,
    "bedroom_warning_minutes": -0.1449,
    "bedroom_mean_temp_c": -0.1415,
    "prev_day_training_load": -0.1353,
    "overnight_low_c": -0.1264,
    "bedroom_max_temp_c": -0.1234,
    "bedroom_fan_ran_minutes": -0.1152,
    "resting_heart_rate_bpm": -0.1600,
    "overnight_wind_max_mph": 0.1717,
    "prev_day_stress_avg": -0.0768,
}


def _correlations(
    rows: list[tuple[str, float, int]],
    outcome: str,
    *,
    adjusted: dict[str, float] | None = None,
) -> list[DriverCorrelation]:
    """Build correlations the way ``compute_drivers`` does, interval included.

    Without ``adjusted`` this models a packet computed with no calendar covariate:
    the interval is taken on the raw coefficient, which is exactly what
    ``compute_drivers`` falls back to when the records carry no calendar key.
    """
    built = []
    for driver, r, n in rows:
        adjusted_r = None if adjusted is None else adjusted.get(driver)
        judged = r if adjusted_r is None else adjusted_r
        interval = correlation_interval(judged, n, controls=0 if adjusted_r is None else 1)
        built.append(
            DriverCorrelation(
                driver=driver,
                outcome=outcome,
                coefficient=r,
                sample_count=n,
                adjusted_coefficient=adjusted_r,
                interval_low=None if interval is None else interval[0],
                interval_high=None if interval is None else interval[1],
            )
        )
    return built


def _prod_outcomes() -> dict[str, list[DriverCorrelation]]:
    return {
        OUTCOME_REM_SLEEP_MIN: _correlations(PROD_REM_DRIVERS_2026_08_27, OUTCOME_REM_SLEEP_MIN),
        OUTCOME_SLEEP_SCORE: _correlations(
            PROD_SLEEP_SCORE_DRIVERS_2026_08_27, OUTCOME_SLEEP_SCORE
        ),
    }


def test_every_measured_driver_is_classified_exactly_once() -> None:
    """A new driver key cannot be added without deciding whether it is a lever.

    231.3 asked for a mapping that covers the drivers the analysis can actually
    produce. This is that requirement as a test rather than a promise.
    """
    classified = ACTIONABLE_DRIVERS | CONCURRENT_DRIVERS | UNMITIGABLE_DRIVERS
    assert classified == set(DRIVER_KEYS)
    assert not ACTIONABLE_DRIVERS & CONCURRENT_DRIVERS
    assert not ACTIONABLE_DRIVERS & UNMITIGABLE_DRIVERS
    assert not CONCURRENT_DRIVERS & UNMITIGABLE_DRIVERS


def test_every_actionable_driver_has_a_lever_that_answers_it() -> None:
    """Naming a driver he cannot act on is the defect 231.4 exists to stop.

    ``prev_day_training_load`` is deliberately included: its lever is a timing
    one, which is a separate objection, but a lever does exist.
    """
    with_levers = {key for item in REM_LIBRARY for key in item.driver_affinity}
    assert ACTIONABLE_DRIVERS <= with_levers


def test_no_lever_claims_a_driver_that_cannot_be_one() -> None:
    with_levers = {key for item in REM_LIBRARY for key in item.driver_affinity}
    assert not with_levers & CONCURRENT_DRIVERS
    assert not with_levers & UNMITIGABLE_DRIVERS


def test_each_flag_reads_its_own_outcome() -> None:
    assert outcome_for_flag("rem_sleep_pct") == OUTCOME_REM_SLEEP_MIN
    assert outcome_for_flag("awake_sleep_pct") == OUTCOME_OVERNIGHT_AWAKE_MIN
    assert outcome_for_flag("hrv_7_day_avg_ms") == OUTCOME_RECOVERY_HRV
    # Anything without its own computed outcome falls back to sleep score.
    assert outcome_for_flag("deep_sleep_pct") == OUTCOME_SLEEP_SCORE


# A driver strong enough that its interval genuinely clears zero. Nothing in
# production has ever looked like this; it exists so the gates can be shown to
# *pass* something as well as to refuse everything.
QUALIFYING_REM_DRIVERS = [
    ("sleep_stress_avg", -0.62, 90),
    ("bedroom_warning_minutes", -0.44, 90),
    ("bedroom_peak_fan_speed", 0.51, 90),
    ("prev_day_training_load", -0.31, 90),
]


def test_the_false_statement_cannot_recur_on_the_data_that_produced_it() -> None:
    """The 2026-08-25..28 regression, pinned to the real stored packet.

    On these exact numbers the app told Mark four mornings running that "training
    load is the strongest measured lever". Batch 231 stopped it winning on
    strength. Batch 249 goes further and names *nothing at all* here: every
    actionable driver's 95% interval crosses zero, ``bedroom_warning_minutes``
    running from -0.458 to +0.007 on 64 nights. The data cannot say which way any
    of them points, so the card says so instead of picking one.
    """
    assert select_lever("rem_sleep_pct", _prod_outcomes()) is None


def test_the_production_partials_leave_no_rem_lever_standing() -> None:
    """Adjusted for calendar time, no REM lever survives — and the CI is why.

    Measured on 2026-09-03. HS240-06 says the partial correlation is what closes
    this, and on the numbers it is not quite: adjustment takes
    ``bedroom_warning_minutes`` to -0.145, below the app's 0.15 floor and exactly
    reproducing the review's -0.1452 on a rolled-forward window — but
    ``bedroom_critical_minutes`` lands at -0.159, still *above* it. The gate that
    actually removes the last standing candidate is the interval, which runs from
    -0.379 to +0.079. **Both gates were needed; neither would have done it alone.**
    """
    outcomes = {
        OUTCOME_REM_SLEEP_MIN: _correlations(
            PROD_REM_DRIVERS_2026_08_27,
            OUTCOME_REM_SLEEP_MIN,
            adjusted=PROD_REM_PARTIALS_2026_09_03,
        )
    }
    assert select_lever("rem_sleep_pct", outcomes) is None
    assert select_levers("rem_sleep_pct", outcomes) == []

    by_driver = {c.driver: c for c in outcomes[OUTCOME_REM_SLEEP_MIN]}
    strong_enough = [
        c
        for c in outcomes[OUTCOME_REM_SLEEP_MIN]
        if c.driver in ACTIONABLE_DRIVERS
        and c.sample_count >= MIN_LEVER_SAMPLES
        and abs(c.effect) >= LEVER_MIN_ABS_R
    ]
    assert [c.driver for c in strong_enough] == ["bedroom_critical_minutes"]
    assert not strong_enough[0].excludes_zero
    # The lever production actually issued, closed by the strength floor alone.
    assert abs(by_driver["bedroom_warning_minutes"].effect) < LEVER_MIN_ABS_R


def test_an_interval_that_crosses_zero_blocks_a_driver_above_the_strength_floor() -> None:
    """Strength alone is not evidence. -0.22 on 71 nights is 0.07 wide of nothing."""
    outcomes = {
        OUTCOME_REM_SLEEP_MIN: _correlations(
            [("bedroom_critical_minutes", -0.2245, 71)], OUTCOME_REM_SLEEP_MIN
        )
    }
    (correlation,) = outcomes[OUTCOME_REM_SLEEP_MIN]
    assert abs(correlation.effect) >= LEVER_MIN_ABS_R
    assert correlation.sample_count >= MIN_LEVER_SAMPLES
    assert not correlation.excludes_zero
    assert select_lever("rem_sleep_pct", outcomes) is None


def test_a_driver_that_is_mostly_a_calendar_is_judged_on_the_adjusted_number() -> None:
    """``bedroom_peak_fan_speed`` reverses sign once the season is held constant.

    Raw it is +0.345 — apparently *protective* of REM. Adjusted it is -0.471.
    Whichever direction the app acts on has to be the one it believes, so the
    gates read the adjusted coefficient throughout.
    """
    rows = [("bedroom_peak_fan_speed", 0.3449, 90)]
    raw_only = _correlations(rows, OUTCOME_REM_SLEEP_MIN)
    adjusted = _correlations(
        rows, OUTCOME_REM_SLEEP_MIN, adjusted={"bedroom_peak_fan_speed": -0.4714}
    )
    # Raw: favourable, so never offered as something to change.
    assert select_lever("rem_sleep_pct", {OUTCOME_REM_SLEEP_MIN: raw_only}) is None
    # Adjusted: unfavourable and strong enough — and it arrives with its confound.
    lever = select_lever("rem_sleep_pct", {OUTCOME_REM_SLEEP_MIN: adjusted})
    assert lever is not None
    assert lever.correlation.effect == -0.4714
    assert "because the room is already warm" in lever.confounds[0]


def test_the_packet_ranking_and_the_named_lever_cannot_disagree() -> None:
    """Whatever is named is the strongest eligible driver of that flag's outcome."""
    outcomes = {OUTCOME_REM_SLEEP_MIN: _correlations(QUALIFYING_REM_DRIVERS, OUTCOME_REM_SLEEP_MIN)}
    lever = select_lever("rem_sleep_pct", outcomes)
    assert lever is not None

    eligible = [
        correlation
        for correlation in outcomes[OUTCOME_REM_SLEEP_MIN]
        if correlation.driver in ACTIONABLE_DRIVERS
        and correlation.sample_count >= MIN_LEVER_SAMPLES
        and correlation.effect < 0
        and correlation.excludes_zero
    ]
    strongest = max(eligible, key=lambda c: abs(c.effect))
    assert lever.correlation.driver == strongest.driver
    # And the plural form is the same gate, in rank order.
    assert [item.correlation.driver for item in select_levers("rem_sleep_pct", outcomes)] == [
        "bedroom_warning_minutes",
        "prev_day_training_load",
    ]


def test_a_concurrent_measurement_is_never_a_lever() -> None:
    """``sleep_stress_avg`` is REM's strongest driver here and still not a lever.

    It is read off the same night's sleep row, so it describes the night rather
    than preceding it. Strength cannot buy its way past that.
    """
    outcomes = {OUTCOME_REM_SLEEP_MIN: _correlations(QUALIFYING_REM_DRIVERS, OUTCOME_REM_SLEEP_MIN)}
    lever = select_lever("rem_sleep_pct", outcomes)
    assert lever is not None
    assert lever.correlation.driver not in CONCURRENT_DRIVERS
    # And it really was ranked above the winner.
    by_driver = {c.driver: c for c in outcomes[OUTCOME_REM_SLEEP_MIN]}
    assert abs(by_driver["sleep_stress_avg"].effect) > abs(lever.correlation.effect)


def test_a_ten_night_favourable_correlation_is_never_promoted() -> None:
    """``bedroom_peak_fan_speed`` is REM's top raw driver at +0.345 on ten nights.

    It fails three times over: too few nights, an interval spanning most of the
    range, and the wrong direction — more fan goes with *more* REM because the fan
    runs on hot nights. An app that told him fan speed lifts REM would be worse
    than one that said nothing.
    """
    outcomes = {OUTCOME_REM_SLEEP_MIN: _correlations(QUALIFYING_REM_DRIVERS, OUTCOME_REM_SLEEP_MIN)}
    lever = select_lever("rem_sleep_pct", outcomes)
    assert lever is not None
    assert lever.correlation.driver != "bedroom_peak_fan_speed"


def test_a_weak_field_names_nothing_rather_than_its_least_weak_member() -> None:
    weak = {
        OUTCOME_REM_SLEEP_MIN: _correlations(
            [("bedroom_warning_minutes", -0.09, 90), ("prev_day_training_load", -0.05, 115)],
            OUTCOME_REM_SLEEP_MIN,
        )
    }
    assert select_lever("rem_sleep_pct", weak) is None


def test_a_low_sample_driver_is_not_a_finding_however_strong() -> None:
    thin = {
        OUTCOME_REM_SLEEP_MIN: _correlations(
            [("bedroom_critical_minutes", -0.82, MIN_LEVER_SAMPLES - 1)],
            OUTCOME_REM_SLEEP_MIN,
        )
    }
    assert select_lever("rem_sleep_pct", thin) is None


def test_a_confounded_driver_carries_its_caveat_when_it_does_qualify() -> None:
    """The fan can still win on a different history — it must not win silently."""
    outcomes = {
        OUTCOME_REM_SLEEP_MIN: _correlations(
            [("bedroom_fan_ran_minutes", -0.41, 55)], OUTCOME_REM_SLEEP_MIN
        )
    }
    lever = select_lever("rem_sleep_pct", outcomes)

    assert lever is not None
    assert lever.confounds
    assert "because the room is already warm" in lever.confounds[0]


@pytest.mark.parametrize("coefficient", [-0.4, -0.3])
def test_more_awake_time_is_the_bad_direction_for_the_awake_outcome(
    coefficient: float,
) -> None:
    """Overnight awake time is the one outcome where a rise is the harm.

    A driver that goes *down* as awake time goes up is protective, not a problem
    to fix, so it must never be offered as the thing to change.
    """
    outcomes = {
        OUTCOME_OVERNIGHT_AWAKE_MIN: _correlations(
            [("bedroom_warning_minutes", coefficient, 64)], OUTCOME_OVERNIGHT_AWAKE_MIN
        )
    }
    assert select_lever("awake_sleep_pct", outcomes) is None

    outcomes_bad = {
        OUTCOME_OVERNIGHT_AWAKE_MIN: _correlations(
            [("bedroom_warning_minutes", abs(coefficient), 64)], OUTCOME_OVERNIGHT_AWAKE_MIN
        )
    }
    lever = select_lever("awake_sleep_pct", outcomes_bad)
    assert lever is not None
    assert lever.correlation.driver == "bedroom_warning_minutes"


def test_a_driver_at_the_strength_floor_with_a_wide_interval_names_nothing() -> None:
    """The gate's own floor used to admit p = 0.53 and call it ``moderate``.

    At the twenty-night sample floor, ``r = 0.15`` has a 95% interval running from
    a moderate negative to a moderate positive relationship. It is a coin flip,
    and it is now refused on exactly that ground rather than labelled.
    """
    outcomes = {
        OUTCOME_REM_SLEEP_MIN: _correlations(
            [("bedroom_warning_minutes", -LEVER_MIN_ABS_R, MIN_LEVER_SAMPLES)],
            OUTCOME_REM_SLEEP_MIN,
        )
    }
    (correlation,) = outcomes[OUTCOME_REM_SLEEP_MIN]
    low, high = correlation.interval or (0.0, 0.0)
    assert low < 0 < high
    assert select_lever("rem_sleep_pct", outcomes) is None


def test_the_evidence_sentence_reports_the_sample_and_the_range() -> None:
    """No confidence word survives — the reader gets the numbers it stood for."""
    (correlation,) = _correlations([("bedroom_warning_minutes", -0.44, 90)], OUTCOME_REM_SLEEP_MIN)
    sentence = describe_evidence(correlation)
    assert "90 nights" in sentence
    assert "stays" in sentence and "one side of no effect" in sentence
    assert "moderate" not in sentence and "high" not in sentence


def test_an_uncomputable_interval_is_not_a_pass() -> None:
    """A correlation with no interval fails the gate rather than skipping it.

    A stored pre-249 packet carries no interval at all. It must not be able to
    name a lever by virtue of the gate having nothing to check.
    """
    outcomes = {
        OUTCOME_REM_SLEEP_MIN: [
            DriverCorrelation(
                driver="bedroom_warning_minutes",
                outcome=OUTCOME_REM_SLEEP_MIN,
                coefficient=-0.9,
                sample_count=120,
            )
        ]
    }
    assert select_lever("rem_sleep_pct", outcomes) is None
