"""Batch 311 (e) — his HRV normal leaves out the week it judges and the nights he slept away.

Craig's answer of 28 Oct to 311's follow-ups: keep (a), (c) and (d) off, and replay (e).
(e) is a replay switch, off in production (Decision #446). Forced on, his normal, for the
acute rail and the 7-day rating, leaves out the 7 nights the morning judges and every night
he slept away. Forced on and forced off both recompute the acute rail, so the two replays
differ by the rule alone.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import Any

import pytest

from src.models.coaching import DailyMetric
from src.services.holiday_pause import HolidayWindow
from src.services.morning_verdict import _hrv_rail
from src.services.verdict_grading import GradingInputs, _hrv_week_on, hrv_normal_leave_out
from src.services.verdict_replay import FORCEABLE_RULES, RULE_FLAGS, _action_list
from tests.test_batch_295_verdict_grading import _load_fixture, _replayed

RULE = "hrv_normal_leaves_out_judged_week"
DAY = date(2026, 10, 28)
#: His autumn holiday as the bedroom reads it: away on the nights dated 28 Sep-6 Oct.
HOLIDAY = HolidayWindow(
    start_date=date(2026, 9, 27),
    end_date=date(2026, 10, 6),
    paused_at_utc=datetime(2026, 9, 27),
)


@pytest.fixture(scope="module")
def fixture() -> dict[str, Any]:
    return _load_fixture()


def _nights(week: float) -> tuple[tuple[date, float], ...]:
    """84 ordinary nights around 47 ms before the judged week, then the week at ``week``."""
    before = [(DAY - timedelta(days=offset), 47.0 + offset % 3 - 1) for offset in range(90, 6, -1)]
    judged = [(DAY - timedelta(days=offset), week) for offset in range(6, -1, -1)]
    return tuple(before + judged)


def test_the_switch_is_off_in_production() -> None:
    assert GradingInputs(subject_date=DAY, acute={}).hrv_normal_leaves_out_judged_week is False
    assert RULE in RULE_FLAGS
    assert RULE in FORCEABLE_RULES


def test_it_leaves_out_the_judged_week_and_the_nights_away() -> None:
    nights = [date(2026, 9, 20) + timedelta(days=offset) for offset in range(30)]
    left_out = hrv_normal_leave_out(date(2026, 10, 8), [HOLIDAY], nights)
    judged = {date(2026, 10, 8) - timedelta(days=offset) for offset in range(7)}
    away = {date(2026, 9, 28) + timedelta(days=offset) for offset in range(9)}
    assert left_out == frozenset(judged | away)


def test_the_7_day_normal_leaves_out_the_week_it_judges() -> None:
    inputs = GradingInputs(subject_date=DAY, acute={}, hrv_nights=_nights(40.0))
    off = _hrv_week_on(inputs, DAY, in_recovery_week=False)
    on = _hrv_week_on(
        replace(inputs, hrv_normal_leaves_out_judged_week=True), DAY, in_recovery_week=False
    )
    assert off.centre is not None and on.centre is not None
    assert on.centre == pytest.approx(47.0, abs=0.05)
    assert off.centre < on.centre


def test_nights_away_leave_the_7_day_normal_too() -> None:
    nights = _nights(47.0)
    away = frozenset(night for night, _ in nights[30:40])
    low_away = tuple((night, 30.0 if night in away else value) for night, value in nights)
    inputs = GradingInputs(
        subject_date=DAY, acute={}, hrv_nights=low_away, hrv_history_nights_away=away
    )
    off = _hrv_week_on(inputs, DAY, in_recovery_week=False)
    on = _hrv_week_on(
        replace(inputs, hrv_normal_leaves_out_judged_week=True), DAY, in_recovery_week=False
    )
    assert off.centre is not None and on.centre is not None
    assert on.centre > off.centre


def test_the_acute_rails_normal_leaves_out_the_named_nights() -> None:
    """Six low nights in the judged week widen his spread and lower the floor; left out,
    the floor rises, so (e) mostly adds caution."""
    nights = _nights(38.0)
    history = [
        DailyMetric(calendar_date=night, hrv_last_night_avg_ms=value)
        for night, value in nights
        if night < DAY
    ]
    today = DailyMetric(calendar_date=DAY, hrv_last_night_avg_ms=38.0)
    off = _hrv_rail(today, history)
    on = _hrv_rail(today, history, leave_out=hrv_normal_leave_out(DAY, [], [n for n, _ in nights]))
    assert on["baselineSampleCount"] == off["baselineSampleCount"] - 6
    assert on["acuteFloorMs"] > off["acuteFloorMs"]


def _outcomes(replayed: dict[date, Any]) -> dict[date, tuple[str, list[str]]]:
    return {day: (m.graded_label, _action_list(m)) for day, m in replayed.items()}


@pytest.fixture(scope="module")
def forced_on(fixture: dict[str, Any]) -> dict[date, Any]:
    return _replayed(fixture, rules_on={RULE})


@pytest.fixture(scope="module")
def forced_off(fixture: dict[str, Any]) -> dict[date, Any]:
    return _replayed(fixture, rules_off={RULE})


def _rail(replayed: dict[date, Any], day: date) -> dict[str, Any]:
    return dict(replayed[day].context["acutePhysiology"]["overnightHrv"])


def test_forced_off_is_todays_replay(fixture: dict[str, Any], forced_off: dict[date, Any]) -> None:
    """Recomputing the acute rail without the rule moves nothing the fixture holds."""
    assert _outcomes(forced_off) == _outcomes(_replayed(fixture))


def test_forced_on_reaches_the_replays_acute_rail(
    forced_on: dict[date, Any], forced_off: dict[date, Any]
) -> None:
    on, off = _rail(forced_on, date(2026, 9, 18)), _rail(forced_off, date(2026, 9, 18))
    assert on["baselineSampleCount"] < off["baselineSampleCount"]
    assert on["acuteFloorMs"] > off["acuteFloorMs"]


def test_with_little_history_his_normal_keeps_the_nights(
    forced_on: dict[date, Any], forced_off: dict[date, Any]
) -> None:
    """16 Jul, five weeks into his reliable nights: leaving out the week would take his
    normal under the rail's minimum and lift the morning's off-the-bike floor, so his
    normal keeps the nights and the rail judges exactly as it does today."""
    on, off = _rail(forced_on, date(2026, 7, 16)), _rail(forced_off, date(2026, 7, 16))
    assert on["baselineSampleCount"] == off["baselineSampleCount"]
    assert (on["triggered"], on["acuteFloorMs"]) == (off["triggered"], off["acuteFloorMs"])
    assert off["triggered"] is True


def test_the_7_day_normal_keeps_the_nights_when_too_few_would_remain() -> None:
    # 25 nights before the morning: enough to judge by, but only 19 once the week is out.
    short = tuple(night for night in _nights(40.0) if night[0] >= DAY - timedelta(days=25))
    inputs = GradingInputs(subject_date=DAY, acute={}, hrv_nights=short)
    off = _hrv_week_on(inputs, DAY, in_recovery_week=False)
    on = _hrv_week_on(
        replace(inputs, hrv_normal_leaves_out_judged_week=True), DAY, in_recovery_week=False
    )
    assert (on.rating, on.centre) == (off.rating, off.centre)


def test_forced_on_changes_no_fixture_colour_or_action(
    forced_on: dict[date, Any], forced_off: dict[date, Any]
) -> None:
    on, off = _outcomes(forced_on), _outcomes(forced_off)
    assert [day for day in sorted(on) if on[day] != off[day]] == []
