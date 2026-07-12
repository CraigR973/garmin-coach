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
        duration_sec=8 * 3600,
        deep_sleep_sec=95 * 60,
        light_sleep_sec=250 * 60,
        rem_sleep_sec=80 * 60,
        awake_sleep_sec=15 * 60,
        restless_moments_count=8,
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

    sleep_rows = _rows_by_key(type("SleepRows", (), {"rows": comparison.sleep_rows})())
    assert set(sleep_rows) == {
        "sleep_duration_hours",
        "deep_sleep_pct",
        "light_sleep_pct",
        "rem_sleep_pct",
        "awake_sleep_pct",
        "restless_moments_count",
    }
    assert sleep_rows["sleep_duration_hours"].tone == "good"  # type: ignore[attr-defined]
    # REM 18.2% sits inside the 50–59 healthy band (15–23%), so it reads good,
    # carrying the band it was judged against — this is Mark's whole complaint.
    rem = sleep_rows["rem_sleep_pct"]
    assert rem.tone == "good"  # type: ignore[attr-defined]
    assert (rem.band_low, rem.band_high) == (15, 23)  # type: ignore[attr-defined]
    assert (rem.garmin_target_low, rem.garmin_target_high) == (21, 31)  # type: ignore[attr-defined]
    assert rem.descriptor == "Healthy for your age"  # type: ignore[attr-defined]
    # Restless has no defensible population band: shown for context, never warns.
    restless = sleep_rows["restless_moments_count"]
    assert restless.tone == "neutral"  # type: ignore[attr-defined]
    assert restless.age_average is None  # type: ignore[attr-defined]
    assert (restless.band_low, restless.band_high) == (None, None)  # type: ignore[attr-defined]
    assert (restless.garmin_target_low, restless.garmin_target_high) == (None, None)  # type: ignore[attr-defined]


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
    assert comparison.sleep_rows == []
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
        duration_sec=7 * 3600,
        deep_sleep_sec=90 * 60,
        light_sleep_sec=240 * 60,
        rem_sleep_sec=75 * 60,
        awake_sleep_sec=15 * 60,
        restless_moments_count=10,
    ).to_dict()
    assert payload["ageBand"] == "50–59"
    assert payload["fitnessAge"] == 48
    assert payload["fitnessAgeDelta"] == 9
    assert len(payload["sleepRows"]) == 6
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
        "bandLow",
        "bandHigh",
        "garminTargetLow",
        "garminTargetHigh",
    }
    # A fitness (average) row carries null band edges; a sleep-stage row carries
    # the healthy range it was classified against.
    assert (first["bandLow"], first["bandHigh"]) == (None, None)
    assert (first["garminTargetLow"], first["garminTargetHigh"]) == (None, None)
    rem = next(r for r in payload["sleepRows"] if r["metricKey"] == "rem_sleep_pct")
    assert (rem["bandLow"], rem["bandHigh"]) == (15, 23)
    assert (rem["garminTargetLow"], rem["garminTargetHigh"]) == (21, 31)
    restless = next(r for r in payload["sleepRows"] if r["metricKey"] == "restless_moments_count")
    assert restless["ageAverage"] is None


def test_sleep_stage_in_band_is_good_outside_warns_with_edge_tolerance() -> None:
    # REM band for a 57yo male is 15–23%. Build nights that place REM at a
    # given percentage of measured sleep by supplying only REM + a filler stage.
    def rem_tone(rem_pct: float) -> str:
        total_sec = 100 * 60
        rem_sec = int(round(rem_pct / 100 * total_sec))
        comparison = build_age_comparison(
            age=57,
            sex="male",
            vo2max=None,
            resting_heart_rate_bpm=None,
            hrv_overnight_ms=None,
            fitness_age=None,
            rem_sleep_sec=rem_sec,
            light_sleep_sec=total_sec - rem_sec,
        )
        return _rows_by_key(type("SleepRows", (), {"rows": comparison.sleep_rows})())[
            "rem_sleep_pct"
        ].tone  # type: ignore[attr-defined]

    assert rem_tone(19) == "good"  # squarely inside 15–23
    assert rem_tone(15) == "good"  # on the low edge, still healthy
    assert rem_tone(28) == "good"  # more REM than the band is desirable, not a fail
    # Just below the band (tolerance = 0.15 * 8 = 1.2) is neutral, not a warn.
    assert rem_tone(14) == "neutral"
    # Meaningfully below the band warns.
    assert rem_tone(10) == "warn"


def test_light_above_band_warns_even_when_garmin_would_flag_it() -> None:
    # Too *much* light sleep for age is a genuine miss (Mark's is high even for
    # his age) — the band still warns, so the age lens is not a rubber stamp.
    total = 100 * 60
    comparison = build_age_comparison(
        age=57,
        sex="male",
        vo2max=None,
        resting_heart_rate_bpm=None,
        hrv_overnight_ms=None,
        fitness_age=None,
        light_sleep_sec=int(0.70 * total),
        deep_sleep_sec=int(0.30 * total),
    )
    rows = _rows_by_key(type("SleepRows", (), {"rows": comparison.sleep_rows})())
    assert rows["light_sleep_pct"].tone == "warn"  # type: ignore[attr-defined]


def test_public_band_helpers_match_the_table() -> None:
    from src.services.age_norms import classify_sleep_stage, sleep_stage_band

    assert sleep_stage_band("rem_sleep_pct", 57, "male") == (15, 23)
    assert sleep_stage_band("rem_sleep_pct", 62, "male") == (14, 22)
    # No band for a fitness metric or an unknown age.
    assert sleep_stage_band("vo2max", 57, "male") is None
    assert sleep_stage_band("restless_moments_count", 57, "male") is None
    assert sleep_stage_band("rem_sleep_pct", None, "male") is None
    # classify mirrors the band tone used by the age-adjusted score.
    assert classify_sleep_stage("rem_sleep_pct", 19, 57, "male") == "good"
    assert classify_sleep_stage("rem_sleep_pct", 10, 57, "male") == "warn"
    assert classify_sleep_stage("restless_moments_count", 12, 57, "male") is None
