"""Batch 369 — the brief and the review in plain words.

369.2 (ST363-08b, UX362-04): "median" reached 4 of 6 briefs after the plain-words rule
shipped (Decision #440), and twice in the 1 Nov review, after Mark asked about the word
twice; the rule's own detector only logged a warning.
"""

from __future__ import annotations

from datetime import date, timedelta

from src.services.brief_check import MISS_STATISTICS_WORDS, MISSES, check_brief
from src.services.personal_baselines import readiness_baseline_trend
from tests.test_batch_318_brief_leads import GOOD, PACKET


def test_a_statistics_word_is_a_miss() -> None:
    assert MISS_STATISTICS_WORDS in MISSES
    assert MISS_STATISTICS_WORDS not in check_brief(PACKET, GOOD).misses
    leaked = GOOD + "\n\nThe recent 42-day median (63.0) is 11 points below the prior median.\n"
    check = check_brief(PACKET, leaked)
    assert MISS_STATISTICS_WORDS in check.misses
    assert check.statistics_words == ("median",)
    assert check.to_packet()["statisticsWords"] == ["median"]


# -- 369.1: the readiness line in plain figures, with what his days away explain ------------


def _readiness(before: float, recent: float, away: float, away_days: set[date]) -> list:
    as_of = date(2026, 11, 1)
    start = as_of - timedelta(days=83)
    return [
        (
            start + timedelta(days=i),
            away if start + timedelta(days=i) in away_days else (before if i < 42 else recent),
        )
        for i in range(84)
    ]


def test_the_line_says_whether_the_holiday_explains_the_fall() -> None:
    as_of = date(2026, 11, 1)
    holiday = {date(2026, 9, 22) + timedelta(days=i) for i in range(14)}
    # His shape: 74 before, 63 lately, and the fall still shows without the holiday.
    still = readiness_baseline_trend(
        _readiness(74, 67, 55, holiday), as_of=as_of, away_days=holiday
    )
    assert still["triggered"] and still["withoutAway"]["stillLower"]
    assert still["sentence"].endswith(
        "It still shows with your days away left out (67 against 74)."
    )
    # A fall that is all holiday says so.
    long_trip = {date(2026, 9, 22) + timedelta(days=i) for i in range(22)}
    explained = readiness_baseline_trend(
        _readiness(74, 72, 40, long_trip), as_of=as_of, away_days=long_trip
    )
    assert explained["triggered"] and not explained["withoutAway"]["stillLower"]
    assert "Most of that is your days away" in explained["sentence"]
    for trend in (still, explained):
        assert "median" not in trend["sentence"] + trend["reason"]
