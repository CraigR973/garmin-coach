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
from src.services.workout_completion import WORKOUT_STATUS_COMPLETED
from src.services.workout_delivery import IntervalsEventClient


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


DONE_ADHERENCE_STATUSES = {"completed", "modified", "done", "did_something_else"}


def _pattern_minutes(value: float) -> str:
    # Matches the plan JSON's authored pattern grammar, e.g. "2min" (Batch 67's
    # ``_expand_pattern`` parses "Nmin" / "Nmin / Mmin @X%" via ``_duration_sec``).
    return f"{value:g}min"


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
    # Batch 75: real ramp warm-up/cool-down (Batch 67 step grammar) instead of a
    # flat "easy" block. None on both ends preserves the pre-Batch-75 flat shape.
    warmup_ramp_pct: tuple[int, int] | None = None
    cooldown_ramp_pct: tuple[int, int] | None = None
    # Batch 75: authors the main block as an interval pattern (work/recovery
    # repeats) instead of one steady block, e.g. VO2 "with efforts". The chosen
    # duration's main portion is covered by the nearest whole rep count in
    # [min_reps, max_reps], so the delivered duration may differ slightly from
    # the requested one — the returned workout always reports the true total.
    interval_work_min: float | None = None
    interval_recovery_min: float | None = None
    interval_recovery_target: str | None = None
    min_reps: int | None = None
    max_reps: int | None = None


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
        QuickAddOption(
            subtype="tempo",
            label="Tempo / Threshold (Z3)",
            title="Tempo / Threshold ride",
            workout_type="bike_tempo",
            intensity_target="Tempo/Threshold ~84% FTP",
            default_duration_min=40,
            min_duration_min=25,
            max_duration_min=65,
            warmup_min=8,
            cooldown_min=5,
            main_target="84%",
            structured_format="bike",
            warmup_ramp_pct=(55, 80),
            cooldown_ramp_pct=(65, 40),
        ),
        QuickAddOption(
            subtype="vo2_efforts",
            label="VO2 (with efforts)",
            title="VO2 with efforts",
            workout_type="bike_vo2",
            intensity_target="VO2 ~118% FTP efforts",
            default_duration_min=38,
            min_duration_min=30,
            max_duration_min=50,
            warmup_min=10,
            cooldown_min=8,
            main_target="118%",
            structured_format="bike",
            warmup_ramp_pct=(55, 80),
            cooldown_ramp_pct=(65, 40),
            interval_work_min=2.0,
            interval_recovery_min=2.0,
            interval_recovery_target="60%",
            min_reps=3,
            max_reps=8,
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
        if option.warmup_ramp_pct is not None:
            warmup_start, warmup_end = option.warmup_ramp_pct
            warmup_step = {
                "label": "Warm-up ramp",
                "minutes": option.warmup_min,
                "ramp": [warmup_start, warmup_end],
            }
        else:
            warmup_step = {"label": "Warm-up", "minutes": option.warmup_min, "target": "easy"}

        if option.cooldown_ramp_pct is not None:
            cooldown_start, cooldown_end = option.cooldown_ramp_pct
            cooldown_step = {
                "label": "Cool-down ramp",
                "minutes": option.cooldown_min,
                "ramp": [cooldown_start, cooldown_end],
            }
        else:
            cooldown_step = {"label": "Cool-down", "minutes": option.cooldown_min, "target": "easy"}

        if option.interval_work_min is not None:
            assert option.interval_recovery_min is not None
            assert option.min_reps is not None and option.max_reps is not None
            cycle_min = option.interval_work_min + option.interval_recovery_min
            remaining_min = duration - option.warmup_min - option.cooldown_min
            reps = max(option.min_reps, min(option.max_reps, round(remaining_min / cycle_min)))
            main_min = int(round(reps * cycle_min))
            duration = option.warmup_min + main_min + option.cooldown_min
            main_step: dict[str, Any] = {
                "label": option.label,
                "target": option.main_target,
                "pattern": (
                    f"{reps} x {_pattern_minutes(option.interval_work_min)} / "
                    f"{_pattern_minutes(option.interval_recovery_min)} "
                    f"@{option.interval_recovery_target}"
                ),
            }
        else:
            main_min = duration - option.warmup_min - option.cooldown_min
            main_step = {"label": option.label, "minutes": main_min, "target": option.main_target}

        structured_workout: dict[str, Any] = {
            "format": "bike",
            "steps": [warmup_step, main_step, cooldown_step],
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
        workouts = list(
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
        logged_done_ids = await self._logged_done_workout_ids_on(user_id, workout_date)
        return [
            workout
            for workout in workouts
            if workout.status != WORKOUT_STATUS_COMPLETED and workout.id not in logged_done_ids
        ]

    async def _logged_done_workout_ids_on(
        self, user_id: uuid.UUID, workout_date: date
    ) -> set[uuid.UUID]:
        entries = (
            (
                await self.session.execute(
                    select(ManualEntry)
                    .where(
                        ManualEntry.user_id == user_id,
                        ManualEntry.entry_date == workout_date,
                        ManualEntry.planned_workout_id.is_not(None),
                        ManualEntry.activity_id.is_(None),
                    )
                    .order_by(ManualEntry.entry_at_utc.desc(), ManualEntry.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        latest_by_workout: dict[uuid.UUID, ManualEntry] = {}
        for entry in entries:
            if entry.planned_workout_id is None or entry.planned_workout_id in latest_by_workout:
                continue
            latest_by_workout[entry.planned_workout_id] = entry
        return {
            workout_id
            for workout_id, entry in latest_by_workout.items()
            if (entry.adherence_status or "").strip().lower() in DONE_ADHERENCE_STATUSES
        }
