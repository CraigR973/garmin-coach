"""Batch 304 — a persistent HRV dip counts as clearly off.

The graded verdict rated a week of low HRV "a little off" however long it lasted: seven
mild autonomic mornings in a row (21-27 Sep) never escalated, and the 7-day marked line
was set just past his worst week, so it never fired. The trials the engine cites made a
7-day mean under the smallest worthwhile change a low-intensity day. The 1 Oct review
softened that to: marked when the 7-day mean has been under it on three or more mornings
in a row, or is under it with last night under his acute floor (Craig, 1 Oct).

* **The six mornings it changes**, from Mark's own rows (the 295 fixture, extended with
  21-22 Jul and 27 Sep on 3 Oct): replayed under the rule, against the colour and
  actions they had before it.
* **From now on only**: a graded morning stored before the rule replays without it, and
  one stored after replays with it, so the replay reproduces both.
* **The rule's edges** on a synthetic history: one noisy night stays mild, two mornings
  under the line stay mild, the third is marked; a low week with a night under the floor
  is marked at once; on its own it is at worst Amber.
"""

from __future__ import annotations

import itertools
import uuid
from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import Any

import pytest

from src.services.morning_verdict import graded_verdict_packet
from src.services.verdict_grading import (
    ACTION_EASE_HARD,
    ACTION_MOVE_OR_HOLD,
    ACTION_RECOVERY,
    ACTION_SHORTENED_Z2,
    DOMAIN_AUTONOMIC,
    RATING_ORDER,
    THRESHOLDS,
    GradingInputs,
    grade,
    mark_facing_phrase,
)
from src.services.verdict_replay import (
    MorningRead,
    _planned_workouts_from_packet,
    replay_morning,
)
from tests.test_batch_295_verdict_grading import (
    BASE_HRV,
    DAY,
    VO2,
    Z2,
    _acute,
    _inputs,
    _load_fixture,
    _metrics,
    _replayed,
)


@pytest.fixture(scope="module")
def fixture() -> dict[str, Any]:
    return _load_fixture()


@pytest.fixture(scope="module")
def replayed(fixture: dict[str, Any]) -> dict[date, Any]:
    # Batch 310 holds 21 and 22 Jul at "a little off" again (his HRV back to normal a
    # week after his July holiday), so 304's own rule is pinned without it.
    return _replayed(fixture, before=310)


@pytest.fixture(scope="module")
def before(fixture: dict[str, Any]) -> dict[date, Any]:
    return _replayed(fixture, before=304)


def _actions(morning: Any) -> list[str]:
    return [item.action for item in morning.graded.actions]


# -- the six mornings, from his own rows --------------------------------------------------

#: What the replay of every stored morning found on 3 Oct (103 mornings, 6 changed, Red
#: 4 -> 6), and what these fixture rows reproduce: (before, after) as label and actions.
SIX: dict[date, tuple[tuple[str, list[str]], tuple[str, list[str]]]] = {
    # Third morning running under the line, after a very poor night: Red, Zone 2 shortened.
    date(2026, 7, 21): (("Amber", ["as_planned"]), ("Red", [ACTION_SHORTENED_Z2])),
    # The VO2 is eased a zone instead of moved or held.
    date(2026, 7, 22): (("Green (held)", [ACTION_MOVE_OR_HOLD]), ("Amber", [ACTION_EASE_HARD])),
    # The second night under his floor with the week already low: marked at once.
    date(2026, 9, 22): (
        ("Green (held)", ["as_planned", ACTION_MOVE_OR_HOLD]),
        ("Amber", ["as_planned", ACTION_EASE_HARD]),
    ),
    date(2026, 9, 23): (("Green (held)", ["as_planned"]), ("Amber", ["as_planned"])),
    date(2026, 9, 26): (
        ("Green (held)", ["as_planned", "as_planned"]),
        ("Amber", ["as_planned", "as_planned"]),
    ),
    # Seven mornings running and a 51-score night: the VO2 becomes a recovery ride.
    date(2026, 9, 27): (("Amber", [ACTION_EASE_HARD]), ("Red", [ACTION_RECOVERY])),
}


@pytest.mark.parametrize("day", sorted(SIX))
def test_the_six_mornings_change_as_the_review_replayed_them(
    replayed: dict[date, Any], before: dict[date, Any], day: date
) -> None:
    (old_label, old_actions), (new_label, new_actions) = SIX[day]
    assert (before[day].graded_label, _actions(before[day])) == (old_label, old_actions)
    assert (replayed[day].graded_label, _actions(replayed[day])) == (new_label, new_actions)
    assert replayed[day].graded.domain(DOMAIN_AUTONOMIC).rating == "marked"


def test_every_other_fixture_morning_keeps_its_colour_and_actions(
    replayed: dict[date, Any], before: dict[date, Any]
) -> None:
    others = sorted(set(replayed) - set(SIX))
    assert len(others) == 8
    for day in others:
        assert replayed[day].graded_label == before[day].graded_label, day
        assert _actions(replayed[day]) == _actions(before[day]), day


