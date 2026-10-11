"""The proposed plan cannot hide a multiplied VO₂ dose or a lost safeguard."""

from datetime import date, datetime

import pytest

from src.services.next_plan import next_plan_draft
from src.services.plan_changes import (
    BY_COACH,
    BY_MARK,
    PlanChangeRefused,
    apply_change,
    normalise_draft,
)
from src.services.plan_protections import (
    PLAN_THREE_VO2_RATIONALE,
    RECOVERY_CAUTION,
    VO2_CAUTION,
    plan_comparison,
    vo2_work_minutes,
)


def _draft() -> dict:
    return next_plan_draft(
        start_date=date(2026, 10, 19),
        ftp_watts=280,
        athlete_name="Mark",
        generated_at_utc=datetime(2026, 10, 7, 7),
        plan_number=3,
    )


def test_plan_three_peak_is_twenty_minutes_and_four_sets_are_counted() -> None:
    draft = _draft()
    week = draft["weeks"][9]
    vo2 = next(workout for workout in week["workouts"] if workout["kind"] == "vo2")
    assert vo2_work_minutes(vo2["structuredWorkout"], vo2["intensityTarget"]) == 20

    with pytest.raises(PlanChangeRefused) as error:
        apply_change(
            draft,
            {
                "kind": "intervals",
                "session": vo2["id"],
                "repeat": 6,
                "workSec": 180,
                "workPct": 119,
                "restSec": 30,
                "restPct": 55,
            },
            today=date(2026, 10, 11),
            by=BY_MARK,
            at_utc=datetime(2026, 10, 11, 12),
        )
    assert "72 min" in error.value.words
    assert "30 min" in error.value.words


def test_removing_the_ramp_test_has_fixed_caution_and_accept_comparison() -> None:
    draft = _draft()
    test = next(workout for workout in draft["weeks"][0]["workouts"] if workout["kind"] == "test")
    applied = apply_change(
        draft,
        {"kind": "remove", "session": test["id"]},
        today=date(2026, 10, 11),
        by=BY_MARK,
        at_utc=datetime(2026, 10, 11, 12),
    )
    assert "ramp test" in applied.summary.lower()
    comparison = plan_comparison(applied.draft)
    assert comparison["test"]["asProposed"] is not None
    assert comparison["test"]["yourPlan"] is None
    assert len(comparison["vo2Sessions"]) == 12
    assert [row["week"] for row in comparison["recoveryWeeks"]] == [3, 6, 9]


def test_accept_comparison_shows_a_vo2_session_moved_to_another_day() -> None:
    draft = _draft()
    vo2 = next(workout for workout in draft["weeks"][1]["workouts"] if workout["kind"] == "vo2")
    moved = apply_change(
        draft,
        {"kind": "move", "session": vo2["id"], "toDate": "2026-10-26"},
        today=date(2026, 10, 11),
        by=BY_MARK,
        at_utc=datetime(2026, 10, 11, 12),
    )
    comparison = plan_comparison(moved.draft)
    row = next(item for item in comparison["vo2Sessions"] if item["week"] == 2)
    assert row["asProposed"].startswith("2026-10-27:")
    assert row["yourPlan"].startswith("2026-10-26:")


def test_coach_offer_cannot_hide_lost_vo2_and_a_heavier_recovery_week() -> None:
    draft = _draft()
    vo2 = next(workout for workout in draft["weeks"][1]["workouts"] if workout["kind"] == "vo2")
    removed = apply_change(
        draft,
        {"kind": "remove", "session": vo2["id"]},
        today=date(2026, 10, 11),
        by=BY_COACH,
        at_utc=datetime(2026, 10, 11, 12),
    )
    assert VO2_CAUTION in removed.summary

    recovery = draft["weeks"][2]
    heavier = apply_change(
        draft,
        {"kind": "add", "date": recovery["startDate"], "sessionType": "zone2", "minutes": 60},
        today=date(2026, 10, 11),
        by=BY_MARK,
        at_utc=datetime(2026, 10, 11, 12),
    )
    assert RECOVERY_CAUTION in heavier.summary


def test_two_small_additions_trigger_caution_against_the_proposed_recovery_week() -> None:
    draft = _draft()
    first = apply_change(
        draft,
        {"kind": "add", "date": "2026-11-02", "sessionType": "zone2", "minutes": 20},
        today=date(2026, 10, 11),
        by=BY_MARK,
        at_utc=datetime(2026, 10, 11, 12),
    )
    assert RECOVERY_CAUTION not in first.summary
    second = apply_change(
        first.draft,
        {"kind": "add", "date": "2026-11-06", "sessionType": "zone2", "minutes": 20},
        today=date(2026, 10, 11),
        by=BY_MARK,
        at_utc=datetime(2026, 10, 11, 12),
    )
    assert RECOVERY_CAUTION in second.summary


def test_existing_plan_three_draft_gets_its_missing_rationale_on_read() -> None:
    draft = _draft()
    assert PLAN_THREE_VO2_RATIONALE not in draft["whyThisPlan"]
    assert normalise_draft(draft)["whyThisPlan"].count(PLAN_THREE_VO2_RATIONALE) == 1
