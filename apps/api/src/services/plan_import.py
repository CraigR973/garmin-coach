"""Import a reviewed training-plan JSON as the owned plan (`plan_blocks` +
`planned_workouts`).

Context (DECISIONS #102): Mark's real 13-week plan was never loaded — at first-run
the Batch 5 seed created a *generic* 2121 slate anchored to the setup week, leaving
the app ~10 weeks out of sync with his actual progression and with placeholder
content. This importer loads a hand-reviewed plan definition (see
``apps/api/data/plans/``) as the real owned plan.

The plan JSON shape is::

    {
      "name": "...", "source": "plan_no2_import", "start_date": "2026-07-06",
      "weeks": [
        {"week": 1, "label": "BUILD WEEK", "block_type": "build",
         "days": [
           {"dow": 0, "rest": false, "title": "...", "workout_type": "bike_vo2",
            "duration_min": 60, "intensity_target": "...", "structured_workout": {...}},
           {"dow": 4, "rest": true, "title": "Rest"}
         ]}
      ]
    }

``build_plan_rows`` is pure (no DB) and unit-tested; ``import_plan`` applies the
rows, replacing the forward schedule from the plan's Monday start while leaving any
earlier (already-in-progress) week untouched. Idempotent: a re-run first clears its
own prior import (matched by ``source`` and the block-name prefix).
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import PlanBlock, PlannedWorkout

DEFAULT_BLOCK_PREFIX = "PN2"
DEFAULT_SOURCE = "plan_import"


@dataclass(frozen=True)
class BlockRow:
    name: str
    sequence_index: int
    block_type: str
    start_date: dt.date
    end_date: dt.date
    label: str


@dataclass(frozen=True)
class WorkoutRow:
    week: int
    workout_date: dt.date
    title: str
    workout_type: str
    planned_duration_min: int | None
    intensity_target: str
    structured_workout: dict[str, Any]


@dataclass(frozen=True)
class PlanRows:
    start_date: dt.date
    source: str
    block_prefix: str
    blocks: list[BlockRow] = field(default_factory=list)
    workouts: list[WorkoutRow] = field(default_factory=list)


@dataclass(frozen=True)
class ImportSummary:
    dry_run: bool
    start_date: dt.date
    blocks_inserted: int
    workouts_inserted: int
    forward_workouts_removed: int
    forward_blocks_removed: int
    prior_import_workouts_removed: int
    prior_import_blocks_removed: int


def build_plan_rows(
    plan: dict[str, Any],
    start_date: dt.date | None = None,
    *,
    block_prefix: str = DEFAULT_BLOCK_PREFIX,
) -> PlanRows:
    """Map a reviewed plan dict to concrete block + workout rows (pure, DB-free).

    ``start_date`` overrides the plan's declared start; either way it must be a
    Monday, because weeks are anchored on Monday and day offsets (``dow`` 0=Mon)
    hang off the week start.
    """
    start = start_date or dt.date.fromisoformat(str(plan["start_date"]))
    if start.weekday() != 0:
        raise ValueError(f"start_date {start.isoformat()} must be a Monday")

    source = str(plan.get("source", DEFAULT_SOURCE))
    blocks: list[BlockRow] = []
    workouts: list[WorkoutRow] = []
    for wk in plan["weeks"]:
        week_no = int(wk["week"])
        block_start = start + dt.timedelta(days=7 * (week_no - 1))
        label = str(wk["label"])
        blocks.append(
            BlockRow(
                name=f"{block_prefix} W{week_no:02d} {label}"[:160],
                sequence_index=week_no,
                block_type=str(wk["block_type"]),
                start_date=block_start,
                end_date=block_start + dt.timedelta(days=6),
                label=label,
            )
        )
        for day in wk["days"]:
            if day.get("rest"):
                continue
            duration = day.get("duration_min")
            workouts.append(
                WorkoutRow(
                    week=week_no,
                    workout_date=block_start + dt.timedelta(days=int(day["dow"])),
                    title=str(day["title"])[:200],
                    workout_type=str(day["workout_type"]),
                    planned_duration_min=int(duration) if duration is not None else None,
                    intensity_target=str(day.get("intensity_target", ""))[:120],
                    structured_workout=dict(day.get("structured_workout", {})),
                )
            )
    return PlanRows(
        start_date=start,
        source=source,
        block_prefix=block_prefix,
        blocks=blocks,
        workouts=workouts,
    )


async def import_plan(
    session: AsyncSession,
    user_id: uuid.UUID,
    plan: dict[str, Any],
    *,
    start_date: dt.date | None = None,
    block_prefix: str = DEFAULT_BLOCK_PREFIX,
    dry_run: bool = True,
) -> ImportSummary:
    """Load ``plan`` as the owned plan for ``user_id``.

    Replaces the forward schedule from the plan's Monday start (earlier weeks are
    left intact) and is idempotent for its own prior import. Commits when
    ``dry_run`` is False, otherwise rolls back so callers can preview the counts.
    """
    rows = build_plan_rows(plan, start_date, block_prefix=block_prefix)
    start = rows.start_date

    async def _delete(sql: str, params: dict[str, Any]) -> int:
        result = await session.execute(text(sql), params)
        # DML CursorResult carries rowcount; the base Result type does not expose it.
        return int(getattr(result, "rowcount", 0) or 0)

    prior_workouts = await _delete(
        "DELETE FROM planned_workouts WHERE user_id = :u AND source = :s",
        {"u": user_id, "s": rows.source},
    )
    prior_blocks = await _delete(
        "DELETE FROM plan_blocks WHERE user_id = :u AND name LIKE :p",
        {"u": user_id, "p": f"{block_prefix} %"},
    )
    forward_workouts = await _delete(
        "DELETE FROM planned_workouts WHERE user_id = :u AND workout_date >= :d",
        {"u": user_id, "d": start},
    )
    forward_blocks = await _delete(
        "DELETE FROM plan_blocks WHERE user_id = :u AND start_date >= :d AND name NOT LIKE :p",
        {"u": user_id, "d": start, "p": f"{block_prefix} %"},
    )

    block_ids: dict[int, uuid.UUID] = {}
    for block in rows.blocks:
        obj = PlanBlock(
            user_id=user_id,
            name=block.name,
            version=1,
            sequence_index=block.sequence_index,
            block_type=block.block_type,
            start_date=block.start_date,
            end_date=block.end_date,
            goals_json={"label": block.label},
            raw_plan={},
        )
        session.add(obj)
        await session.flush()
        block_ids[block.sequence_index] = obj.id
    for workout in rows.workouts:
        session.add(
            PlannedWorkout(
                user_id=user_id,
                plan_block_id=block_ids.get(workout.week),
                workout_date=workout.workout_date,
                version=1,
                title=workout.title,
                workout_type=workout.workout_type,
                status="planned",
                is_active=True,
                planned_duration_min=workout.planned_duration_min,
                intensity_target=workout.intensity_target,
                structured_workout=workout.structured_workout,
                source=rows.source,
            )
        )
    await session.flush()

    summary = ImportSummary(
        dry_run=dry_run,
        start_date=start,
        blocks_inserted=len(rows.blocks),
        workouts_inserted=len(rows.workouts),
        forward_workouts_removed=forward_workouts,
        forward_blocks_removed=forward_blocks,
        prior_import_workouts_removed=prior_workouts,
        prior_import_blocks_removed=prior_blocks,
    )
    if dry_run:
        await session.rollback()
    else:
        await session.commit()
    return summary
