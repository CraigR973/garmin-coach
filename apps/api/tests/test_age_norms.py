"""Tests for the population age-norm comparison (services/age_norms.py).

Covers the pure :func:`build_age_comparison` core: age-band selection, the
direction-aware outcome tiers (low resting HR is *good*, high VO2max is *good*),
the fitness-age headline, sex resolution, and graceful degradation when age or
individual metrics are missing.
"""

from __future__ import annotations

from src.services.age_norms import build_age_comparison


def _rows_by_key(comparison: object) -> dict[str, object]:
    return {row.metric_key: row for row in comparison.rows}  # type: ignore[attr-defined]


def test_mark_like_profile_is_much_better_than_average() -> None:
    # Mark: 57yo male, strong cyclist — well above the average 50–59 man.
    comparison = build_age_comparison(
        age=57,
        sex="male",
        vo2max=54.0,
        resting_heart_rate_bpm=45,
        hrv_overnight_ms=50,
        fitness_age=48,
    )

    assert comparison.age_band == "50–59"
    # Fitness age 48 vs real 57 -> 9 years "younger", good.
    assert comparison.fitness_age_delta == 9
    assert comparison.fitness_age_tone == "good"

    rows = _rows_by_key(comparison)
    # All three land "much better than average" and green for this profile.
    for key in ("vo2max", "resting_heart_rate_bpm", "hrv_overnight_ms"):
        assert rows[key].tone == "good"  # type: ignore[attr-defined]
        assert rows[key].descriptor == "Much better than average"  # type: ignore[attr-defined]
    # The average is carried for the UI, drawn from the 50–59 male band.
    assert rows["vo2max"].age_average == 31  # type: ignore[attr-defined]
    assert rows["resting_heart_rate_bpm"].age_average == 71  # type: ignore[attr-defined]


def test_resting_hr_is_direction_aware_low_is_good() -> None:
    # A resting HR *below* the average must read green, not red.
    comparison = build_age_comparison(
        age=57,
        sex="male",
        vo2max=None,
        resting_heart_rate_bpm=45,
        hrv_overnight_ms=None,
        fitness_age=None,
    )
    row = _rows_by_key(comparison)["resting_heart_rate_bpm"]
    assert row.better_direction == "lower"  # type: ignore[attr-defined]
    assert row.tone == "good"  # type: ignore[attr-defined]

    # And an elevated resting HR reads as a warning.
    high = build_age_comparison(
        age=57,
        sex="male",
        vo2max=None,
        resting_heart_rate_bpm=88,
        hrv_overnight_ms=None,
        fitness_age=None,
    )
    assert _rows_by_key(high)["resting_heart_rate_bpm"].tone == "warn"  # type: ignore[attr-defined]


def test_about_average_is_neutral() -> None:
    comparison = build_age_comparison(
        age=57,
        sex="male",
        vo2max=31.0,  # exactly the 50–59 male average
        resting_heart_rate_bpm=None,
        hrv_overnight_ms=None,
        fitness_age=None,
    )
    row = _rows_by_key(comparison)["vo2max"]
    assert row.tone == "neutral"  # type: ignore[attr-defined]
    assert row.descriptor == "About average"  # type: ignore[attr-defined]


def test_age_band_selection_tracks_decade() -> None:
    assert (
        build_age_comparison(
            age=62,
            sex="male",
            vo2max=27.0,
            resting_heart_rate_bpm=None,
            hrv_overnight_ms=None,
            fitness_age=None,
        ).age_band
        == "60–69"
    )
    # 62yo at the 60–69 average VO2max (27) is about average, not below.
    row = _rows_by_key(
        build_age_comparison(
            age=62,
            sex="male",
            vo2max=27.0,
            resting_heart_rate_bpm=None,
            hrv_overnight_ms=None,
            fitness_age=None,
        )
    )["vo2max"]
    assert row.tone == "neutral"  # type: ignore[attr-defined]


def test_missing_age_yields_empty_rows_but_keeps_fitness_age() -> None:
    comparison = build_age_comparison(
        age=None,
        sex="male",
        vo2max=54.0,
        resting_heart_rate_bpm=45,
        hrv_overnight_ms=50,
        fitness_age=48,
    )
    assert comparison.rows == []
    assert comparison.age_band is None
    # Fitness age is reported, but with no chronological age there is no delta.
    assert comparison.fitness_age == 48
    assert comparison.fitness_age_delta is None


def test_missing_individual_metrics_drop_their_rows() -> None:
    comparison = build_age_comparison(
        age=57,
        sex="male",
        vo2max=54.0,
        resting_heart_rate_bpm=None,
        hrv_overnight_ms=None,
        fitness_age=None,
    )
    keys = set(_rows_by_key(comparison))
    assert keys == {"vo2max"}


def test_unknown_sex_defaults_to_male() -> None:
    male = build_age_comparison(
        age=57,
        sex="male",
        vo2max=40.0,
        resting_heart_rate_bpm=None,
        hrv_overnight_ms=None,
        fitness_age=None,
    )
    unknown = build_age_comparison(
        age=57,
        sex=None,
        vo2max=40.0,
        resting_heart_rate_bpm=None,
        hrv_overnight_ms=None,
        fitness_age=None,
    )
    assert (
        _rows_by_key(unknown)["vo2max"].age_average  # type: ignore[attr-defined]
        == _rows_by_key(male)["vo2max"].age_average  # type: ignore[attr-defined]
    )


def test_older_fitness_age_reads_as_warning() -> None:
    comparison = build_age_comparison(
        age=50,
        sex="male",
        vo2max=None,
        resting_heart_rate_bpm=None,
        hrv_overnight_ms=None,
        fitness_age=58,
    )
    assert comparison.fitness_age_delta == -8
    assert comparison.fitness_age_tone == "warn"


def test_to_dict_shape_is_camel_cased_for_the_api() -> None:
    payload = build_age_comparison(
        age=57,
        sex="male",
        vo2max=54.0,
        resting_heart_rate_bpm=45,
        hrv_overnight_ms=50,
        fitness_age=48,
    ).to_dict()
    assert payload["ageBand"] == "50–59"
    assert payload["fitnessAge"] == 48
    assert payload["fitnessAgeDelta"] == 9
    first = payload["rows"][0]
    assert set(first) == {
        "metricKey",
        "label",
        "value",
        "unit",
        "ageAverage",
        "ageBand",
        "betterDirection",
        "tone",
        "descriptor",
    }
