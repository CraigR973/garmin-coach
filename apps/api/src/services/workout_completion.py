from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import (
    Activity,
    Analysis,
    PlannedWorkout,
    PostActivityGenerationStatus,
)
from src.services.workout_categories import category_for_workout_type
from src.services.workout_match import material_difference

WORKOUT_STATUS_COMPLETED = "completed"


@dataclass(frozen=True)
class PlannedWorkoutMatch:
    """What an arriving activity did to the day's plan.

    ``planned_workout_id`` is the row the activity *completed*, and is ``None`` both
    when the day held no session of the category and when the one it held turned out
    to be a different session (Batch 278). The read this activity produces is a read
    of what was ridden, so linking it to a planned session it did not do would let
    every surface that asks "has this session got a read?" answer yes.
    """

    planned_workout_id: uuid.UUID | None
    deviation: dict[str, Any] | None = None

    @property
    def completed(self) -> bool:
        return self.planned_workout_id is not None


async def complete_matched_planned_workout(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    subject_date: date,
    category: str,
    activity: Activity,
    ftp_watts: int | None = None,
) -> PlannedWorkoutMatch:
    """Flip the planned workout an activity completed to ``completed`` (Batch 60),
    or record why it did not.

    The candidate is chosen by local date + workout category. When a day holds more
    than one session of the category (two rides, say), a candidate already claimed by
    a *different* activity's analysis is skipped, so the two activities spread across
    the two planned rows rather than both landing on the first.

    **Batch 278:** the chosen candidate is then read against the activity, and a row
    that describes a materially different session is left alone. Before this the
    match tested date and category and nothing else, so whatever bike row sat on the
    date was flipped by whatever bike activity arrived — which is how Mark's Zone-2
    ride came to be recorded as the VO2 he had not done. ``material_difference``
    holds the two rules and the evidence behind them.

    The flip is left uncommitted for the caller to persist in its own transaction, and
    is idempotent: re-running for the same activity re-selects the same row and
    re-reaches the same verdict. It does not *un*-flip a row an earlier run completed
    — this batch stops the wrong record being written, and correcting one already
    written stays a deliberate act.
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
        return PlannedWorkoutMatch(planned_workout_id=None)

    claimed_by_analysis = {
        row
        for row in (
            (
                await session.execute(
                    select(Analysis.planned_workout_id).where(
                        Analysis.planned_workout_id.in_([workout.id for workout in matches]),
                        Analysis.activity_id.is_not(None),
                        Analysis.activity_id != activity.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        if row is not None
    }
    claimed_by_status = {
        row
        for row in (
            (
                await session.execute(
                    select(PostActivityGenerationStatus.planned_workout_id).where(
                        PostActivityGenerationStatus.planned_workout_id.in_(
                            [workout.id for workout in matches]
                        ),
                        PostActivityGenerationStatus.activity_id != activity.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        if row is not None
    }
    claimed = claimed_by_analysis | claimed_by_status
    chosen = next((workout for workout in matches if workout.id not in claimed), matches[0])

    deviation = material_difference(
        chosen,
        activity,
        category=category,
        ftp_watts=ftp_watts,
    )
    if deviation is not None:
        return PlannedWorkoutMatch(
            planned_workout_id=None,
            deviation={"plannedWorkoutId": str(chosen.id), **deviation},
        )

    chosen.status = WORKOUT_STATUS_COMPLETED
    return PlannedWorkoutMatch(planned_workout_id=chosen.id)
