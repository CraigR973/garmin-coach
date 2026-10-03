"""Batch 305 — the load and readiness lines say what they are.

Craig's calls on 3 Oct 2026, with G7c brought forward to go live before Mark's first ride
back on 7 Oct:

* **"Yesterday was a hard day" counts only before a hard session.** It was mild on 17 of
  103 replayed mornings; on 5 the day's session was easy, which is the recovery his plan
  set, not something off.
* **Readiness confirmation stays, labelled as deliberate extra weight.** It restates his
  sleep and recovery time, so a confirmed domain counts that night twice, on purpose.
* **A low HRV night is taken off the bike by a resting-heart-rate rise of 4 bpm**, not by
  two mornings above his usual range.
* **The load lines name their sources honestly.** Moving the load-ratio line to 1.5 waits
  until after 20 Oct: his first fortnight back from a holiday is when it would bite, and a
  session wrongly held is something he could not see.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from typing import Any
from unittest.mock import patch

import pytest

from src.services import verdict_grading
from src.services.morning_verdict import (
    RESTING_HR_CORROBORATION_DELTA_BPM,
    _rhr_corroborates,
)
from src.services.verdict_grading import (
    DOMAIN_LOAD,
    DOMAIN_SLEEP,
    THRESHOLDS,
    grade,
)
from tests.test_batch_294_symptom_floors import _verdict
from tests.test_batch_295_verdict_grading import VO2, Z2, _inputs


def _yesterday(inputs: Any) -> Any:
    [signal] = [
        s for s in grade(inputs).domain(DOMAIN_LOAD).signals if s.signal == "yesterday_load"
    ]
    return signal


# -- a hard yesterday counts only before a hard session ---------------------------------


def test_a_hard_yesterday_before_a_hard_session_is_mild() -> None:
    signal = _yesterday(_inputs(yesterday="hard", sessions=(VO2, Z2)))
    assert signal.rating == "mild"


def test_a_hard_yesterday_before_an_easy_session_counts_for_nothing() -> None:
    signal = _yesterday(_inputs(yesterday="hard", sessions=(Z2,)))
    assert signal.rating == "none"
    assert signal.reason == (
        "Yesterday's training was hard, and today's session is easy: that is the recovery "
        "his plan set, so it does not count against today."
    )


def test_a_hard_yesterday_before_a_rest_day_counts_for_nothing() -> None:
    inputs = replace(_inputs(yesterday="hard", sessions=(VO2,)), rest_day=True)
    assert _yesterday(inputs).rating == "none"


def test_an_easy_day_after_a_hard_one_is_no_longer_held_for_it() -> None:
    """3 Aug's shape: the hard yesterday was the only thing off. Held Green, now Green."""
    easy_day = _inputs(yesterday="hard", sessions=(Z2,))
    assert grade(easy_day).label == "Green"
    before = replace(easy_day, yesterday_counts_on_hard_days=False)
    assert grade(before).label == "Green (held)"


def test_the_flag_is_stored_so_the_replay_grades_a_morning_as_it_was() -> None:
    inputs = _inputs(yesterday="hard", sessions=(Z2,))
    assert grade(inputs).references["yesterdayCountsOnHardDays"] is True
    stored_before = replace(inputs, yesterday_counts_on_hard_days=False)
    assert grade(stored_before).references["yesterdayCountsOnHardDays"] is False


# -- readiness: deliberate extra weight, and the table says so -----------------------------


def test_readiness_confirms_one_domain_as_the_table_says() -> None:
    inputs = _inputs(sleep_score=70, recovery_hours=30, readiness="LOW")
    domains = {item.domain: item for item in grade(inputs).domains}
    assert domains[DOMAIN_SLEEP].rating == "marked"
    assert domains[DOMAIN_SLEEP].confirmed_by_readiness is True
    assert domains[DOMAIN_LOAD].rating == "mild"
    assert domains[DOMAIN_LOAD].confirmed_by_readiness is False


def test_the_engine_reads_the_tables_reach_for_readiness() -> None:
    """The table is the source: raise the line and readiness confirms both domains."""
    widened = dict(THRESHOLDS)
    widened["readiness_confirms_domains"] = replace(
        THRESHOLDS["readiness_confirms_domains"], value=2
    )
    inputs = _inputs(sleep_score=70, recovery_hours=30, readiness="LOW")
    with patch.object(verdict_grading, "THRESHOLDS", widened):
        domains = {item.domain: item for item in grade(inputs).domains}
    assert domains[DOMAIN_LOAD].rating == "marked"
    assert domains[DOMAIN_LOAD].confirmed_by_readiness is True


def test_readiness_is_labelled_as_counting_the_night_twice_on_purpose() -> None:
    line = THRESHOLDS["readiness_confirms_domains"]
    assert line.value == 1
    assert line.source.startswith("deliberate extra weight")
    assert "twice on purpose" in line.reason
    assert "counts the\n   same night twice" in (verdict_grading.__doc__ or "")


# -- the off-the-bike corroboration needs a real rise -------------------------------------


def test_two_mornings_above_his_usual_range_no_longer_take_a_low_night_off_the_bike() -> None:
    verdict = _verdict(day=date(2026, 9, 22), resting_hr=46, prior_resting_hr=46)
    acute = verdict["acutePhysiology"]

    assert acute["restingHeartRate"]["trigger"] == "consecutive_q3"
    assert acute["overnightHrv"]["corroboratedBy"] == []
    assert acute["overnightHrv"]["requiresBikeRest"] is False
    assert acute["requiresBikeRest"] is False


def test_a_rise_of_four_takes_a_low_night_off_the_bike() -> None:
    verdict = _verdict(day=date(2026, 9, 22), resting_hr=48)
    acute = verdict["acutePhysiology"]

    assert acute["overnightHrv"]["corroboratedBy"] == ["resting_heart_rate"]
    assert acute["requiresBikeRest"] is True


@pytest.mark.parametrize(
    ("delta", "samples", "corroborates"),
    [
        (3.9, 84, False),
        (4.0, 84, True),
        (7.0, 84, True),
        # His baseline is not yet known: nothing corroborates.
        (6.0, 20, False),
        (None, 84, False),
    ],
)
def test_the_rise_line_is_the_graded_mild_line(
    delta: float | None, samples: int, corroborates: bool
) -> None:
    assert RESTING_HR_CORROBORATION_DELTA_BPM == THRESHOLDS["resting_hr_rise_mild_bpm"].value
    rail = {"deltaFromMedianBpm": delta, "baselineSampleCount": samples, "triggered": True}
    assert _rhr_corroborates(rail) is corroborates


# -- the load lines name their sources ---------------------------------------------------


def test_the_load_ratio_lines_say_where_they_come_from() -> None:
    mild, marked = THRESHOLDS["acwr_mild"], THRESHOLDS["acwr_marked"]
    assert (mild.value, marked.value) == (1.3, 1.5)  # unchanged until after 20 Oct
    assert "Gabbett 2016" in mild.source
    assert "Impellizzeri 2020" in mild.source
    assert "optimal" in mild.source
    assert "after 20 Oct" in mild.reason
    assert "Garmin" in marked.source


def test_the_recovery_and_yesterday_lines_say_they_have_no_trial_source() -> None:
    assert THRESHOLDS["recovery_time_mild_hours"].source.startswith("Garmin's own estimate")
    yesterday = THRESHOLDS["yesterday_hard_mild"]
    assert yesterday.source.startswith("engineering choice, no trial source")
    assert "17 of 103" in yesterday.reason
