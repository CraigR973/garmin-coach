"""Batch 316 — the load ratio counts from Garmin's "high", and recovery time only before a
hard session.

Queued by Batch 305 (Decision #379) and the 6 Oct daily-verdict review (DV-8), after the
7–20 Oct trial (Decision #425); decided under Craig's delegation of 6 Oct (Decision #445):

* **The load ratio counts only from 1.5, Garmin's "high".** From 1.3 it flagged what Garmin
  calls optimal, and 4 of the 5 mornings load alone made cautious were followed by a normal
  one. From 1.5 it is still marked, as before: making it mild there would hold the sessions
  it now eases, as it eased 15 Oct's primer, and that is left for Craig.
* **Garmin's recovery time counts only before a hard session**, as Batch 305 made a hard
  yesterday count. Its own line already said a day of recovery left is fine for an easy
  session. The marked line (over 48 hours, never reached) still counts on any day.
* **From now on only.** Each graded morning stores both rules in its references, a morning
  stored before them replays without them, and the replay can force a rule on or off for
  every morning to list what it changes.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from typing import Any

import pytest

from src.services import verdict_grading
from src.services.verdict_grading import DOMAIN_LOAD, THRESHOLDS, SignalReading, grade
from src.services.verdict_replay import (
    RULE_FLAGS,
    ReplayReport,
    _action_list,
    _with_rules,
    _without_rules,
    render_rule_comparison,
)
from tests.test_batch_295_verdict_grading import VO2, Z2, _inputs, _load_fixture, _replayed

LOAD_RULES = ("load_ratio_from_high", "recovery_time_counts_on_hard_days")


def _signal(inputs: Any, name: str) -> SignalReading:
    [signal] = [s for s in grade(inputs).domain(DOMAIN_LOAD).signals if s.signal == name]
    return signal


# -- the load ratio counts from Garmin's "high" ------------------------------------------


@pytest.mark.parametrize("ratio", [1.3, 1.4, 1.49])
def test_a_ratio_under_garmins_high_counts_for_nothing(ratio: float) -> None:
    inputs = _inputs(acwr=ratio)
    signal = _signal(inputs, "acwr")
    assert signal.rating == "none"
    assert signal.reason == f"Load ratio {ratio:.2f}, under the 1.5 Garmin calls high."
    assert grade(inputs).domain(DOMAIN_LOAD).rating == "none"
    assert grade(inputs).label == "Green"


def test_a_balanced_ratio_reads_as_before() -> None:
    assert _signal(_inputs(acwr=1.1), "acwr").reason == "Load ratio is balanced."


@pytest.mark.parametrize("ratio", [1.5, 1.65])
def test_a_ratio_from_garmins_high_is_still_marked(ratio: float) -> None:
    """15 Oct's shape: 1.61 eased the primer, and still does."""
    inputs = _inputs(acwr=ratio)
    assert _signal(inputs, "acwr").rating == "marked"
    assert grade(inputs).label == "Amber"


def test_a_morning_stored_before_the_rule_reads_the_old_line() -> None:
    inputs = replace(_inputs(acwr=1.4), load_ratio_from_high=False)
    assert _signal(inputs, "acwr").rating == "mild"
    assert grade(inputs).label == "Green (held)"


# -- recovery time counts only before a hard session -------------------------------------


def test_a_day_of_recovery_before_a_hard_session_is_mild() -> None:
    assert _signal(_inputs(recovery_hours=30, sessions=(VO2, Z2)), "recovery_time").rating == (
        "mild"
    )


def test_a_day_of_recovery_before_an_easy_session_counts_for_nothing() -> None:
    signal = _signal(_inputs(recovery_hours=30, sessions=(Z2,)), "recovery_time")
    assert signal.rating == "none"
    assert signal.reason == (
        "30 h recovery left, and today's session is easy: a day of recovery is fine for an "
        "easy session, so it does not count against today."
    )


def test_a_day_of_recovery_before_a_rest_day_counts_for_nothing() -> None:
    inputs = replace(_inputs(recovery_hours=30, sessions=(VO2,)), rest_day=True)
    assert _signal(inputs, "recovery_time").rating == "none"


def test_an_unusual_recovery_debt_counts_on_any_day() -> None:
    assert _signal(_inputs(recovery_hours=50, sessions=(Z2,)), "recovery_time").rating == ("marked")


