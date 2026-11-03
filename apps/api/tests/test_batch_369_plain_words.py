"""Batch 369 — the brief and the review in plain words.

369.2 (ST363-08b, UX362-04): "median" reached 4 of 6 briefs after the plain-words rule
shipped (Decision #440), and twice in the 1 Nov review, after Mark asked about the word
twice; the rule's own detector only logged a warning.
"""

from __future__ import annotations

from src.services.brief_check import MISS_STATISTICS_WORDS, MISSES, check_brief
from tests.test_batch_318_brief_leads import GOOD, PACKET


def test_a_statistics_word_is_a_miss() -> None:
    assert MISS_STATISTICS_WORDS in MISSES
    assert MISS_STATISTICS_WORDS not in check_brief(PACKET, GOOD).misses
    leaked = GOOD + "\n\nThe recent 42-day median (63.0) is 11 points below the prior median.\n"
    check = check_brief(PACKET, leaked)
    assert MISS_STATISTICS_WORDS in check.misses
    assert check.statistics_words == ("median",)
    assert check.to_packet()["statisticsWords"] == ["median"]
