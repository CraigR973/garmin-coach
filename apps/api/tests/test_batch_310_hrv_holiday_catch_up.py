"""Batch 310 — after a holiday, an HRV average still catching up is a little off.

Since Batch 304 a 7-day HRV dip that lasts marks autonomic clearly off. After a holiday
the 7-day mean lags his nights: on 4 Oct 2026 his nights were 36-39 ms against a usual 47,
and even with his nights back to 47 ms from Wed 7 Oct the week stays marked until Sat
10 Oct, so his first hard session back (Thu 8 Oct's Sweet Spot, in a consolidation week)
would be eased a zone. Craig's rule of 4 Oct: a marked 7-day reading counts as a little
off when the seven nights it averages include a night he slept away, last night was at
home, and his last two nights are each at or above the line the reading itself uses (his
normal minus the smallest worthwhile change). It never takes a little off to nothing,
and every floor still runs.

* **The 4 Oct computation**, on his real nights to 4 Oct (the 295 fixture, extended on
  4 Oct) and the two returns the ledger measured.
* **The edges**: a night away is dated by the morning after it; one night under the line;
  nights still low; still away; a mild reading; the floors.
* **21 and 22 Jul through the replay**, the only mornings of his history it changes.
* **From now on only**: a graded morning stored before the rule replays without it, and
  one stored with it replays from the nights away it saw, whatever the record says later.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import Any

import pytest

from src.models.coaching import DailyMetric, PlanBlock, Sleep
from src.services.holiday_pause import HolidayWindow
from src.services.morning_verdict import _hrv_rail, graded_verdict_packet
from src.services.verdict_grading import (
    ACTION_AS_PLANNED,
    ACTION_EASE_HARD,
    ACTION_HOLD_TARGETS,
    ACTION_MOVE_OR_HOLD,
    ACTION_NO_TRAINING,
    ACTION_OFF_THE_BIKE,
    ACTION_RECOVERY,
    ACTION_SHORTENED_Z2,
    DOMAIN_AUTONOMIC,
    THRESHOLDS,
    GradedVerdict,
    GradingInputs,
    SignalReading,
    build_grading_inputs,
    classify_session,
    grade,
    mark_facing_phrase,
    week_nights_away,
)
from src.services.verdict_replay import (
    MorningRead,
    ReplayReport,
    _planned_workouts_from_packet,
    render_rule_comparison,
    replay_morning,
)
from tests.test_batch_295_verdict_grading import (
    BASE_FEEL,
    BASE_HRV,
    BASE_SLEEP,
    DAY,
    _acute,
    _holiday_windows,
    _inputs,
    _load_fixture,
    _metrics,
    _replayed,
)

CATCHING_UP = "hrv_7_day_catching_up"

#: Thu 8 Oct, W12 consolidation: Sweet Spot 1 x 30 min at 89%, his first hard session back.
SWEET_SPOT = classify_session(
    session_id="sweet-spot",
    title="Sweet Spot 1 x 30 min",
    workout_type="bike_sweet_spot",
    planned_minutes=58,
    ir={"steps": [{"durationSec": 1800, "powerStartPct": 89, "powerEndPct": 89}]},
)

#: The two returns the ledger measured on 4 Oct, nightly from Mon 5 Oct: his last two
#: nights away still low, then back to 47 ms from Wed 7 Oct; or a gradual return.
BACK_FROM_7_OCT = (38, 38, *[47] * 14)
GRADUAL = (38, 38, 41, 43, 45, *[47] * 11)


@pytest.fixture(scope="module")
def fixture() -> dict[str, Any]:
    return _load_fixture()


def _his_nights(fixture: dict[str, Any]) -> dict[date, float]:
    """His overnight HRV as the engine reads it: the wake rows, to 4 Oct 2026."""
    return {
        date.fromisoformat(row[0]): float(row[2])
        for row in fixture["wakeMetrics"]
        if row[2] is not None
    }


def _blocks(fixture: dict[str, Any]) -> list[PlanBlock]:
    return [
        PlanBlock(
            name=name,
            block_type=block_type,
            start_date=date.fromisoformat(start),
            end_date=date.fromisoformat(end),
        )
        for name, block_type, start, end in fixture["blocks"]
    ]


def _return_morning(
    fixture: dict[str, Any],
    day: date,
    future: Sequence[float],
    *,
    windows: Sequence[HolidayWindow] | None = None,
    symptoms: str | None = None,
    rhr_rise: int = 0,
) -> GradingInputs:
    """One morning of his return, through the live builder, with nothing else off.

    His real nights to 4 Oct, then ``future`` from 5 Oct; the acute rail computed from
    them as the morning computes it; his stored holiday windows and plan blocks.
    """
    nights = {
        **_his_nights(fixture),
        **{date(2026, 10, 5) + timedelta(days=i): float(v) for i, v in enumerate(future)},
    }
    history = {night: value for night, value in nights.items() if night < day}
    rail = _hrv_rail(
        DailyMetric(calendar_date=day, hrv_last_night_avg_ms=nights.get(day)),
        [
            DailyMetric(calendar_date=night, hrv_last_night_avg_ms=value)
            for night, value in sorted(history.items())
        ],
    )
    acute = {**_acute(symptoms=symptoms, rhr_rise=rhr_rise), "overnightHrv": rail}
    acute["requiresBikeRest"] = acute["requiresBikeRest"] or rail["requiresBikeRest"]
    inputs = build_grading_inputs(
        subject_date=day,
        acute=acute,
        last_night_hrv_ms=nights.get(day),
        hrv_history=history,
        sleep_score_raw=80,
        sleep_score_age_adjusted=80,
        sleep_minutes=450.0,
        sleep_minutes_history={
            day - timedelta(days=offset): BASE_SLEEP[offset % 3] for offset in range(1, 85)
        },
        acwr=1.0,
        recovery_time_min=600.0,
        yesterday_load="easy",
        feel=8,
        feel_history={
            day - timedelta(days=offset): BASE_FEEL[offset % 3] for offset in range(1, 31)
        },
        readiness_level="HIGH",
        readiness_score=70.0,
        readiness_lower_quartile=55.0,
        planned_workouts=(),
        rest_day=False,
        blocks=_blocks(fixture),
        holiday_windows=_holiday_windows(fixture) if windows is None else windows,
    )
    return replace(inputs, sessions=(SWEET_SPOT,))


def _week(verdict: GradedVerdict) -> SignalReading:
    """The 7-day HRV reading, whichever line rated it."""
    return next(
        signal
        for signal in verdict.domain(DOMAIN_AUTONOMIC).signals
        if signal.signal.startswith("hrv_7_day")
    )


def _actions(verdict: GradedVerdict) -> list[str]:
    return [item.action for item in verdict.actions]


def _without_rule(inputs: GradingInputs) -> GradedVerdict:
    return grade(replace(inputs, hrv_holiday_catch_up=False))


def _words(week: int, usual: int) -> str:
    return (
        "your HRV is back to normal, but your 7-day average is still catching up after "
        f"your holiday ({week} ms against {usual})"
    )


# -- a night away is dated by the morning after it ---------------------------------------


@pytest.mark.parametrize(
    ("day", "away"),
    [
        # He flew out on the morning of 27 Sep: that morning's night was at home, so
        # late September's training dip is not a holiday week.
        (date(2026, 9, 27), []),
        (date(2026, 9, 28), ["2026-09-28"]),
        (
            date(2026, 10, 4),
            ["2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02"]
            + ["2026-10-03", "2026-10-04"],
        ),
        # Home on the evening of 6 Oct: the night before 7 Oct is his first at home.
        (
            date(2026, 10, 7),
            ["2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04", "2026-10-05"] + ["2026-10-06"],
        ),
        (date(2026, 10, 12), ["2026-10-06"]),
        (date(2026, 10, 13), []),
        # July: away 12-16 Jul, his nights dated 13-16 Jul.
        (date(2026, 7, 17), ["2026-07-13", "2026-07-14", "2026-07-15", "2026-07-16"]),
        (date(2026, 7, 22), ["2026-07-16"]),
        (date(2026, 7, 23), []),
    ],
)
def test_a_night_away_is_dated_by_the_morning_after_it(
    fixture: dict[str, Any], day: date, away: list[str]
) -> None:
    nights = week_nights_away(day, _holiday_windows(fixture))
    assert sorted(night.isoformat() for night in nights) == away


# -- the 4 Oct computation, on his real nights -------------------------------------------


@pytest.mark.parametrize(
    ("day", "signal", "rating", "without"),
    [
        # His last night away (6 Oct) was still low, so two nights are not back yet.
        (date(2026, 10, 7), "hrv_7_day", "marked", "marked"),
        (date(2026, 10, 8), CATCHING_UP, "mild", "marked"),
        (date(2026, 10, 9), CATCHING_UP, "mild", "marked"),
        (date(2026, 10, 10), CATCHING_UP, "mild", "marked"),
        # The week has caught up by itself.
        (date(2026, 10, 11), "hrv_7_day", "none", "none"),
    ],
)
def test_back_to_normal_from_wednesday(
    fixture: dict[str, Any], day: date, signal: str, rating: str, without: str
) -> None:
    inputs = _return_morning(fixture, day, BACK_FROM_7_OCT)
    reading = _week(grade(inputs))
    assert (reading.signal, reading.rating) == (signal, rating)
    assert _week(_without_rule(inputs)).rating == without


def test_his_first_hard_session_back_is_held_not_eased(fixture: dict[str, Any]) -> None:
    """Thu 8 Oct, W12 consolidation: nothing else is off, so the Sweet Spot holds."""
    inputs = _return_morning(fixture, date(2026, 10, 8), BACK_FROM_7_OCT)
    verdict = grade(inputs)
    assert verdict.label == "Green (held)"
    assert _actions(verdict) == [ACTION_HOLD_TARGETS]
    assert verdict.summary == f"One thing is a little off: {_words(40, 46)}."

    before = _without_rule(inputs)
    assert before.label == "Amber"
    assert _actions(before) == [ACTION_EASE_HARD]


def test_the_words_carry_his_numbers_each_morning(fixture: dict[str, Any]) -> None:
    summaries = {
        day: grade(_return_morning(fixture, day, BACK_FROM_7_OCT)).summary
        for day in (date(2026, 10, 8), date(2026, 10, 9), date(2026, 10, 10))
    }
    assert summaries == {
        date(2026, 10, 8): f"One thing is a little off: {_words(40, 46)}.",
        date(2026, 10, 9): f"One thing is a little off: {_words(42, 46)}.",
        date(2026, 10, 10): f"One thing is a little off: {_words(43, 46)}.",
    }


@pytest.mark.parametrize(
    ("day", "rating"),
    [
        (date(2026, 10, 7), "marked"),
        (date(2026, 10, 8), "marked"),
        (date(2026, 10, 9), "marked"),
        # 45 then 47 ms: two nights back.
        (date(2026, 10, 10), "mild"),
        (date(2026, 10, 11), "mild"),
        (date(2026, 10, 12), "none"),
    ],
)
def test_a_gradual_return(fixture: dict[str, Any], day: date, rating: str) -> None:
    reading = _week(grade(_return_morning(fixture, day, GRADUAL)))
    assert reading.rating == rating
    if rating == "mild":
        assert reading.signal == CATCHING_UP


# -- the edges ---------------------------------------------------------------------------


def test_one_night_under_the_line_at_home_marks_the_week_again(fixture: dict[str, Any]) -> None:
    """A 40 ms night on Fri 9 Oct ends it: that morning and the next are marked again.

    304's streak counts the 7-day rating, which this rule leaves alone, so on 10 Oct the
    lifted 8 Oct still counts among the mornings under the line (2-10 Oct, nine).
    """
    dipped = (38, 38, 47, 47, 40, *[47] * 11)
    readings = {
        day: _week(grade(_return_morning(fixture, day, dipped)))
        for day in (date(2026, 10, 8), date(2026, 10, 9), date(2026, 10, 10))
    }
    assert (readings[date(2026, 10, 8)].signal, readings[date(2026, 10, 8)].rating) == (
        CATCHING_UP,
        "mild",
    )
    assert (readings[date(2026, 10, 9)].signal, readings[date(2026, 10, 9)].rating) == (
        "hrv_7_day",
        "marked",
    )
    tenth = readings[date(2026, 10, 10)]
    assert (tenth.signal, tenth.rating, tenth.streak) == ("hrv_7_day_persistent", "marked", 9)


def test_nights_still_low_once_home_stay_marked(fixture: dict[str, Any]) -> None:
    still_low = (38,) * 16
    for offset in range(2, 9):
        day = date(2026, 10, 5) + timedelta(days=offset)
        reading = _week(grade(_return_morning(fixture, day, still_low)))
        assert reading.rating == "marked", day
        assert reading.signal != CATCHING_UP, day


def test_it_waits_until_he_is_home(fixture: dict[str, Any]) -> None:
    """Back to normal while still away (5-6 Oct): 6 Oct stays marked, 7 Oct is lifted."""
    back_while_away = (47,) * 16
    away = _week(grade(_return_morning(fixture, date(2026, 10, 6), back_while_away)))
    assert away.rating == "marked"
    home = _week(grade(_return_morning(fixture, date(2026, 10, 7), back_while_away)))
    assert (home.signal, home.rating) == (CATCHING_UP, "mild")


def test_without_a_holiday_the_lag_still_counts(fixture: dict[str, Any]) -> None:
    """The same nights with no holiday recorded: 8 Oct stays clearly off (311's question)."""
    inputs = _return_morning(fixture, date(2026, 10, 8), BACK_FROM_7_OCT, windows=[])
    assert inputs.hrv_nights_away == frozenset()
    assert _week(grade(inputs)).rating == "marked"


def test_a_mild_reading_stays_mild_and_takes_the_words() -> None:
    """A week a little under his line, two nights away in it, the last two back: still mild.

    The rule never takes "a little off" to nothing, so a hard session is still held.
    """
    week = [40.0, 40.0, 46.0, 46.0, 46.0, 46.0, 46.0]  # mean 44.3, under 44.96, over 42.92
    nights = [(DAY - timedelta(days=offset), BASE_HRV[offset % 3]) for offset in range(90, 6, -1)]
    nights[-2:] = [(DAY - timedelta(days=8), 55.0), (DAY - timedelta(days=7), 52.0)]
    nights += [(DAY - timedelta(days=6 - i), value) for i, value in enumerate(week)]
    inputs = replace(
        _inputs(),
        hrv_nights=tuple(nights),
        hrv_nights_away=frozenset({DAY - timedelta(days=6), DAY - timedelta(days=5)}),
    )
    before = _week(_without_rule(inputs))
    assert (before.signal, before.rating) == ("hrv_7_day", "mild")

    verdict = grade(inputs)
    reading = _week(verdict)
    assert (reading.signal, reading.rating) == (CATCHING_UP, "mild")
    assert verdict.label == "Green (held)"


def test_304s_low_night_clause_is_never_lifted() -> None:
    """A low week with last night under his acute floor stays marked, whatever else holds."""
    week = [43.0, 43.0, 43.0, 43.0, 43.0, 46.0, 46.0]  # mild, and only since today
    nights = [(DAY - timedelta(days=offset), BASE_HRV[offset % 3]) for offset in range(90, 6, -1)]
    nights[-2:] = [(DAY - timedelta(days=8), 55.0), (DAY - timedelta(days=7), 55.0)]
    nights += [(DAY - timedelta(days=6 - i), value) for i, value in enumerate(week)]
    inputs = replace(
        _inputs(overnight="capped"),
        hrv_nights=tuple(nights),
        hrv_nights_away=frozenset({DAY - timedelta(days=6)}),
    )
    reading = _week(grade(inputs))
    assert (reading.signal, reading.rating) == ("hrv_7_day_low_night", "marked")


@pytest.mark.parametrize(
    ("symptoms", "rhr_rise", "status", "floor", "action"),
    [
        ("fever_aches", 0, "Red", "no_training", ACTION_NO_TRAINING),
        (None, 7, "Amber", "bike_rest", ACTION_OFF_THE_BIKE),
    ],
)
def test_the_floors_still_run(
    fixture: dict[str, Any],
    symptoms: str | None,
    rhr_rise: int,
    status: str,
    floor: str,
    action: str,
) -> None:
    inputs = _return_morning(
        fixture, date(2026, 10, 8), BACK_FROM_7_OCT, symptoms=symptoms, rhr_rise=rhr_rise
    )
    for verdict in (grade(inputs), _without_rule(inputs)):
        assert (verdict.status, verdict.floor, _actions(verdict)) == (status, floor, [action])


# -- 21 and 22 Jul through the replay ------------------------------------------------------

#: What the replay of his whole history finds: (without the rule, with it).
JULY: dict[date, tuple[tuple[str, list[str]], tuple[str, list[str]]]] = {
    # A very poor night is still clearly off; his HRV is back to normal: Amber, Zone 2 kept.
    date(2026, 7, 21): (("Red", [ACTION_SHORTENED_Z2]), ("Amber", [ACTION_AS_PLANNED])),
    # Nothing else off: the VO2 is moved or held at its targets, not eased.
    date(2026, 7, 22): (("Amber", [ACTION_EASE_HARD]), ("Green (held)", [ACTION_MOVE_OR_HOLD])),
}
#: The nights away inside each morning's week (away 12-16 Jul: nights 13-16 Jul).
JULY_NIGHTS_AWAY = {
    date(2026, 7, 21): ["2026-07-15", "2026-07-16"],
    date(2026, 7, 22): ["2026-07-16"],
}


@pytest.fixture(scope="module")
def replayed(fixture: dict[str, Any]) -> dict[date, Any]:
    return _replayed(fixture)


@pytest.fixture(scope="module")
def before(fixture: dict[str, Any]) -> dict[date, Any]:
    return _replayed(fixture, before=310)


def _shown(morning: Any) -> tuple[str, list[str]]:
    return morning.graded_label, _actions(morning.graded)


@pytest.mark.parametrize("day", sorted(JULY))
def test_21_and_22_jul_are_held_at_a_little_off(
    replayed: dict[date, Any], before: dict[date, Any], day: date
) -> None:
    old, new = JULY[day]
    assert _shown(before[day]) == old
    assert _shown(replayed[day]) == new
    reading = _week(replayed[day].graded)
    assert (reading.signal, reading.rating) == (CATCHING_UP, "mild")
    assert replayed[day].graded.references["hrvWeekNightsAway"] == JULY_NIGHTS_AWAY[day]


def test_every_other_fixture_morning_is_unchanged(
    replayed: dict[date, Any], before: dict[date, Any]
) -> None:
    others = sorted(set(replayed) - set(JULY))
    assert len(others) == 12
    for day in others:
        assert _shown(replayed[day]) == _shown(before[day]), day


def test_22_jul_reads_in_marks_words(replayed: dict[date, Any]) -> None:
    assert replayed[date(2026, 7, 22)].graded.summary == (
        f"One thing is a little off: {_words(43, 47)}."
    )


def test_27_sep_stays_clearly_off(replayed: dict[date, Any]) -> None:
    """A night at home (he flew out that morning): late September's dip still counts."""
    morning = replayed[date(2026, 9, 27)]
    assert _shown(morning) == ("Red", [ACTION_RECOVERY])
    assert _week(morning.graded).rating == "marked"
    assert morning.graded.references["hrvWeekNightsAway"] == []


# -- the committed replay shows what the rule changes ------------------------------------


def _report(mornings: dict[date, Any]) -> ReplayReport:
    days = sorted(mornings)
    return ReplayReport(start=days[0], end=days[-1], mornings=[mornings[day] for day in days])


def test_the_replay_can_grade_without_the_rule(
    fixture: dict[str, Any], before: dict[date, Any]
) -> None:
    without = _replayed(fixture, rules_off={"hrv_holiday_catch_up"})
    assert {day: _shown(morning) for day, morning in without.items()} == {
        day: _shown(morning) for day, morning in before.items()
    }


def test_the_replay_refuses_a_rule_it_does_not_know(fixture: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="unknown graded rules"):
        _replayed(fixture, rules_off={"hrv_holiday"})


def test_the_comparison_lists_exactly_21_and_22_jul(
    fixture: dict[str, Any], replayed: dict[date, Any]
) -> None:
    without = _replayed(fixture, rules_off={"hrv_holiday_catch_up"})
    text = render_rule_comparison(
        _report(replayed), _report(without), rules_off={"hrv_holiday_catch_up"}
    )
    assert "Batch 310, the HRV average catching up after a holiday" in text
    assert "- **Changed:** 2 of 14 mornings" in text
    assert "| Tue 21 Jul | Red | Amber | shortened_zone2 → as_planned |" in text
    assert "| Wed 22 Jul | Amber | Green (held) | ease_hard → move_or_hold |" in text
    reds = sum(m.graded.status == "Red" for m in without.values())
    assert f"- **Red, without → with:** {reds} → {reds - 1}" in text


# -- from now on only --------------------------------------------------------------------


def _replay_as_stored(
    fixture: dict[str, Any],
    morning: Any,
    day: date,
    references: dict[str, Any],
    *,
    windows: Sequence[HolidayWindow],
) -> Any:
    """Replay ``morning`` as production would have stored it, with ``references``."""
    [day_packet] = [m for m in fixture["mornings"] if m["subjectDate"] == day.isoformat()]
    planned = _planned_workouts_from_packet(day, day_packet["plannedWorkouts"])
    packet = graded_verdict_packet(
        morning.ladder_packet, morning.graded, planned, breathwork_line=None
    )
    read = MorningRead(
        id=uuid.uuid4(),
        subject_date=day,
        generated_at_utc=datetime.combine(day, datetime.min.time()),
        created_at=datetime.combine(day, datetime.min.time()),
        verdict=packet["status"],
        daily_metrics=day_packet["dailyMetrics"],
        sleep=day_packet["sleep"],
        manual_entries=day_packet["manualEntries"],
        planned_workouts=day_packet["plannedWorkouts"],
        yesterday_load=day_packet["yesterdayLoad"],
        rest_day=day_packet["restDay"],
        readiness_trend=None,
        age_adjusted=day_packet["ageAdjusted"],
        engine=packet["engine"],
        acute=packet["acutePhysiology"],
        held=packet["held"],
        references=references,
    )
    sleeps = {
        date.fromisoformat(row[0]): Sleep(
            calendar_date=date.fromisoformat(row[0]),
            duration_sec=row[1],
            resting_heart_rate_bpm=row[2],
            average_spo2_pct=row[3],
            lowest_spo2_pct=row[4],
            average_respiration=row[5],
        )
        for row in fixture["sleeps"]
    }
    return replay_morning(
        read,
        metrics=_metrics(fixture["wakeMetrics"]),
        baseline_metrics=_metrics(fixture["preferredMetrics"]),
        sleeps=sleeps,
        feels={date.fromisoformat(d): score for d, score in fixture["feels"]},
        blocks=_blocks(fixture),
        holiday_windows=windows,
    )


def test_a_morning_graded_before_the_rule_replays_without_it(
    fixture: dict[str, Any], before: dict[date, Any]
) -> None:
    """22 Jul as it would have been stored before 310: neither key."""
    day = date(2026, 7, 22)
    references = dict(before[day].graded.references)
    references.pop("hrvHolidayCatchUp")
    references.pop("hrvWeekNightsAway")

    again = _replay_as_stored(
        fixture, before[day], day, references, windows=_holiday_windows(fixture)
    )

    assert again.shown_label == "Amber"
    assert again.graded_label == "Amber"
    assert again.reproduces_production is True


def test_a_morning_graded_with_the_rule_off_replays_with_it_off(
    fixture: dict[str, Any], before: dict[date, Any]
) -> None:
    """The flag decides, not the nights: stored off, with its nights away, it stays off."""
    day = date(2026, 7, 22)
    references = dict(before[day].graded.references)
    assert references["hrvHolidayCatchUp"] is False
    assert references["hrvWeekNightsAway"] == ["2026-07-16"]

    again = _replay_as_stored(
        fixture, before[day], day, references, windows=_holiday_windows(fixture)
    )

    assert again.graded_label == "Amber"
    assert again.reproduces_production is True


def test_a_morning_graded_under_the_rule_replays_from_what_it_saw(
    fixture: dict[str, Any], replayed: dict[date, Any]
) -> None:
    """22 Jul stored under the rule replays the same even if the holiday record changes."""
    day = date(2026, 7, 22)
    references = dict(replayed[day].graded.references)
    assert references["hrvHolidayCatchUp"] is True
    assert references["hrvWeekNightsAway"] == ["2026-07-16"]

    for windows in (_holiday_windows(fixture), []):
        again = _replay_as_stored(fixture, replayed[day], day, references, windows=windows)
        assert again.shown_label == "Green (held)"
        assert again.graded_label == "Green (held)"
        assert again.reproduces_production is True


# -- the table states the line and its source honestly -----------------------------------


def test_the_table_states_the_catch_up_line_and_its_source() -> None:
    line = THRESHOLDS["hrv_catch_up_nights"]
    assert line.value == 2
    assert line.source.startswith("an engineering choice")
    assert "one night swings about 5 ms" in line.source
    assert "only in the 7 days after a holiday" in line.source
    assert "a little off" in line.reason


def test_the_7_day_marked_line_no_longer_claims_it_never_fired() -> None:
    line = THRESHOLDS["hrv_week_marked_sd"]
    assert "never fired" not in line.reason
    assert "4 Oct 2026" in line.reason


def test_the_phrase_is_the_one_craig_signed_off() -> None:
    reading = SignalReading(
        domain=DOMAIN_AUTONOMIC,
        signal=CATCHING_UP,
        rating="mild",
        value=41.29,
        reference=None,
        reason="",
        usual=46.54,
    )
    assert mark_facing_phrase(reading) == _words(41, 47)
