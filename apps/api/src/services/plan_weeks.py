"""Which week of his plan a date fell in, by the plan's own name and type (Batch 380).

Batch 379's review of the live coach found it misnaming the training phase of part of
a period it was asked about. Nothing it held named a week of the plan: the week ahead
carries sessions, the knowledge base carries the plan's general rhythm, and the
generated block section is hidden from the model. With the record silent, it named
the phase from what a week usually holds.

Each ``PlanBlock`` row is one dated week of the plan (``PN3 W02 BUILD``, type
``build``). This module is the one reader of those rows for the coach: the live
block's ``planWeeks`` and each ``get_planned_workouts`` row's ``planWeek`` come from
here, and the proactive week packet (:mod:`week_ahead`) uses the same lookup, so the
coach and the weekly review never name the same week differently.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import PlanBlock


async def latest_plan_blocks(
    session: AsyncSession,
    user_id: uuid.UUID,
    start: date,
    end: date,
) -> list[PlanBlock]:
    """The plan weeks overlapping ``start``..``end``, oldest first, latest version only.

    A re-imported week keeps its name and dates and gains a version, so the newest
    version of each (name, start, end) stands for it.
    """
    rows = (
        (
            await session.execute(
                select(PlanBlock)
                .where(
                    PlanBlock.user_id == user_id,
                    PlanBlock.start_date <= end,
                    PlanBlock.end_date >= start,
                )
                .order_by(
                    PlanBlock.start_date.asc(),
                    PlanBlock.version.desc(),
                    PlanBlock.name.asc(),
                )
            )
        )
        .scalars()
        .all()
    )
    latest: dict[tuple[str, date, date], PlanBlock] = {}
    for row in rows:
        key = (row.name, row.start_date, row.end_date)
        if key not in latest:
            latest[key] = row
    return list(latest.values())


def plan_week_row(block: PlanBlock) -> list[Any]:
    """One plan week as a row of the live block's ``planWeeks``: dates, name and type.

    The order is ``chat_context.PLAN_WEEK_COLUMNS``; a row rather than an object
    because the live block is full (see there).
    """
    return [
        block.start_date.isoformat(),
        block.end_date.isoformat(),
        block.name,
        block.block_type,
    ]


def plan_week_on(blocks: Sequence[PlanBlock], day: date) -> dict[str, Any] | None:
    """The plan week ``day`` falls in, or ``None`` when no week of the plan covers it.

    Weeks do not overlap in a loaded plan; if two ever do, the later-starting one is
    the plan that was loaded over the earlier one, so it names the day.
    """
    covering = [block for block in blocks if block.start_date <= day <= block.end_date]
    if not covering:
        return None
    block = max(covering, key=lambda row: (row.start_date, row.version))
    return {"name": block.name, "weekType": block.block_type}


__all__ = ["latest_plan_blocks", "plan_week_on", "plan_week_row"]
