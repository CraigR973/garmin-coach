"""Batch 231: which measured driver may be called a lever, and which may not."""

from __future__ import annotations

import pytest

from src.services.driver_levers import (
    ACTIONABLE_DRIVERS,
    CONCURRENT_DRIVERS,
    LEVER_MIN_ABS_R,
    MIN_LEVER_SAMPLES,
    UNMITIGABLE_DRIVERS,
    outcome_for_flag,
    select_lever,
)
from src.services.insights import (
    DRIVER_KEYS,
    OUTCOME_OVERNIGHT_AWAKE_MIN,
    OUTCOME_RECOVERY_HRV,
    OUTCOME_REM_SLEEP_MIN,
    OUTCOME_SLEEP_SCORE,
    DriverCorrelation,
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


def _correlations(rows: list[tuple[str, float, int]], outcome: str) -> list[DriverCorrelation]:
    return [
        DriverCorrelation(driver=driver, outcome=outcome, coefficient=r, sample_count=n)
        for driver, r, n in rows
    ]


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


def test_the_false_statement_cannot_recur_on_the_data_that_produced_it() -> None:
    """The 2026-08-25..28 regression, pinned to the real stored packet.

    On these exact numbers the app told Mark four mornings running that "training
    load is the strongest measured lever". It is the twelfth of thirteen drivers
    of REM and the second-weakest of sleep score, and it now loses on strength
    before any other gate is reached.
    """
    lever = select_lever("rem_sleep_pct", _prod_outcomes())

    assert lever is not None
    assert lever.correlation.driver == "bedroom_warning_minutes"
    assert lever.correlation.sample_count == 64
    assert lever.correlation.outcome == OUTCOME_REM_SLEEP_MIN
    assert lever.confidence == "moderate"


def test_the_packet_ranking_and_the_named_lever_cannot_disagree() -> None:
    """Whatever is named is the strongest eligible driver of that flag's outcome."""
    outcomes = _prod_outcomes()
    lever = select_lever("rem_sleep_pct", outcomes)
    assert lever is not None

    eligible = [
        correlation
        for correlation in outcomes[OUTCOME_REM_SLEEP_MIN]
        if correlation.driver in ACTIONABLE_DRIVERS
        and correlation.sample_count >= MIN_LEVER_SAMPLES
        and correlation.coefficient < 0
    ]
    strongest = max(eligible, key=lambda c: abs(c.coefficient))
    assert lever.correlation.driver == strongest.driver


def test_a_concurrent_measurement_is_never_a_lever() -> None:
    """``sleep_stress_avg`` is REM's second-strongest driver and still not a lever.

    It is read off the same night's sleep row, so it describes the night rather
    than preceding it. Strength cannot buy its way past that.
    """
    outcomes = _prod_outcomes()
    lever = select_lever("rem_sleep_pct", outcomes)
    assert lever is not None
    assert lever.correlation.driver not in CONCURRENT_DRIVERS
    # And it really was ranked above the winner.
    by_driver = {c.driver: c for c in outcomes[OUTCOME_REM_SLEEP_MIN]}
    assert abs(by_driver["sleep_stress_avg"].coefficient) > abs(lever.correlation.coefficient)


def test_a_ten_night_favourable_correlation_is_never_promoted() -> None:
    """``bedroom_peak_fan_speed`` is REM's top driver at +0.345 on ten nights.

    It fails twice over: too few nights, and the wrong direction — more fan goes
    with *more* REM because the fan runs on hot nights. An app that told him fan
    speed lifts REM would be worse than one that said nothing.
    """
    outcomes = _prod_outcomes()
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
    assert lever.confidence == "high"
    assert lever.confounds
    assert "because the room is already warm" in lever.confounds[0]


@pytest.mark.parametrize("coefficient", [-0.4, -LEVER_MIN_ABS_R])
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
