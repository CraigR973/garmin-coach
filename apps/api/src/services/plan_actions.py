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


@dataclass(frozen=True)
class QuickAddOption:
    subtype: str
    label: str
    title: str
    workout_type: str
    intensity_target: str
    default_duration_min: int
    min_duration_min: int
    max_duration_min: int
    warmup_min: int
    cooldown_min: int
    main_target: str
    structured_format: str
    structured_focus: str | None = None


QUICK_ADD_CATALOG: dict[str, list[QuickAddOption]] = {
    DAY_CATEGORY_CYCLE: [
        QuickAddOption(
            subtype="endurance",
            label="Endurance",
            title="Endurance ride",
            workout_type="bike_endurance",
            intensity_target="Zone 2",
            default_duration_min=45,
            min_duration_min=20,
            max_duration_min=90,
            warmup_min=10,
            cooldown_min=5,
            main_target="zone 2",
            structured_format="bike",
        ),
        QuickAddOption(
            subtype="sweet_spot",
            label="Sweet Spot",
            title="Sweet Spot ride",
            workout_type="bike_sweet_spot",
            intensity_target="Sweet Spot ~89% FTP",
            default_duration_min=40,
            min_duration_min=25,
            max_duration_min=75,
            warmup_min=10,
            cooldown_min=5,
            main_target="89%",
            structured_format="bike",
        ),
        QuickAddOption(
            subtype="recovery",
            label="Recovery spin",
            title="Recovery spin",
            workout_type="bike_recovery",
            intensity_target="Recovery ~55% FTP",
            default_duration_min=30,
            min_duration_min=15,
            max_duration_min=45,
            warmup_min=5,
            cooldown_min=5,
            main_target="55%",
            structured_format="bike",
        ),
    ],
    DAY_CATEGORY_WEIGHTS: [
        QuickAddOption(
            subtype="maintenance",
            label="Strength maintenance",
            title="Strength maintenance",
            workout_type="strength_maintenance",
            intensity_target="maintenance",
            default_duration_min=20,
            min_duration_min=10,
            max_duration_min=40,
            warmup_min=0,
            cooldown_min=0,
            main_target="maintenance",
            structured_format="strength",
            structured_focus="maintenance",
        ),
        QuickAddOption(
            subtype="recovery",
            label="Strength recovery",
            title="Strength recovery",
            workout_type="strength_recovery",
            intensity_target="recovery",
            default_duration_min=15,
            min_duration_min=10,
            max_duration_min=30,
            warmup_min=0,
            cooldown_min=0,
            main_target="recovery",
            structured_format="strength",
            structured_focus="recovery",
        ),
    ],
    DAY_CATEGORY_FLEXIBILITY: [
        QuickAddOption(
            subtype="mobility",
            label="Flexibility",
            title="Flexibility",
            workout_type="mobility",
            intensity_target="easy",
            default_duration_min=16,
            min_duration_min=10,
            max_duration_min=30,
            warmup_min=0,
            cooldown_min=0,
            main_target="easy",
            structured_format="mobility",
        ),
    ],
}


def quick_add_options(category: str) -> list[QuickAddOption]:
    options = QUICK_ADD_CATALOG.get(category)
    if options is None:
        raise HTTPException(status_code=422, detail="Unknown workout category")
    return options


def _quick_add_option(category: str, subtype: str) -> QuickAddOption:
    for option in quick_add_options(category):
        if option.subtype == subtype:
            return option
    raise HTTPException(status_code=422, detail="Unknown workout subtype for category")


def workout_for_selection(
    category: str, *, subtype: str | None, duration_min: int | None
) -> dict[str, Any]:
    options = quick_add_options(category)
    option = _quick_add_option(category, subtype) if subtype else options[0]
    duration = duration_min if duration_min is not None else option.default_duration_min
    if duration < option.min_duration_min or duration > option.max_duration_min:
        raise HTTPException(
            status_code=422,
            detail=(
                f"durationMin for '{option.subtype}' must be between "
                f"{option.min_duration_min} and {option.max_duration_min}"
            ),
        )

    if option.structured_format == "bike":
        main_min = duration - option.warmup_min - option.cooldown_min
        structured_workout: dict[str, Any] = {
            "format": "bike",
            "steps": [
                {"label": "Warm-up", "minutes": option.warmup_min, "target": "easy"},
                {"label": option.label, "minutes": main_min, "target": option.main_target},
                {"label": "Cool-down", "minutes": option.cooldown_min, "target": "easy"},
            ],
        }
    elif option.structured_format == "strength":
        structured_workout = {"format": "strength", "focus": option.structured_focus}
    else:
        structured_workout = {"format": option.structured_format}

    return {
        "title": option.title,
        "workout_type": option.workout_type,
        "planned_duration_min": duration,
        "intensity_target": option.intensity_target,
        "structured_workout": structured_workout,
    }


def default_workout_for_category(category: str) -> dict[str, Any]:
    return workout_for_selection(category, subtype=None, duration_min=None)


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
        self,
        player: Profile,
        *,
        workout_date: date,
        category: str,
        subtype: str | None = None,
        duration_min: int | None = None,
    ) -> PlannedWorkout:
        template = workout_for_selection(category, subtype=subtype, duration_min=duration_min)
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