def test_the_words_lead_with_how_long_and_his_numbers(replayed: dict[date, Any]) -> None:
    """The words Craig signed off on Mark's behalf on 3 Oct 2026."""
    assert replayed[date(2026, 9, 23)].graded.summary == (
        "One thing is clearly off: your 7-day HRV average has been below your usual for "
        "3 mornings running (43 ms against 47)."
    )
    assert replayed[date(2026, 9, 22)].graded.summary == (
        "One thing is clearly off: your HRV has been below your usual this week and was "
        "low again last night (39 ms against a usual 47)."
    )
    assert replayed[date(2026, 9, 27)].graded.summary == (
        "Two things are clearly off: your 7-day HRV average has been below your usual for "
        "7 mornings running (44 ms against 47), and a very poor night's sleep (score 51)."
    )


def test_the_packet_carries_the_streak_on_the_persistent_reading_only(
    replayed: dict[date, Any],
) -> None:
    [persistent] = [
        signal
        for signal in replayed[date(2026, 9, 26)]
        .graded.domain(DOMAIN_AUTONOMIC)
        .to_packet()["signals"]
        if signal["rating"] == "marked"
    ]
    assert persistent["signal"] == "hrv_7_day_persistent"
    assert persistent["streak"] == 6
    assert persistent["reason"] == (
        "7-day HRV 43.4 ms has been under his usual 46.9 ms by more than the smallest "
        "worthwhile change for 6 mornings in a row."
    )
    other = replayed[date(2026, 9, 7)].graded.to_packet()["domains"]
    assert all("streak" not in signal for domain in other for signal in domain["signals"])


# -- from now on only ------------------------------------------------------------------


