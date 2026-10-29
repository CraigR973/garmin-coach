"""Batch 322: record what he rode and how it went.

The ride's read now carries the morning's call against what he rode, one clean 0-10
effort and his legs, and the ride's fixed-power check; each morning keeps Garmin's
readiness factors. Grading against the version he was sent was already in place
(``gradingTarget``, Batches 152 and 335), so 322 records which version it was.
Each test failed on ``main`` first.
"""

from __future__ import annotations

import uuid
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from src.models.coaching import ManualEntry, PlannedWorkout
from src.routers.daily_loop_schemas import PostRideCheckInBody
from src.services.fixed_power import fixed_power_check
from src.services.post_workout_analysis import (
    RideGradingTarget,
    _manual_entry_packet,
    call_against_ride,
)
from src.services.readiness_factors import readiness_factors

REPO = Path(__file__).resolve().parents[3]
DRAFT = REPO / "docs" / "drafts" / "2026-10-29-batch-322-wording.md"
WEB = REPO / "apps" / "web" / "src" / "lib" / "rideCheckIn.ts"

WORKOUT = PlannedWorkout(id=uuid.uuid4(), title="Sweet Spot", workout_type="bike_sweet_spot")


def _target(origin: str | None, source: str = "delivered_proposal") -> RideGradingTarget:
    return RideGradingTarget(
        ir={"origin": origin} if origin else {},
        source=source,
        planned_workout=WORKOUT,
        proposal=None,
    )


def _morning(action: str) -> dict[str, Any]:
    return {
        "id": "m1",
        "subjectDate": "2026-10-28",
        "actions": [{"plannedWorkoutId": str(WORKOUT.id), "action": action}],
    }


def _deviation(kind: str = "on_plan", diverged: bool = False) -> dict[str, Any]:
    return {"kind": kind, "diverged": diverged, "wasApprovedAdjustment": False}


# -- the call against what he rode -----------------------------------------------------------


def test_riding_the_eased_version_he_was_sent_is_taking_the_call() -> None:
    took = call_against_ride(_morning("ease_hard"), _target("amber_ease"), _deviation())
    assert took is not None
    assert (took["morningAction"], took["tookTheCall"], took["morningDate"]) == (
        "ease_hard",
        True,
        "2026-10-28",
    )


def test_riding_the_planned_session_the_call_eased_is_not() -> None:
    skipped = call_against_ride(_morning("ease_hard"), _target("as_planned"), _deviation())
    assert skipped is not None and skipped["tookTheCall"] is False
    harder = call_against_ride(
        _morning("as_planned"), _target(None), _deviation("harder_than_planned", True)
    )
    assert harder is not None and harder["tookTheCall"] is False
    assert call_against_ride(_morning("as_planned"), _target(None), _deviation())["tookTheCall"]


def test_no_morning_or_no_planned_ride_is_not_judged() -> None:
    assert call_against_ride(None, _target(None), _deviation()) is None
    free = RideGradingTarget(ir=None, source="none", planned_workout=None, proposal=None)
    assert call_against_ride(_morning("as_planned"), free, _deviation("free_ride")) is None


# -- one clean effort, and his legs ----------------------------------------------------------


def test_effort_is_0_to_10_and_his_legs_are_named() -> None:
    with pytest.raises(ValidationError):
        PostRideCheckInBody(rpe=14)
    assert PostRideCheckInBody(rpe=7, subjectiveScore=6).rpe == 7
    entry = ManualEntry(id=uuid.uuid4(), entry_date=date(2026, 10, 28), rpe=7, subjective_score=6)
    packet = _manual_entry_packet(entry)
    assert packet is not None
    assert (packet["effort"], packet["legs"], packet["effortOffScale"]) == (7, 6, False)
    old = ManualEntry(id=uuid.uuid4(), entry_date=date(2026, 9, 1), rpe=14)
    old_packet = _manual_entry_packet(old)
    assert old_packet is not None and (old_packet["effort"], old_packet["effortOffScale"]) == (
        None,
        True,
    )


# -- the fixed-power check --------------------------------------------------------------------


def _interval(minutes: float, pct: float, target: float, watts: float, hr: float) -> dict[str, Any]:
    return {
        "durationSec": minutes * 60,
        "avgPowerWatts": watts,
        "avgHeartRateBpm": hr,
        "pctFtp": pct,
        "targetPctFtpLow": target,
        "targetPctFtpHigh": target,
        "hrDriftPct": 0.5,
        "label": "Z2",
    }


def test_a_steady_zone_2_block_of_twenty_minutes_is_a_fixed_power_check() -> None:
    check = fixed_power_check(
        [
            {**_interval(10, 60, 55, 160, 100), "targetPctFtpHigh": 80},  # the ramp
            _interval(35, 65.7, 66, 184, 116.3),
            _interval(5, 50, 50, 140, 95),
        ]
    )
    assert check is not None
    assert (check["minutes"], check["powerWatts"], check["avgHeartRateBpm"]) == (35.0, 184, 116.3)


def test_short_hard_or_wandering_blocks_are_not() -> None:
    assert fixed_power_check([_interval(15, 66, 66, 184, 110)]) is None  # too short
    assert fixed_power_check([_interval(25, 90, 90, 250, 140)]) is None  # sweet spot
    assert fixed_power_check([_interval(25, 58, 66, 160, 100)]) is None  # not held in ERG
    assert fixed_power_check(None) is None


# -- Garmin's readiness factors ---------------------------------------------------------------


def test_each_morning_keeps_garmins_readiness_factors() -> None:
    raw = {
        "training_readiness": [
            {
                "score": 61,
                "level": "MODERATE",
                "sleepScoreFactorPercent": 68,
                "sleepScoreFactorFeedback": "MODERATE",
                "recoveryTimeFactorPercent": 10,
                "recoveryTimeFactorFeedback": "POOR",
                "acwrFactorPercent": 69,
                "hrvFactorPercent": 100,
                "sleepHistoryFactorPercent": 66,
                "stressHistoryFactorPercent": 77,
            }
        ]
    }
    factors = readiness_factors(raw)
    assert factors is not None
    assert factors["factors"]["recoveryTime"] == {"percent": 10, "feedback": "POOR"}
    assert set(factors["factors"]) == {
        "sleep",
        "recoveryTime",
        "loadRatio",
        "hrv",
        "sleepHistory",
        "stressHistory",
    }
    assert readiness_factors({}) is None
    assert readiness_factors(None) is None


def test_the_check_in_words_are_in_the_draft() -> None:
    draft = DRAFT.read_text(encoding="utf-8")
    web = WEB.read_text(encoding="utf-8")
    for words in ("Effort (0–10)", "0 easy, 10 all-out", "0 dead, 10 fresh"):
        assert words in draft and words in web, words
