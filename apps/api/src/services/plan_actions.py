from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import ManualEntry, PlannedWorkout
from src.models.profile import Profile
from src.services.executable_coaching import WORKOUT_STATUS_SKIPPED, ExecutableCoachingService
from src.services.workout_categories import (
    DAY_CATEGORY_CYCLE,
    DAY_CATEGORY_FLEXIBILITY,
    DAY_CATEGORY_WEIGHTS,
    DayState,
    day_state_for_workout_types,
)
from src.services.workout_delivery import IntervalsEventClient


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@dataclass(frozen=True)
class PlanDay:
    date: date
    day_state: DayState
    workouts: list[PlannedWorkout]


@dataclass(frozen=True)
class PlanSchedule:
    start_date: date
    days: list[PlanDay]


def default_workout_for_category(category: str) -> dict[str, Any]:
    if category == DAY_CATEGORY_CYCLE:
        return {
            "title": "Endurance ride",
            "workout_type": "bike_endurance",
            "planned_duration_min": 45,
            "intensity_target": "Zone 2",
            "structured_workout": {
                "format": "bike",
                "steps": [
                    {"label": "Warm-up", "minutes": 10, "target": "easy"},
                    {"label": "Endurance", "minutes": 30, "target": "zone 2"},
                    {"label": "Cool-down", "minutes": 5, "target": "easy"},
                ],
            },
        }
    if category == DAY_CATEGORY_WEIGHTS:
        return {
            "title": "Strength maintenance",
            "workout_type": "strength_maintenance",
            "planned_duration_min": 20,
            "intensity_target": "maintenance",
            "structured_workout": {"format": "strength", "focus": "maintenance"},
        }
    if category == DAY_CATEGORY_FLEXIBILITY:
        return {
            "title": "Flexibility",
            "workout_type": "mobility",
            "planned_duration_min": 16,
            "intensity_target": "easy",
            "structured_workout": {"format": "mobility"},
        }
    raise HTTPException(status_code=422, detail="Unknown workout category")


class PlanActionService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        intervals_client: IntervalsEventClient | None = None,
    ) -> None:
        self.session = session
        self.executable = ExecutableCoachingService(session, intervals_client=intervals_client)

    async def schedule(self, player: Profile, *, start_date: date, days: int) -> PlanSchedule:
        end_date = start_date + timedelta(days=max(days, 1) - 1)
        rows = (
            (
                await self.session.execute(
                    select(PlannedWorkout)
                    .where(
                        PlannedWorkout.user_id == player.id,
                        PlannedWorkout.workout_date >= start_date,
                        PlannedWorkout.workout_date <= end_date,
                        PlannedWorkout.is_active.is_(True),
                        PlannedWorkout.status != WORKOUT_STATUS_SKIPPED,
                    )
                    .order_by(PlannedWorkout.workout_date.asc(), PlannedWorkout.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
        by_date: dict[date, list[PlannedWorkout]] = {}
        for workout in rows:
            by_date.setdefault(workout.workout_date, []).append(workout)

        plan_days: list[PlanDay] = []
        for offset in range(max(days, 1)):
            current = start_date + timedelta(days=offset)
            workouts = by_date.get(current, [])
            plan_days.append(
                PlanDay(
                    date=current,
                    day_state=day_state_for_workout_types([w.workout_type for w in workouts]),
                    workouts=workouts,
                )
            )
        return PlanSchedule(start_date=start_date, days=plan_days)

    async def add_workout(
        self, player: Profile, *, workout_date: date, category: str
    ) -> PlannedWorkout:
        template = default_workout_for_category(category)
        version = await self._next_version(player.id, workout_date)
        workout = PlannedWorkout(
            user_id=player.id,
            plan_block_id=None,
            workout_date=workout_date,
            version=version,
            title=template["title"],
            workout_type=template["workout_type"],
            status="planned",
            is_active=True,
            planned_duration_min=template["planned_duration_min"],
            intensity_target=template["intensity_target"],
            structured_workout=template["structured_workout"],
            source="plan_action_add",
        )
        self.session.add(workout)
        await self.session.flush()
        if category == DAY_CATEGORY_CYCLE:
            await self.executable.reconcile_deliveries(
                player, start_date=workout_date, end_date=workout_date
            )
        await self.session.commit()
        await self.session.refresh(workout)
        return workout

    async def swap_workout_into_date(
        self, player: Profile, *, planned_workout_id: uuid.UUID, target_date: date
    ) -> PlannedWorkout:
        return await self.executable.swap_day(
            player, planned_workout_id=planned_workout_id, target_date=target_date
        )

    async def skip_day(self, player: Profile, *, workout_date: date) -> list[PlannedWorkout]:
        workouts = await self._active_workouts_on(player.id, workout_date)
        skipped: list[PlannedWorkout] = []
        for workout in workouts:
            skipped.append(
                await self.executable.skip_workout(player, planned_workout_id=workout.id)
            )
        return skipped

    async def record_actual(
        self,
        player: Profile,
        *,
        workout_date: date,
        label: str,
        notes: str | None,
    ) -> ManualEntry:
        entry = ManualEntry(
            user_id=player.id,
            entry_date=workout_date,
            entry_at_utc=_utcnow(),
            adherence_status="modified",
            actual_workout_json={"label": label, "source": "did_something_else"},
            notes=notes,
        )
        self.session.add(entry)
        await self.session.commit()
        await self.session.refresh(entry)
        return entry

    async def _next_version(self, user_id: uuid.UUID, workout_date: date) -> int:
        current = await self.session.scalar(
            select(func.max(PlannedWorkout.version)).where(
                PlannedWorkout.user_id == user_id,
                PlannedWorkout.workout_date == workout_date,
            )
        )
        return (current or 0) + 1

    async def _active_workouts_on(
        self, user_id: uuid.UUID, workout_date: date
    ) -> list[PlannedWorkout]:
        return list(
            (
                await self.session.execute(
                    select(PlannedWorkout)
                    .where(
                        PlannedWorkout.user_id == user_id,
                        PlannedWorkout.workout_date == workout_date,
                        PlannedWorkout.is_active.is_(True),
                        PlannedWorkout.status != WORKOUT_STATUS_SKIPPED,
                    )
                    .order_by(PlannedWorkout.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
