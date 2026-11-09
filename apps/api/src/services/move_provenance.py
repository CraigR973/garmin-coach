"""Who moved a planned session, and why (Batch 381).

Until Batch 381 every move through ``swap_day`` was stamped ``today_card_swap``,
including the ten Dumbbells A rows Craig moved to Thursdays on 2 Nov 2026 by running
``swap_day`` inside the api container (Decision #462). The coach then told Mark his
record showed his own Today-card move with no reason logged (379's case #33).

Two existing fields carry the provenance, so no column or table is added:

* **Who** is the row's ``planned_workouts.source``: ``today_card_swap`` for Mark's own
  move from the app (the Today card, the Week page or the morning's swap suggestion,
  which all reach the same endpoint), ``operator_move`` for a move Craig makes or that
  is made on his decision. ``coach_policy.INTERNAL_SOURCE_BASIS`` turns either token
  into a sentence the coach may say.
* **Why** is the move's own audit row (an ``analyses`` row of type ``workout_moved``):
  its ``context_packet`` gains ``movedBy`` and, for a move Craig made, ``reason``, a
  short plain sentence. Mark's own moves record no reason, because the app does not ask
  him for one; the coach must not invent one.

A leaf: it imports models only, so the move path, the week packet and the coach's
lookup can all read it without a cycle.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import Analysis

#: Mark's own move from the app. The token predates Batch 381 and is kept, so every
#: move he has made keeps its label.
OWNER_MOVE_SOURCE = "today_card_swap"
#: A move Craig made, or one made on his decision, outside Mark's own taps.
OPERATOR_MOVE_SOURCE = "operator_move"

MOVED_BY_OWNER = "owner"
MOVED_BY_OPERATOR = "operator"

#: Keys on a ``workout_moved`` audit row's ``context_packet``.
MOVED_BY_KEY = "movedBy"
MOVE_REASON_KEY = "reason"
#: The other row of a swap, so its reason is found as well as the moved row's.
SWAPPED_WORKOUT_KEY = "swappedPlannedWorkoutId"

AUDIT_TYPE_MOVED = "workout_moved"

#: A reason is one short sentence the coach can quote on a phone.
MOVE_REASON_MAX_CHARS = 280


@dataclass(frozen=True)
class MoveProvenance:
    """Who is moving a session and, for Craig's moves, why."""

    moved_by: str
    reason: str | None = None

    @property
    def source(self) -> str:
        return OPERATOR_MOVE_SOURCE if self.moved_by == MOVED_BY_OPERATOR else OWNER_MOVE_SOURCE

    def audit_fields(self) -> dict[str, Any]:
        fields: dict[str, Any] = {MOVED_BY_KEY: self.moved_by}
        if self.reason is not None:
            fields[MOVE_REASON_KEY] = self.reason
        return fields


#: Every move Mark makes in the app.
OWNER_MOVE = MoveProvenance(moved_by=MOVED_BY_OWNER)


def operator_move(reason: str) -> MoveProvenance:
    """A move Craig makes. It must say why, in one short plain sentence."""
    text = " ".join((reason or "").split())
    if not text:
        raise ValueError("A move Craig makes must record a reason")
    if len(text) > MOVE_REASON_MAX_CHARS:
        raise ValueError(f"A move reason is at most {MOVE_REASON_MAX_CHARS} characters")
    return MoveProvenance(moved_by=MOVED_BY_OPERATOR, reason=text)


def _uuid(value: Any) -> uuid.UUID | None:
    if not isinstance(value, str):
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def move_reasons(audits: Iterable[Analysis]) -> dict[uuid.UUID, str]:
    """The recorded reason for each planned row a move produced, latest move winning.

    Rows Mark moved carry no reason and are absent. ``audits`` may hold any action
    audits; only moves with a reason count. Pure, so the week packet can use the
    audits it has already loaded.
    """
    ordered = sorted(
        (audit for audit in audits if audit.analysis_type == AUDIT_TYPE_MOVED),
        key=lambda audit: (audit.generated_at_utc, audit.created_at),
    )
    reasons: dict[uuid.UUID, str] = {}
    for audit in ordered:
        packet: Mapping[str, Any] = (
            audit.context_packet if isinstance(audit.context_packet, dict) else {}
        )
        reason = packet.get(MOVE_REASON_KEY)
        for key in ("plannedWorkoutId", SWAPPED_WORKOUT_KEY):
            row_id = _uuid(packet.get(key))
            if row_id is None:
                continue
            if isinstance(reason, str) and reason.strip():
                reasons[row_id] = reason.strip()
            else:
                # A later move without a reason (Mark's own) supersedes an earlier one.
                reasons.pop(row_id, None)
    return reasons


async def move_reasons_for(
    session: AsyncSession, user_id: uuid.UUID, workout_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, str]:
    """``move_reasons`` for the given rows, read from the database."""
    wanted = {str(row_id) for row_id in workout_ids}
    if not wanted:
        return {}
    audits = (
        (
            await session.execute(
                select(Analysis).where(
                    Analysis.user_id == user_id,
                    Analysis.analysis_type == AUDIT_TYPE_MOVED,
                    (
                        Analysis.context_packet["plannedWorkoutId"].astext.in_(wanted)
                        | Analysis.context_packet[SWAPPED_WORKOUT_KEY].astext.in_(wanted)
                    ),
                )
            )
        )
        .scalars()
        .all()
    )
    return {
        row_id: reason for row_id, reason in move_reasons(audits).items() if str(row_id) in wanted
    }