def test_an_easy_day_with_a_day_of_recovery_left_is_no_longer_held() -> None:
    easy_day = _inputs(recovery_hours=30, sessions=(Z2,))
    assert grade(easy_day).label == "Green"
    before = replace(easy_day, recovery_time_counts_on_hard_days=False)
    assert grade(before).label == "Green (held)"


def test_readiness_still_confirms_recovery_time_before_a_hard_session() -> None:
    """Batch 305's deliberate extra weight is untouched where recovery time counts."""
    inputs = _inputs(recovery_hours=30, readiness="LOW", sessions=(VO2, Z2))
    load = grade(inputs).domain(DOMAIN_LOAD)
    assert load.rating == "marked"
    assert load.confirmed_by_readiness is True


# -- from now on only ---------------------------------------------------------------------


def test_both_rules_are_stored_so_the_replay_grades_a_morning_as_it_was() -> None:
    inputs = _inputs()
    references = grade(inputs).references
    assert references["loadRatioFromHigh"] is True
    assert references["recoveryTimeCountsOnHardDays"] is True
    stored_before = replace(
        inputs, load_ratio_from_high=False, recovery_time_counts_on_hard_days=False
    )
    assert grade(stored_before).references["loadRatioFromHigh"] is False
    assert grade(stored_before).references["recoveryTimeCountsOnHardDays"] is False


def test_the_replay_names_both_rules() -> None:
    assert RULE_FLAGS["load_ratio_from_high"] == (
        "Batch 316, the load ratio only from Garmin's high (1.5)"
    )
    assert RULE_FLAGS["recovery_time_counts_on_hard_days"] == (
        "Batch 316, recovery time only before a hard session"
    )


def test_the_replay_can_force_each_rule_on_or_off() -> None:
    stored_before = replace(
        _inputs(), load_ratio_from_high=False, recovery_time_counts_on_hard_days=False
    )
    forced_on = _with_rules(stored_before, LOAD_RULES)
    assert forced_on.load_ratio_from_high is True
    assert forced_on.recovery_time_counts_on_hard_days is True
    forced_off = _without_rules(forced_on, LOAD_RULES)
    assert forced_off.load_ratio_from_high is False
    assert forced_off.recovery_time_counts_on_hard_days is False


def test_the_replay_refuses_to_force_on_what_is_not_a_grading_flag() -> None:
    with pytest.raises(ValueError, match="cannot force on"):
        _with_rules(_inputs(), ["planned_rest_day"])


def test_the_fixture_mornings_the_rules_change_are_listed() -> None:
    """Every stored morning with the rules forced on, against every one with them off."""
    fixture = _load_fixture()
    off = _replayed(fixture, rules_off=set(LOAD_RULES))
    on = _replayed(fixture, rules_on=set(LOAD_RULES))
    days = sorted(on)
    text = render_rule_comparison(
        ReplayReport(start=days[0], end=days[-1], mornings=[on[day] for day in days]),
        ReplayReport(start=days[0], end=days[-1], mornings=[off[day] for day in days]),
        rules_off=set(LOAD_RULES),
    )
    changed = [
        day
        for day in days
        if (on[day].graded_label, _action_list(on[day]))
        != (off[day].graded_label, _action_list(off[day]))
    ]
    assert f"- **Changed:** {len(changed)} of {len(days)} mornings" in text
    for day in changed:
        assert f"| {day:%a %-d %b} |" in text
        # Neither rule ever adds caution.
        rank = {"Green": 0, "Green (held)": 1, "Amber": 2, "Red": 3}
        assert rank[on[day].graded_label] <= rank[off[day].graded_label]


# -- the table says where each line stands ----------------------------------------------


def test_the_table_says_where_each_line_stands() -> None:
    assert THRESHOLDS["acwr_mild"].value == 1.3
    assert "before Batch 316" in THRESHOLDS["acwr_mild"].reason
    assert THRESHOLDS["acwr_marked"].value == 1.5
    assert "the ratio's only line" in THRESHOLDS["acwr_marked"].reason
    assert "only before a hard session" in THRESHOLDS["recovery_time_mild_hours"].reason
    assert "on any day" in THRESHOLDS["recovery_time_marked_hours"].reason
    assert "from Garmin's high (Batch 316)" in (verdict_grading.__doc__ or "")


def test_the_subject_date_is_not_what_decides() -> None:
    """The rules follow the stored flag, never the date the morning falls on."""
    early = replace(_inputs(acwr=1.4), subject_date=date(2026, 7, 27))
    assert _signal(early, "acwr").rating == "none"
