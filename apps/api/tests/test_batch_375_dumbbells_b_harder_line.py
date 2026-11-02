"""Batch 375 — Dumbbells B's "harder version" line names upper-body moves.

On 2 Nov 2026, after Batch 368's dose rewrite, Plan No. 3's Sat 5 Dec "Dumbbells B (upper
body)" read "the harder version of each move you can (rear foot raised on the lunge, one leg
on the deadlift)": B has no lunge or deadlift. The line came from the week's dose, which
served A and B alike, so the next plan would have repeated it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.services.next_plan import (
    HARDER_VERSIONS,
    HARDER_VERSIONS_B,
    WEEKS,
    strength,
)
from src.services.plan_changes import ADD_STRENGTH_A, ADD_STRENGTH_B, _added_session

REPO = Path(__file__).resolve().parents[3]
DRAFT = REPO / "docs" / "drafts" / "2026-11-02-batch-375-wording.md"

#: Moves only one session has. A's dose text must not name B's, nor B's A's.
A_ONLY = ("squat", "deadlift", "lunge", "calf", "side plank", "hop")
B_ONLY = ("press", "pullover", "curl", "triceps", "step-up", "dead bug")


def _words(session: str, week_index: int) -> tuple[str, str]:
    built = strength(WEEKS[week_index].strength, session=session).structured_workout
    return built["steps"][0]["target"], built["summary"]


def _dose_text(session: str, week_index: int) -> str:
    target, _summary = _words(session, week_index)
    return target.lower()


@pytest.mark.parametrize("week_index", range(len(WEEKS)))
def test_no_weeks_dose_line_names_the_other_sessions_moves(week_index: int) -> None:
    b_line = _dose_text("B", week_index)
    a_line = _dose_text("A", week_index)
    assert not [move for move in A_ONLY if re.search(rf"\b{move}", b_line)], b_line
    assert not [move for move in B_ONLY if re.search(rf"\b{move}", a_line)], a_line


def test_week_7_gives_each_session_its_own_harder_version() -> None:
    week7 = 6
    a_target, a_summary = _words("A", week7)
    b_target, b_summary = _words("B", week7)
    assert a_target == f"3 × 8, {HARDER_VERSIONS}; 2 reps in reserve"
    assert b_target == f"3 × 8, {HARDER_VERSIONS_B}; 2 reps in reserve"
    assert HARDER_VERSIONS_B in b_summary and "rear foot" not in b_summary
    assert HARDER_VERSIONS in a_summary


def test_only_week_7_has_a_line_of_bs_own() -> None:
    differing = [
        index for index in range(len(WEEKS)) if _dose_text("A", index) != _dose_text("B", index)
    ]
    assert differing == [6]


def test_a_b_session_added_in_week_7_takes_bs_line() -> None:
    added_b = _added_session(ADD_STRENGTH_B, 25, 7).structured_workout
    added_a = _added_session(ADD_STRENGTH_A, 25, 7).structured_workout
    assert HARDER_VERSIONS_B in added_b["steps"][0]["target"]
    assert HARDER_VERSIONS in added_a["steps"][0]["target"]
    assert added_b["steps"][0]["minutes"] == 25


def test_bs_line_is_in_the_draft() -> None:
    draft = " ".join(DRAFT.read_text(encoding="utf-8").replace("\n> ", " ").split())
    assert f"{HARDER_VERSIONS_B}; 2 reps in reserve" in draft
