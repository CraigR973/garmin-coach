from __future__ import annotations

from datetime import date, timedelta

from src.services.chronic_patterns import (
    BaselineBand,
    RecoveryDay,
    SleepNight,
    build_chronic_pattern_suggestions,
)
from src.services.insights import DriverCorrelation


def _nights(end: date, *, rem_pct: float, count: int = 28) -> list[SleepNight]:
    rows: list[SleepNight] = []
    for offset in range(count):
        day = end - timedelta(days=count - offset - 1)
        duration = int(7.1 * 3600)
        deep = int(duration * 0.17)
        rem = int(duration * rem_pct)
        awake = int(duration * 0.09)
        light = duration - deep - rem - awake
        rows.append(
            SleepNight(
                calendar_date=day,
                score=68,
                age_adjusted_score=72,
                duration_sec=duration,
                deep_sleep_sec=deep,
                light_sleep_sec=light,
                rem_sleep_sec=rem,
                awake_sleep_sec=awake,
                restless_moments_count=9,
            )
        )
    return rows


def test_chronic_rem_suggestion_prioritises_measured_driver() -> None:
    as_of = date(2026, 7, 5)
    drivers = [
        DriverCorrelation(
            driver="prev_day_training_load",
            outcome="sleep_score",
            coefficient=-0.61,
            sample_count=18,
            summary="Higher load nights averaged 5 points lower sleep score.",
        )
    ]

    result = build_chronic_pattern_suggestions(
        sleeps=_nights(as_of, rem_pct=0.13),
        recovery_days=[],
        baselines={},
        sleep_drivers=drivers,
        age=57,
        sex="male",
        sleep_protocol={"bedtime": "23:15", "sealTargetTime": "22:00"},
        as_of=as_of,
    )

    assert result.status == "active"
    suggestion = result.items[0]
    assert suggestion.metric_key == "rem_sleep_pct"
    assert suggestion.driver is not None
    assert suggestion.driver.driver == "prev_day_training_load"
    assert "high-load" in suggestion.actions[0]
    assert suggestion.evidence[0].startswith("28 of 28 measured nights")


def test_insufficient_history_is_explicit() -> None:
    as_of = date(2026, 7, 5)

    result = build_chronic_pattern_suggestions(
        sleeps=_nights(as_of, rem_pct=0.13, count=6),
        recovery_days=[],
        baselines={},
        sleep_drivers=[],
        age=57,
        sex="male",
        sleep_protocol={},
        as_of=as_of,
    )

    assert result.status == "insufficient_history"
    assert result.evidence_window.nights_observed == 6
    assert "21 are needed" in result.summary


def test_clear_when_misses_do_not_repeat_enough() -> None:
    as_of = date(2026, 7, 5)
    sleeps = _nights(as_of, rem_pct=0.22)
    recovery_days = [
        RecoveryDay(
            calendar_date=as_of - timedelta(days=27 - offset),
            readiness_score=78,
            hrv_7_day_avg_ms=50,
            resting_heart_rate_bpm=45,
        )
        for offset in range(28)
    ]

    result = build_chronic_pattern_suggestions(
        sleeps=sleeps,
        recovery_days=recovery_days,
        baselines={
            "readiness_score": BaselineBand(
                metric_key="readiness_score",
                label="Readiness",
                lower_quartile=70,
                upper_quartile=84,
                median=78,
                mean=77,
                sample_count=28,
            )
        },
        sleep_drivers=[],
        age=57,
        sex="male",
        sleep_protocol={},
        as_of=as_of,
    )

    assert result.status == "clear"
    assert result.items == []
