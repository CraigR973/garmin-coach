"""Batch 367.2–.5 — progress and trend claims that pass a noise test.

Wave #6's statistics pass (ST363-02 to -09) found the weekly review's claims firing on
noise: the "ready for a little more" note was three Greens in a row under ERG (shuffled
mornings fired it as often, P 0.53–0.57 a quarter), the fitness drift called a change on
one judged Sunday in seven from shuffled heart rates, the sleep "trend" on 63% of shuffled
weeks, and a REM lever with no effect got a direction on some morning in about a quarter
of seasons. The simulations below use his own spreads and run in CI: each claim must fire
on noise less than one time in ten.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path

from src.services import reviews
from src.services.experiment_evaluation import (
    EARLY_WAKING_DRIVERS,
    RECOMMEND_INCONCLUSIVE,
    RemInterventionNight,
    evaluate_rem_interventions,
    judged_through,
)
from src.services.insights import DriverCorrelation, DriversReport, _drivers_markdown
from src.services.progress_signal import (
    HOLD_SLIPPING,
    READY_NOTE,
    STATUS_STEADY,
    FixedPowerRide,
    HardSession,
    effort_from_check_in,
    fitness_drift,
    progress_signal,
)
from src.services.reviews import SLEEP_SCORE_NIGHT_SD, ReviewDay, _half_trend_evidence

REPO = Path(__file__).resolve().parents[3]
DRAFT = REPO / "docs" / "drafts" / "2026-11-03-batch-367-wording.md"
SUNDAY = date(2026, 11, 1)
TRIALS = 2000
NOISE_CEILING = 0.10


# -- 367.2: a note ERG cannot make true -------------------------------------------------------


def _hard(days_ago: int, effort: float | None, fresh: bool = True) -> HardSession:
    return HardSession(SUNDAY - timedelta(days=days_ago), 10, 10, fresh, effort=effort)


def test_the_note_needs_his_effort_and_never_offers_a_test() -> None:
    manageable = [_hard(6, 6), _hard(4, 6), _hard(2, 7)]
    assert progress_signal([], manageable, as_of=SUNDAY)["note"] == READY_NOTE
    hard_one = [_hard(6, 6), _hard(4, 8), _hard(2, 6)]
    assert progress_signal([], hard_one, as_of=SUNDAY)["readyToProgress"] is False
    unknown = [_hard(6, 6), _hard(4, None), _hard(2, 6)]
    assert progress_signal([], unknown, as_of=SUNDAY)["readyToProgress"] is False
    for words in ("ramp test", "step up", "ready for a little more"):
        assert words not in READY_NOTE


def test_the_note_holds_while_his_heart_rate_is_slipping() -> None:
    rides = [
        FixedPowerRide(SUNDAY - timedelta(days=day), 184, 120 if day < 28 else 110)
        for day in (2, 9, 16, 30, 37, 44)
    ]
    signal = progress_signal(rides, [_hard(6, 6), _hard(4, 6), _hard(2, 6)], as_of=SUNDAY)
    assert (signal["readyToProgress"], signal["heldBecause"]) == (False, HOLD_SLIPPING)


def test_his_effort_comes_from_either_check_in_field() -> None:
    assert effort_from_check_in({"effort": 6, "rpe": 9}) == 6.0
    assert effort_from_check_in({"rpe": 7}) == 7.0
    assert effort_from_check_in({"rpe": True}) is None
    assert effort_from_check_in(None) is None


# -- 367.3: the drift and the sleep trend clear their noise -----------------------------------


def test_the_drift_calls_a_change_on_noise_less_than_one_sunday_in_ten() -> None:
    """ST363-03: his heart rate at Z2 power has SD 3.56 bpm ride to ride."""

    rng = random.Random(363)
    for rides_each in (3, 4, 6):
        fired = 0
        for _ in range(TRIALS):
            days = [2 + 7 * i for i in range(rides_each)] + [30 + 7 * i for i in range(rides_each)]
            rides = [
                FixedPowerRide(SUNDAY - timedelta(days=d), 184, rng.gauss(115, 3.56)) for d in days
            ]
            fired += fitness_drift(rides, as_of=SUNDAY)["status"] != STATUS_STEADY
        assert fired / TRIALS < NOISE_CEILING, (rides_each, fired / TRIALS)


def test_a_real_drift_still_shows() -> None:
    rides = [
        FixedPowerRide(SUNDAY - timedelta(days=d), 184, 108 if d < 28 else 117)
        for d in (2, 9, 16, 30, 37, 44)
    ]
    assert fitness_drift(rides, as_of=SUNDAY)["status"] == "improving"


def _week(scores: list[float]) -> list[ReviewDay]:
    return [
        ReviewDay(day=SUNDAY - timedelta(days=len(scores) - i), sleep_score=round(score))
        for i, score in enumerate(scores)
    ]


def test_the_sleep_trend_fires_on_noise_less_than_one_week_in_ten() -> None:
    """ST363-09: the old 5% rule called a trend on 63% of shuffled weeks."""

    rng = random.Random(9)
    for nights in (7, 30):
        fired = 0
        for _ in range(TRIALS):
            days = _week([rng.gauss(75, SLEEP_SCORE_NIGHT_SD) for _ in range(nights)])
            evidence = _half_trend_evidence(days, "sleep_score", noise_sd=SLEEP_SCORE_NIGHT_SD)
            fired += evidence.trend != "stable"
        assert fired / TRIALS < NOISE_CEILING, (nights, fired / TRIALS)


def test_the_1_nov_week_is_stable() -> None:
    """The first v14 review called 74.0 → 77.8 a rise; the line is about 16 points."""

    week = _week([74, 75, 73, 70, 75, 70, 88])
    evidence = _half_trend_evidence(week, "sleep_score", noise_sd=SLEEP_SCORE_NIGHT_SD)
    assert evidence.trend == "stable"
    assert evidence.min_absolute_delta > 15
    rollup = reviews.compute_review_rollup(
        week,
        [],
        [],
        [],
        period="weekly",
        period_start=week[0].day,
        period_end=week[-1].day,
        planned_count=0,
    )
    assert rollup.sleep.trend == "stable"


# -- 367.4: experiments at fixed points; concurrent measures out; the audit's sign ------------


def _season(rng: random.Random, nights: int) -> list[RemInterventionNight]:
    start = date(2026, 7, 1)
    return [
        RemInterventionNight(
            day=start + timedelta(days=i),
            intervention_id="room_cool_late_cycles",
            response="applied" if i % 2 else "not_applied",
            rem_sleep_pct=rng.gauss(20, 4.8),
            awake_min=rng.gauss(45, 17),
        )
        for i in range(nights)
    ]


def _directed_on(nights: list[RemInterventionNight], looks: list[date]) -> bool:
    for look in looks:
        result = evaluate_rem_interventions([n for n in nights if n.day <= look])
        if result.recommendation not in (None, RECOMMEND_INCONCLUSIVE):
            return True
    return False


def test_a_lever_with_no_effect_rarely_gets_a_direction_at_fixed_points() -> None:
    """ST363-04: looked at daily, about a quarter of null seasons got a direction."""

    rng = random.Random(4)
    trials = 400
    fired = 0
    for _ in range(trials):
        season = _season(rng, 120)
        last = season[-1].day
        points = sorted({judged_through(season[0].day + timedelta(days=d)) for d in range(150)})
        fired += _directed_on(season, [p for p in points if p <= last])
    assert fired / trials < NOISE_CEILING, fired / trials


def test_the_judging_point_is_the_last_whole_month() -> None:
    assert judged_through(date(2026, 11, 3)) == date(2026, 10, 31)
    assert judged_through(date(2026, 11, 30)) == date(2026, 10, 31)
    assert judged_through(date(2026, 12, 1)) == date(2026, 11, 30)


def test_sleep_stress_is_never_a_candidate_cause_of_his_waking() -> None:
    assert "sleep_stress_avg" not in EARLY_WAKING_DRIVERS
    assert "resting_heart_rate_bpm" not in EARLY_WAKING_DRIVERS


def test_the_audit_names_the_judged_coefficient_with_its_own_sign() -> None:
    """ST363-08a: 31 Oct printed fan speed "positive, r=0.4484" over 8 nights, adjusted -0.51."""

    fan = DriverCorrelation(
        "bedroom_peak_fan_speed", "rem_sleep_min", 0.4484, 8, adjusted_coefficient=-0.51
    )
    stress = DriverCorrelation(
        "prev_day_stress_avg", "rem_sleep_min", -0.12, 121, adjusted_coefficient=-0.18
    )
    report = DriversReport({"rem_sleep_min": [fan, stress]}, 121, None, None)
    text = _drivers_markdown(report)
    assert "bedroom_peak_fan_speed" not in text
    assert "prev_day_stress_avg (negative, r=-0.18)" in text


# -- 367.5: the words ---------------------------------------------------------------------------


def test_every_new_line_is_in_the_draft() -> None:
    draft = " ".join(DRAFT.read_text(encoding="utf-8").replace("\n> ", " ").split())
    assert READY_NOTE in draft
