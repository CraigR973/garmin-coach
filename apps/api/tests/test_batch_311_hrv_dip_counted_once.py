"""Batch 311 — the HRV dip counted twice, decided on the replay.

Run under Craig's delegation of 6 Oct and his go of 27 Oct, with the guard he accepted: a
candidate goes in only if every morning it eases was followed by a normal one (Decision
#425's test: the next night's HRV and resting heart rate not off, and no floor). Replayed on
production, read-only (Decision #446):

* **(b) The catch-up reaches any dip, holiday or not.** Its one eased morning, 27 Sep, was
  followed by a normal night (48 ms, 43 bpm). Built. Without a holiday it reads as a mild
  week in the signed-off words, so Mark reads nothing new.
* **(a), (c) and (d), the readiness candidates, wait for Craig.** Each eases 3 and 4 Oct,
  and both were followed by a low night (37 and 38 ms). They stay off in production; the
  replay can force each on to list what it changes.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from typing import Any

import pytest

from src.services.verdict_grading import (
    ACTION_RECOVERY,
    DOMAIN_SLEEP,
    GradingInputs,
    garmin_hrv_below_balanced,
    grade,
    mark_facing_phrase,
)
from src.services.verdict_replay import (
    FORCEABLE_RULES,
    RULE_FLAGS,
    ReplayReport,
    _action_list,
    _with_rules,
    render_rule_comparison,
)
from tests.test_batch_295_verdict_grading import _inputs, _load_fixture, _replayed
from tests.test_batch_310_hrv_holiday_catch_up import (
    BACK_FROM_7_OCT,
    _return_morning,
    _week,
    _words,
)

CATCHING_UP_DIP = "hrv_7_day_catching_up_dip"
READINESS_CANDIDATES = (
    "readiness_skips_fair_night_on_low_hrv",
    "readiness_confirms_load_only",
    "readiness_never_confirms",
)


@pytest.fixture(scope="module")
def fixture() -> dict[str, Any]:
    return _load_fixture()


# -- (b) the catch-up reaches any dip ------------------------------------------------------


def test_a_dip_without_a_holiday_catches_up_once_his_nights_are_back(
    fixture: dict[str, Any],
) -> None:
    """310's open question: the same nights with no holiday recorded."""
    inputs = _return_morning(fixture, date(2026, 10, 8), BACK_FROM_7_OCT, windows=[])
    assert inputs.hrv_nights_away == frozenset()
    reading = _week(grade(inputs))
    assert (reading.signal, reading.rating) == (CATCHING_UP_DIP, "mild")
    assert "the average is catching up" in reading.reason
    assert _week(grade(replace(inputs, hrv_catch_up_any_dip=False))).rating == "marked"


def test_it_reads_as_a_mild_week_in_signed_off_words(fixture: dict[str, Any]) -> None:
    inputs = _return_morning(fixture, date(2026, 10, 8), BACK_FROM_7_OCT, windows=[])
    reading = _week(grade(inputs))
    mild_week = replace(reading, signal="hrv_7_day")
    assert mark_facing_phrase(reading) == mark_facing_phrase(mild_week)
    assert mark_facing_phrase(reading).startswith("your HRV has been below your usual this week")
    assert "holiday" not in mark_facing_phrase(reading)


def test_a_holiday_keeps_its_own_words(fixture: dict[str, Any]) -> None:
    inputs = _return_morning(fixture, date(2026, 10, 8), BACK_FROM_7_OCT)
    reading = _week(grade(inputs))
    assert reading.signal == "hrv_7_day_catching_up"
    assert mark_facing_phrase(reading).startswith(_words(0, 0)[:60])


def test_one_night_back_is_not_enough(fixture: dict[str, Any]) -> None:
    one_back = (38, 38, 38, *[47] * 13)
    inputs = _return_morning(fixture, date(2026, 10, 8), one_back, windows=[])
    assert _week(grade(inputs)).rating == "marked"


def test_a_night_away_last_night_still_does_not_count(fixture: dict[str, Any]) -> None:
    """Holiday or not, last night must be at home: unchanged from 310."""
    inputs = _return_morning(fixture, date(2026, 10, 8), BACK_FROM_7_OCT, windows=[])
    away_last_night = replace(inputs, hrv_nights_away=frozenset({date(2026, 10, 8)}))
    assert _week(grade(away_last_night)).signal != CATCHING_UP_DIP


