"""Batch 277 — the swap the app proposed and then refused (22 Sep 2026).

Mark was told to take the day off the bike and, in the same brief, offered a swap
bringing Saturday's session forward onto that day. He accepted it; the app
refused it with *"Red verdict blocks VO2 delivery to Zwift"*; he rode the session
anyway. Every prescription and figure below was read from production.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.services.verdict_scaling import (
    ALACTIC_MAX_WORK_SEC,
    ALACTIC_MIN_RECOVERY_RATIO,
    HIT_FLOOR_PCT,
    blocks_red_vo2,
    ir_has_vo2,
)
from src.services.workout_delivery import expand_structured_steps

Z2 = "Zone 2 ~65–72% FTP"


def _ir(pattern: str, target: str) -> dict[str, Any]:
    sw = {"format": "bike", "steps": [{"label": "block", "target": target, "pattern": pattern}]}
    return {"steps": expand_structured_steps(sw, Z2)}


# Every above-threshold prescription in Mark's active plan, read 2026-09-22.
@pytest.mark.parametrize(
    ("name", "pattern", "target", "is_vo2"),
    [
        # The session the app refused. 6 x 12s work, 168s recovery — 1:14.
        ("neuromuscular sprints", "6 x 12s / 168s @55%", "185%", False),
        # The shortest genuine VO2 format he rides. 1:1.
        ("Ronnestad 30/30", "10 x 30s / 30s @55%", "130%", True),
        ("40/20 microbursts", "10 x 40s / 20s @55%", "125%", True),
        ("VO2 2 min", "5 x 2min / 2min @60%", "120%", True),
        ("VO2 3 min", "7 x 3min / 3min @60%", "119%", True),
        # Below the intensity floor entirely — unchanged by this batch.
        ("primer", "2 x 30s / 30s @55%", "100%", False),
    ],
)
def test_every_real_prescription_classifies_correctly(
    name: str, pattern: str, target: str, is_vo2: bool
) -> None:
    assert ir_has_vo2(_ir(pattern, target)) is is_vo2, name


def test_the_22_sep_session_is_deliverable_on_a_red_day() -> None:
    """The failure this batch exists to remove, stated as one assertion."""
    assert blocks_red_vo2("Red", _ir("6 x 12s / 168s @55%", "185%")) is False


def test_a_short_effort_with_short_recovery_is_still_vo2() -> None:
    """The safe direction. 15s/15s is a VO2 stimulus however short each rep is.

    Without this, exempting "short" work would open a route for genuine
    high-intensity intervals onto a Red day — the half of Decision #301's intent
    that survives Batch 277.
    """
    assert ir_has_vo2(_ir("10 x 15s / 15s @55%", "150%")) is True
    assert blocks_red_vo2("Red", _ir("10 x 15s / 15s @55%", "150%")) is True


def test_the_boundary_sits_between_his_sprints_and_his_shortest_vo2() -> None:
    """12 s is a sprint, 30 s is VO2, and the boundary has margin on both sides."""
    assert 12 < ALACTIC_MAX_WORK_SEC < 30
    long_enough = ALACTIC_MIN_RECOVERY_RATIO * ALACTIC_MAX_WORK_SEC
    assert 168 >= long_enough  # his real recovery clears it
    assert 30 < long_enough  # a 30 s recovery does not


def test_an_unknown_duration_is_never_exempt() -> None:
    """Doubt resolves toward blocking."""
    ir = {"steps": [{"label": "x", "powerStartPct": 185, "powerEndPct": 185}]}
    assert ir_has_vo2(ir) is True


def test_a_trailing_hard_step_with_no_following_step_is_never_exempt() -> None:
    ir = {"steps": [{"label": "x", "durationSec": 12, "powerStartPct": 185, "powerEndPct": 185}]}
    assert ir_has_vo2(ir) is True


def test_two_hard_efforts_back_to_back_are_not_sprints() -> None:
    """A "recovery" step that is itself above the floor does not exempt anything."""
    ir = {
        "steps": [
            {"label": "a", "durationSec": 12, "powerStartPct": 185, "powerEndPct": 185},
            {"label": "b", "durationSec": 120, "powerStartPct": HIT_FLOOR_PCT, "powerEndPct": 120},
        ]
    }
    assert ir_has_vo2(ir) is True
