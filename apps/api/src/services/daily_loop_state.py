"""Batch 48 — the explicit daily/block loop-state model.

A pure, DB-free model of *where Mark is in his day and training block, and what
the next thing to surface/push is*. Until now "the loop" was implicit — spread
across scheduler jobs, ``homeSections``, and the per-service state each of
Batches 45-47 re-derived. This module makes it a first-class object.

Two generalisations over the cycling-shaped frontend ``useDailyPhase``
(``pre_ride | post_ride | rest_day``):

* ``post_ride`` becomes **``post_training``** and fires off *any* post-session
  read (ride / strength / flexibility / walk), so a strength-only day advances
  instead of being stuck ``pre_ride``.
* A first-class evening **``wind_down``** phase replaces the 20:00 clock reorder.

The block advances build → recovery → taper → consolidation, and the end of a
13-week block (``consolidation``) is an explicit boundary — the seam Batch 47's
"plan your next block" prompt reads.

Consolidating refactor (DECISIONS #118): **behaviour-preserving, no new coaching
logic, no migration.** The frontend ``useDailyPhase`` mirrors these rules;
Batches 45-47 keep their existing wiring and can adopt ``describe_loop_state``
opportunistically.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from typing import Literal

DayPhase = Literal["rest_day", "pre_training", "post_training", "wind_down"]
BlockPhase = Literal["build", "recovery", "taper", "consolidation", "transition"]
NextAction = Literal["await_training", "review_session", "wind_down", "rest"]

# Mirror of ``homeSections.EVENING_HOUR`` — the local hour at/after which the day
# has tipped into its wind-down phase. Kept in lockstep with the frontend.
EVENING_HOUR = 20


def is_evening(now_local: time | datetime) -> bool:
    """True at/after :data:`EVENING_HOUR` in the user's local time."""

    return now_local.hour >= EVENING_HOUR


def derive_day_phase(
    *,
    has_post_analysis: bool,
    has_planned_workout: bool,
    is_evening: bool,
) -> DayPhase:
    """Where Mark is in his day.

    Precedence: the evening ``wind_down`` (sleep prep is the evening's focus,
    Batch 46) wins; then a completed session's read (``post_training``, any
    modality); then a rest day (nothing planned); else ``pre_training`` (planned
    work not yet done).
    """

    if is_evening:
        return "wind_down"
    if has_post_analysis:
        return "post_training"
    if not has_planned_workout:
        return "rest_day"
    return "pre_training"


def derive_block_phase(*, block_type: str | None, block_name: str | None) -> BlockPhase | None:
    """Classify the active plan block into the 2121 block vocabulary.

    Reads the block's ``block_type`` and human name (e.g. "Week 13
    Consolidation") — the app stores either, so we match on both. Unknown /
    absent blocks return ``None`` rather than guessing.
    """

    text = f"{block_type or ''} {block_name or ''}".lower()
    if not text.strip():
        return None
    if "consolidat" in text:
        return "consolidation"
    if "taper" in text:
        return "taper"
    if "recovery" in text or "rest week" in text or "deload" in text:
        return "recovery"
    if "transition" in text or "off-season" in text or "off season" in text:
        return "transition"
    if "build" in text or "base" in text or "progression" in text:
        return "build"
    return None


def is_block_boundary(block_phase: BlockPhase | None) -> bool:
    """True when the block is at its end — consolidation (wk13) closes a 13-week
    block, so it's time to program the next one (the Batch 47 trigger)."""

    return block_phase == "consolidation"


def next_action(day_phase: DayPhase) -> NextAction:
    """The single day-level "next thing" the orchestration seam surfaces."""

    mapping: dict[DayPhase, NextAction] = {
        "wind_down": "wind_down",
        "post_training": "review_session",
        "rest_day": "rest",
        "pre_training": "await_training",
    }
    return mapping[day_phase]


@dataclass(frozen=True)
class LoopState:
    """The answer to "where is Mark in his day/block, and what is next"."""

    day_phase: DayPhase
    block_phase: BlockPhase | None
    next_action: NextAction
    at_block_boundary: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "dayPhase": self.day_phase,
            "blockPhase": self.block_phase,
            "nextAction": self.next_action,
            "atBlockBoundary": self.at_block_boundary,
        }


def describe_loop_state(
    *,
    has_post_analysis: bool,
    has_planned_workout: bool,
    is_evening: bool,
    block_type: str | None = None,
    block_name: str | None = None,
) -> LoopState:
    """The orchestration seam — pure derivation of the whole loop state from
    already-assembled facts. Batches 45-47 can consume this instead of each
    re-deriving where Mark is."""

    day_phase = derive_day_phase(
        has_post_analysis=has_post_analysis,
        has_planned_workout=has_planned_workout,
        is_evening=is_evening,
    )
    block_phase = derive_block_phase(block_type=block_type, block_name=block_name)
    return LoopState(
        day_phase=day_phase,
        block_phase=block_phase,
        next_action=next_action(day_phase),
        at_block_boundary=is_block_boundary(block_phase),
    )
