"""Batch 353: the oxygen notice in plain words.

Batch 352 (Decision #440) took quartiles, medians and standard deviations out of the
morning brief. The oxygen notice shown beside it still said "oxygen nadir" and "usual
upper quartile"; Craig asked for it as a small follow-up on 26 Oct. The panel's half of
the change is pinned in the web tests (``provenance.test.ts``).
"""

from __future__ import annotations

import re
from datetime import timedelta

from tests.test_morning_verdict import TODAY, _complete_verdict, _sleep

STATISTICS_WORDS = re.compile(
    r"\b(?:medians?|quartiles?|percentiles?|standard deviations?|nadirs?)\b", re.I
)


def _notices(verdict: dict) -> list[str]:
    return [item["message"] for item in verdict["acutePhysiology"]["escalations"]]


def test_both_oxygen_notices_speak_in_plain_words() -> None:
    low_average = _complete_verdict(sleep=_sleep(average_spo2=89, lowest_spo2=87, respiration=17))
    low_nights = _complete_verdict(
        sleep=_sleep(average_spo2=96, lowest_spo2=86, respiration=13),
        recent_sleeps=[
            _sleep(day=TODAY - timedelta(days=1), average_spo2=96, lowest_spo2=87, respiration=13)
        ],
    )
    for verdict, trigger in (
        (low_average, "low_average_spo2"),
        (low_nights, "nadir_cluster_with_respiration"),
    ):
        assert verdict["acutePhysiology"]["oxygenRespiration"]["trigger"] == trigger
        [notice] = _notices(verdict)
        assert not STATISTICS_WORDS.search(notice), notice
        # The GP route and the no-diagnosis wording stay exactly as signed off. Batch 339
        # (HS332-08): one low night is "a low reading", not "sustained".
        middle = (
            "A low reading like this is often the watch; if it repeats, it has causes worth "
            "checking properly"
            if trigger == "low_average_spo2"
            else "Sustained low overnight oxygen has causes worth checking properly"
        )
        assert notice.endswith(
            f"{middle} — a chest "
            "infection, or disrupted breathing during sleep. This one isn't something "
            "training or rest changes. Mention this to your GP if it happens again."
        )


def test_the_low_nights_notice_names_his_lowest_reading_and_his_usual_range() -> None:
    verdict = _complete_verdict(
        sleep=_sleep(average_spo2=96, lowest_spo2=86, respiration=13),
        recent_sleeps=[
            _sleep(day=TODAY - timedelta(days=1), average_spo2=96, lowest_spo2=87, respiration=13)
        ],
    )
    [notice] = _notices(verdict)
    assert notice.startswith(
        "Your watch recorded a lowest oxygen reading of 86% last night, below 88% on 2 of "
        "the last 3 nights."
    )
    assert "your breathing rate has stayed above its usual range (up to 12 " in notice