def test_the_flag_is_stored_so_the_replay_grades_a_morning_as_it_was() -> None:
    inputs = _inputs()
    assert grade(inputs).references["hrvCatchUpAnyDip"] is True
    stored_before = replace(inputs, hrv_catch_up_any_dip=False)
    assert grade(stored_before).references["hrvCatchUpAnyDip"] is False


# -- the replay lists what (b) changes ---------------------------------------------------


def test_27_sep_is_eased_as_the_replay_listed(fixture: dict[str, Any]) -> None:
    """A training dip at home: two nights back, so a little off, not clearly off."""
    today = _replayed(fixture)[date(2026, 9, 27)]
    before = _replayed(fixture, before=311)[date(2026, 9, 27)]
    assert (before.graded_label, _action_list(before)[:1]) == ("Red", [ACTION_RECOVERY])
    assert today.graded_label == "Amber"
    assert _week(today.graded).signal == CATCHING_UP_DIP


def test_the_fixture_mornings_it_changes_are_listed(fixture: dict[str, Any]) -> None:
    on = _replayed(fixture, rules_on={"hrv_catch_up_any_dip"})
    off = _replayed(fixture, rules_off={"hrv_catch_up_any_dip"})
    days = sorted(on)
    changed = [
        day
        for day in days
        if (on[day].graded_label, _action_list(on[day]))
        != (off[day].graded_label, _action_list(off[day]))
    ]
    assert changed == [date(2026, 9, 27)]
    text = render_rule_comparison(
        ReplayReport(start=days[0], end=days[-1], mornings=[on[day] for day in days]),
        ReplayReport(start=days[0], end=days[-1], mornings=[off[day] for day in days]),
        rules_off={"hrv_catch_up_any_dip"},
    )
    assert "Batch 311 (b), the catch-up reaches any dip, holiday or not" in text
    assert "| Sun 27 Sep | Red | Amber |" in text


# -- the readiness candidates wait for Craig ----------------------------------------------


def test_the_readiness_candidates_are_off_in_production() -> None:
    inputs = GradingInputs(subject_date=date(2026, 10, 28), acute={})
    for name in READINESS_CANDIDATES:
        assert getattr(inputs, name) is False
        assert name in RULE_FLAGS
        assert name in FORCEABLE_RULES


def test_a_fair_night_with_low_readiness_is_still_confirmed_today() -> None:
    inputs = _inputs(sleep_score=70, readiness="LOW")
    sleep = grade(inputs).domain(DOMAIN_SLEEP)
    assert (sleep.rating, sleep.confirmed_by_readiness) == ("marked", True)


@pytest.mark.parametrize(
    ("candidate", "below_balanced", "confirmed"),
    [
        ("readiness_skips_fair_night_on_low_hrv", True, False),
        ("readiness_skips_fair_night_on_low_hrv", False, True),
        ("readiness_confirms_load_only", False, False),
        ("readiness_never_confirms", False, False),
    ],
)
def test_each_candidate_forced_on_does_what_it_says(
    candidate: str, below_balanced: bool, confirmed: bool
) -> None:
    inputs = replace(
        _inputs(sleep_score=70, readiness="LOW"), garmin_hrv_below_balanced=below_balanced
    )
    sleep = grade(_with_rules(inputs, [candidate])).domain(DOMAIN_SLEEP)
    assert sleep.confirmed_by_readiness is confirmed
    assert sleep.rating == ("marked" if confirmed else "mild")


@pytest.mark.parametrize(
    ("status", "weekly", "baseline_low", "below"),
    [
        ("LOW", None, None, True),
        ("POOR", None, None, True),
        ("UNBALANCED", 40.0, 44.0, True),
        ("UNBALANCED", 60.0, 44.0, False),
        ("UNBALANCED", None, 44.0, False),
        ("BALANCED", 40.0, 44.0, False),
        (None, None, None, False),
    ],
)
def test_garmins_hrv_status_below_balanced(
    status: str | None, weekly: float | None, baseline_low: float | None, below: bool
) -> None:
    assert garmin_hrv_below_balanced(status, weekly, baseline_low) is below