def _replay_as_stored(
    fixture: dict[str, Any], morning: Any, day: date, references: dict[str, Any]
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
    from src.models.coaching import PlanBlock, Sleep

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
    blocks = [
        PlanBlock(
            name=name,
            block_type=block_type,
            start_date=date.fromisoformat(start),
            end_date=date.fromisoformat(end),
        )
        for name, block_type, start, end in fixture["blocks"]
    ]
    return replay_morning(
        read,
        metrics=_metrics(fixture["wakeMetrics"]),
        baseline_metrics=_metrics(fixture["preferredMetrics"]),
        sleeps=sleeps,
        feels={date.fromisoformat(d): score for d, score in fixture["feels"]},
        blocks=blocks,
    )


def test_a_morning_graded_before_the_rule_replays_without_it(
    fixture: dict[str, Any], before: dict[date, Any]
) -> None:
    """22 Sep as it would have been stored before 304: no ``hrvPersistence`` key."""
    day = date(2026, 9, 22)
    references = dict(before[day].graded.references)
    references.pop("hrvPersistence")

    again = _replay_as_stored(fixture, before[day], day, references)

    assert again.shown_label == "Green (held)"
    assert again.graded_label == "Green (held)"
    assert again.reproduces_production is True


def test_a_morning_graded_under_the_rule_replays_with_it(
    fixture: dict[str, Any], replayed: dict[date, Any]
) -> None:
    day = date(2026, 9, 22)
    references = dict(replayed[day].graded.references)
    assert references["hrvPersistence"] is True

    again = _replay_as_stored(fixture, replayed[day], day, references)

    assert again.shown_label == "Amber"
    assert again.graded_label == "Amber"
    assert again.reproduces_production is True


# -- the rule's edges, on a synthetic history -------------------------------------------


def _dipped(low_nights: int, *, low: float = 44.0) -> tuple[tuple[date, float], ...]:
    """His usual nights (42, 47, 52: mean 47, SD 4.1), then ``low_nights`` at ``low``.

    The two nights before the dip are high (52), so a week that reaches back past the
    dip is clearly within his range: the count of mornings under the line is exact.
    """
    start = DAY - timedelta(days=low_nights - 1)
    nights = [(DAY - timedelta(days=offset), BASE_HRV[offset % 3]) for offset in range(95, 0, -1)]
    history = {night: value for night, value in nights if night < start - timedelta(days=2)}
    history[start - timedelta(days=2)] = 52.0
    history[start - timedelta(days=1)] = 52.0
    for offset in range(low_nights):
        history[start + timedelta(days=offset)] = low
    return tuple(sorted(history.items()))


def _autonomic(inputs: GradingInputs) -> Any:
    return grade(inputs).domain(DOMAIN_AUTONOMIC)


def _marked_signal(domain: Any) -> Any:
    return max(domain.signals, key=lambda signal: RATING_ORDER[signal.rating])


def test_one_noisy_night_under_the_floor_stays_mild() -> None:
    """A usual week with last night under his floor: the week is fine, so one night is mild."""
    inputs = _inputs(overnight="capped")
    domain = _autonomic(inputs)
    assert domain.rating == "mild"
    assert {signal.signal for signal in domain.signals if signal.rating != "none"} == {
        "hrv_overnight"
    }


@pytest.mark.parametrize(
    ("low_nights", "rating", "streak"),
    [
        # Under the line from the fifth low night of a week: two mornings, still mild.
        (8, "mild", None),
        # The third morning running is marked.
        (9, "marked", 3),
        (14, "marked", 8),
    ],
)
def test_the_third_morning_under_the_line_is_marked(
    low_nights: int, rating: str, streak: int | None
) -> None:
    inputs = replace(_inputs(), hrv_nights=_dipped(low_nights))
    domain = _autonomic(inputs)
    assert domain.rating == rating
    worst = _marked_signal(domain)
    if streak is None:
        assert worst.signal == "hrv_7_day"
    else:
        assert worst.signal == "hrv_7_day_persistent"
        assert worst.streak == streak


def test_a_low_week_with_a_night_under_the_floor_is_marked_at_once() -> None:
    inputs = replace(_inputs(overnight="capped"), hrv_nights=_dipped(8))
    domain = _autonomic(inputs)
    assert domain.rating == "marked"
    worst = _marked_signal(domain)
    assert worst.signal == "hrv_7_day_low_night"
    assert worst.value == 40  # last night, through the acute rail
    assert mark_facing_phrase(worst) == (
        "your HRV has been below your usual this week and was low again last night "
        "(40 ms against a usual 47)"
    )


def test_without_the_rule_the_same_week_stays_mild() -> None:
    """The flag the replay restores: a morning graded before 304 keeps its mild rating."""
    for low_nights, overnight in ((14, "none"), (8, "capped")):
        inputs = replace(
            _inputs(overnight=overnight), hrv_nights=_dipped(low_nights), hrv_persistence=False
        )
        assert _autonomic(inputs).rating == "mild"
        assert grade(inputs).references["hrvPersistence"] is False


def test_on_its_own_a_persistent_dip_is_at_worst_amber() -> None:
    """Mark's own line: a week of low HRV, all else fine, is at worst Amber."""
    inputs = replace(_inputs(), hrv_nights=_dipped(14))
    verdict = grade(inputs)
    assert verdict.status == "Amber"
    actions = {item.session_id: item.action for item in verdict.actions}
    assert actions == {VO2.id: ACTION_EASE_HARD, Z2.id: "as_planned"}


# -- the invariants, extended to persistence ----------------------------------------------

DIP_LEVELS = (0, 8, 9, 14)  # nights at 44 ms: none, two mornings, three, eight
RANK = {"Green": 0, "Green (held)": 1, "Amber": 2, "Red": 3}
GRID: dict[str, tuple[Any, ...]] = {
    "dip": DIP_LEVELS,
    "overnight": ("none", "capped", "illness"),
    "sleep_score": (80, 70, 55),
    "feel": (8, 5),
}


@pytest.fixture(scope="module")
def grid() -> dict[tuple[int, ...], Any]:
    results: dict[tuple[int, ...], Any] = {}
    for combo in itertools.product(*(range(len(levels)) for levels in GRID.values())):
        dip, overnight, sleep_score, feel = (
            levels[index] for levels, index in zip(GRID.values(), combo, strict=True)
        )
        inputs = _inputs(overnight=overnight, sleep_score=sleep_score, feel=feel)
        if dip:
            inputs = replace(inputs, hrv_nights=_dipped(dip))
        results[combo] = grade(inputs)
    return results


def test_a_longer_dip_or_a_worse_input_never_gives_a_better_colour(
    grid: dict[tuple[int, ...], Any],
) -> None:
    sizes = [len(levels) for levels in GRID.values()]
    for combo, verdict in grid.items():
        for axis, size in enumerate(sizes):
            if combo[axis] + 1 >= size:
                continue
            worse = list(combo)
            worse[axis] += 1
            assert RANK[grid[tuple(worse)].label] >= RANK[verdict.label], (combo, axis)


def test_the_dip_alone_never_makes_red(grid: dict[tuple[int, ...], Any]) -> None:
    for dip_index in range(len(DIP_LEVELS)):
        assert grid[(dip_index, 0, 0, 0)].status in {"Green", "Amber"}


def test_hrv_persistence_alone_never_reaches_a_floor() -> None:
    verdict = grade(replace(_inputs(), hrv_nights=_dipped(14)))
    assert verdict.floor is None
    assert _acute()["requiresBikeRest"] is False


# -- the table states the line and labels the two that never fire ------------------------


def test_the_table_states_the_new_line_with_its_sources() -> None:
    line = THRESHOLDS["hrv_persistence_mornings"]
    assert line.value == 3
    assert "Javaloyes 2019" in line.source
    assert "Vesterinen 2016" in line.source
    assert "Kiviniemi 2007" in line.source
    assert "acute floor" in line.reason


@pytest.mark.parametrize("key", ["hrv_week_marked_sd", "recovery_time_marked_hours"])
def test_the_two_lines_set_past_his_worst_value_say_so(key: str) -> None:
    line = THRESHOLDS[key]
    assert line.source.startswith("set just past his worst observed value")


def test_the_line_that_never_fires_says_so() -> None:
    # The 7-day marked line first fired on 4 Oct 2026, his holiday week; Batch 310
    # corrects its reason and pins it.
    assert "never fired" in THRESHOLDS["recovery_time_marked_hours"].reason
