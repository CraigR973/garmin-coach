"""Batch 369 — the brief and the review in plain words.

369.2 (ST363-08b, UX362-04): "median" reached 4 of 6 briefs after the plain-words rule
shipped (Decision #440), and twice in the 1 Nov review, after Mark asked about the word
twice; the rule's own detector only logged a warning.
"""

from __future__ import annotations

from datetime import date, timedelta

from src.services.brief_check import MISS_STATISTICS_WORDS, MISSES, check_brief
from src.services.personal_baselines import readiness_baseline_trend
from src.services.plain_words_repair import (
    OUTCOME_ERROR,
    OUTCOME_REJECTED,
    OUTCOME_REPAIRED,
    RepairCall,
    repair_statistics_words,
)
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


# -- 369.2: one repair call on a statistics word ----------------------------------------------


LEAKY = "## Today's call\nEasy spin.\n\nYour readiness median is 63, against 74 before.\n"


def _call(answer: str | Exception) -> tuple[list[str], RepairCall]:
    seen: list[str] = []

    async def call(system: str, user: str) -> str:
        seen.append(user)
        if isinstance(answer, Exception):
            raise answer
        return answer

    return seen, call


async def test_a_clean_read_makes_no_call() -> None:
    seen, call = _call("unused")
    assert await repair_statistics_words("## Today's call\nEasy.\n", call=call) == (
        "## Today's call\nEasy.\n",
        {"attempted": False},
    )
    assert seen == []


async def test_a_leak_is_repaired_once_and_kept_only_with_every_figure() -> None:
    fixed = "## Today's call\nEasy spin.\n\nYour readiness is usually 63, against 74 before.\n"
    seen, call = _call(fixed)
    text, record = await repair_statistics_words(LEAKY, call=call)
    assert (text, record["outcome"], len(seen)) == (fixed.strip(), OUTCOME_REPAIRED, 1)
    # A repair that drops or changes a figure is not kept.
    _, call = _call(fixed.replace("63", "64"))
    text, record = await repair_statistics_words(LEAKY, call=call)
    assert (text, record["outcome"]) == (LEAKY, OUTCOME_REJECTED)
    # Nor one that keeps the word, nor a failed call.
    _, call = _call(LEAKY)
    assert (await repair_statistics_words(LEAKY, call=call))[1]["outcome"] == OUTCOME_REJECTED
    _, call = _call(RuntimeError("boom"))
    text, record = await repair_statistics_words(LEAKY, call=call)
    assert (text, record["outcome"]) == (LEAKY, OUTCOME_ERROR)


# -- 369.3: one REM yardstick, his own ----------------------------------------------------------


def test_the_rem_card_judges_his_own_usual_not_the_lab_band() -> None:
    """ST363-07: REM under 15% on 74 of 93 nights made the age-band card on by default."""

    from src.services.chronic_patterns import BaselineBand, build_chronic_pattern_suggestions
    from tests.test_chronic_patterns import _nights

    his_usual = {
        "rem_sleep_pct": BaselineBand(
            metric_key="rem_sleep_pct",
            label="REM sleep",
            lower_quartile=6.8,
            upper_quartile=13.4,
            median=10.0,
            mean=10.0,
            sample_count=84,
        )
    }
    as_of = date(2026, 11, 1)

    def rem_items(rem_pct: float) -> list:
        result = build_chronic_pattern_suggestions(
            sleeps=_nights(as_of, rem_pct=rem_pct),
            recovery_days=[],
            baselines=his_usual,
            driver_outcomes={},
            age=57,
            sex="male",
            sleep_protocol=None,
            as_of=as_of,
        )
        return [item for item in result.items if item.metric_key == "rem_sleep_pct"]

    # 11% nights: below the lab band every night, inside his usual: no card.
    assert rem_items(0.11) == []
    # 5% nights: below his own usual: the card, in his words.
    [card] = rem_items(0.05)
    assert any("your usual 7–13%" in line for line in card.evidence)
    assert "age" not in " ".join(card.evidence).lower()


def test_the_line_is_said_on_a_3_point_move_or_a_monday() -> None:
    """Craig, 3 Nov: not on every 1-2 point drift (the first replay said it 3 days of 5)."""

    from src.services.personal_baselines import readiness_trend_say

    def morning(recent: int) -> dict:
        return {"triggered": True, "usualRecent": recent}

    previous = None
    said = []
    # Wed 28 Oct to Sun 1 Nov, then Mon 2 Nov: 66, 66, 64, 63, 63, 63.
    for offset, recent in enumerate((66, 66, 64, 63, 63, 63)):
        trend = morning(recent)
        said.append(readiness_trend_say(trend, previous, date(2026, 10, 28) + timedelta(offset)))
        previous = trend
    assert said == [True, False, False, True, False, True]
    assert readiness_trend_say({"triggered": False}, previous, date(2026, 11, 3)) is False


def test_the_readiness_sentence_never_counts_toward_the_call() -> None:
    sentence = (
        "Your readiness has run lower for six weeks: usually 63 lately, against 74 the six "
        "weeks before."
    )
    packet = {**PACKET, "verdict": {**PACKET.get("verdict", {}), "readinessBaselineTrend": {
        "triggered": True, "say": True, "sentence": sentence}}}  # fmt: skip
    plain = check_brief(packet, GOOD).call_words
    call_end = GOOD.index("\n## ", GOOD.index("## Today's call") + 3)
    inside = GOOD[:call_end] + f"\n\n{sentence}\n" + GOOD[call_end:]
    assert check_brief(packet, inside).call_words == plain


async def test_one_repair_trims_a_long_call_and_keeps_every_other_figure() -> None:
    from src.services.plain_words_repair import repair_brief

    call_end = GOOD.index("\n## ", GOOD.index("## Today's call") + 3)
    padding = " ".join(["and"] * 130)
    long_brief = GOOD[:call_end] + f"\n\nAlso {padding}.\n" + GOOD[call_end:]
    assert "call_too_long" in check_brief(PACKET, long_brief).misses
    seen, call = _call(GOOD)
    text, record = await repair_brief(PACKET, long_brief, call=call)
    assert (text, record["outcome"], len(seen)) == (GOOD.strip(), OUTCOME_REPAIRED, 1)
    # A trim that changes a figure outside the call is not kept.
    rest = GOOD[call_end:]
    figure = next(token for token in rest.split() if token.strip(".,").isdigit())
    _, call = _call(GOOD.replace(figure, "999", 1) if figure in rest else GOOD + " 999")
    text, record = await repair_brief(PACKET, long_brief, call=call)
    assert (text, record["outcome"]) == (long_brief, OUTCOME_REJECTED)
    # A clean brief makes no call.
    seen, call = _call("unused")
    assert (await repair_brief(PACKET, GOOD, call=call))[1] == {"attempted": False}
    assert seen == []
