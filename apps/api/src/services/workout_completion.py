from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import Analysis, PlannedWorkout
from src.services.workout_categories import category_for_workout_type

WORKOUT_STATUS_COMPLETED = "completed"


async def complete_matched_planned_workout(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    subject_date: date,
    category: str,
    activity_id: uuid.UUID,
) -> uuid.UUID | None:
    """Flip the planned workout an activity completed to ``completed`` and return
    its id (Batch 60), or ``None`` when the day holds no matching planned session
    (e.g. an unplanned ride).

    The match is by local date + workout category. When a day holds more than one
    session of the category (two rides, say), a candidate already claimed by a
    *different* activity's analysis is skipped, so the two activities spread
    across the two planned rows rather than both landing on the first. The flip is
    left uncommitted for the caller to persist in its own transaction, and is
    idempotent: re-running for the same activity re-selects the same row.
    """
    candidates = (
        (
            await session.execute(
                select(PlannedWorkout)
                .where(
                    PlannedWorkout.user_id == user_id,
                    PlannedWorkout.workout_date == subject_date,
                    PlannedWorkout.is_active.is_(True),
                )
                .order_by(PlannedWorkout.version.desc(), PlannedWorkout.id)
            )
        )
        .scalars()
        .all()
    )
    matches = [
        workout
        for workout in candidates
        if category_for_workout_type(workout.workout_type) == category
    ]
    if not matches:
        return None

    claimed = {
        row
        for row in (
            (
                await session.execute(
                    select(Analysis.planned_workout_id).where(
                        Analysis.planned_workout_id.in_([workout.id for workout in matches]),
                        Analysis.activity_id.is_not(None),
                        Analysis.activity_id != activity_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        if row is not None
    }
    chosen = next((workout for workout in matches if workout.id not in claimed), matches[0])
    chosen.status = WORKOUT_STATUS_COMPLETED
    return chosen.id
