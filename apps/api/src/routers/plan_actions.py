from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import CurrentUser
from src.database import get_db
from src.models.coaching import ManualEntry, PlannedWorkout
from src.services.plan_actions import PlanActionService, PlanDay, QuickAddOption, quick_add_options
from src.services.structured_workout_builder import CustomBikeWorkoutSpec, DeliveryTarget

router = APIRouter(prefix="/api/v1/plan-actions", tags=["plan-actions"])


def _generated_at() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")


def _local_today(timezone_name: str) -> date:
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        timezone = ZoneInfo("UTC")
    return datetime.now(timezone).date()


class ApiError(BaseModel):
    code: str
    detail: str


class ApiMeta(BaseModel):
    generatedAtUtc: str


class PlanWorkoutOut(BaseModel):
    id: str
    workoutDate: str
    version: int
    title: str
    workoutType: str
    status: str
    plannedDurationMin: int | None
    intensityTarget: str | None
    source: str | None
    structuredWorkout: dict[str, Any]


class DayStateOut(BaseModel):
    categories: list[str]
    label: str
    isRest: bool


class PlanDayOut(BaseModel):
    date: str
    dayState: DayStateOut
    workouts: list[PlanWorkoutOut]


class PlanScheduleData(BaseModel):
    startDate: str
    days: int
    schedule: list[PlanDayOut]


class PlanScheduleEnvelope(BaseModel):
    data: PlanScheduleData
    meta: ApiMeta
    errors: list[ApiError]


class CustomBikeWorkoutBody(BaseModel):
    delivery: DeliveryTarget = "indoor"
    warmupEnabled: bool = True
    warmupDurationMin: int | None = Field(default=10, ge=1, le=60)
    z2LeadInEnabled: bool = False
    z2LeadInDurationMin: int | None = Field(default=None, ge=1, le=180)
    intervalsEnabled: bool = False
    interval1DurationMin: int | None = Field(default=None, ge=1, le=120)
    interval1FtpPct: int | None = Field(default=None, ge=45, le=150)
    interval2DurationMin: int | None = Field(default=None, ge=1, le=120)
    interval2FtpPct: int | None = Field(default=None, ge=45, le=150)
    repeats: int | None = Field(default=None, ge=1, le=40)
    blockDurationMin: int | None = Field(default=30, ge=1, le=240)
    blockFtpPct: int | None = Field(default=65, ge=45, le=150)
    cooldownEnabled: bool = True
    cooldownDurationMin: int | None = Field(default=5, ge=1, le=60)

    def to_spec(self) -> CustomBikeWorkoutSpec:
        return CustomBikeWorkoutSpec(
            delivery=self.delivery,
            warmup_enabled=self.warmupEnabled,
            warmup_duration_min=self.warmupDurationMin,
            z2_lead_in_enabled=self.z2LeadInEnabled,
            z2_lead_in_duration_min=self.z2LeadInDurationMin,
            intervals_enabled=self.intervalsEnabled,
            interval_1_duration_min=self.interval1DurationMin,
            interval_1_ftp_pct=self.interval1FtpPct,
            interval_2_duration_min=self.interval2DurationMin,
            interval_2_ftp_pct=self.interval2FtpPct,
            repeats=self.repeats,
            block_duration_min=self.blockDurationMin,
            block_ftp_pct=self.blockFtpPct,
            cooldown_enabled=self.cooldownEnabled,
            cooldown_duration_min=self.cooldownDurationMin,
        )


class AddWorkoutBody(BaseModel):
    category: str = Field(pattern="^(cycle|weights|flexibility)$")
    subtype: str | None = None
    durationMin: int | None = Field(default=None, ge=1, le=180)
    customBike: CustomBikeWorkoutBody | None = None


class QuickAddOptionOut(BaseModel):
    subtype: str
    label: str
    defaultDurationMin: int
    minDurationMin: int
    maxDurationMin: int


class QuickAddOptionsData(BaseModel):
    category: str
    options: list[QuickAddOptionOut]


class QuickAddOptionsEnvelope(BaseModel):
    data: QuickAddOptionsData
    meta: ApiMeta
    errors: list[ApiError]


class SwapIntoDateBody(BaseModel):
    plannedWorkoutId: uuid.UUID


class RecordActualBody(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    notes: str | None = None


class WorkoutActionData(BaseModel):
    workout: PlanWorkoutOut


class WorkoutsActionData(BaseModel):
    workouts: list[PlanWorkoutOut]


class ManualEntryData(BaseModel):
    entry: dict[str, Any]


class WorkoutActionEnvelope(BaseModel):
    data: WorkoutActionData
    meta: ApiMeta
    errors: list[ApiError]


class WorkoutsActionEnvelope(BaseModel):
    data: WorkoutsActionData
    meta: ApiMeta
    errors: list[ApiError]


class ManualEntryEnvelope(BaseModel):
    data: ManualEntryData
    meta: ApiMeta
    errors: list[ApiError]


def _workout_out(workout: PlannedWorkout) -> PlanWorkoutOut:
    return PlanWorkoutOut(
        id=str(workout.id),
        workoutDate=workout.workout_date.isoformat(),
        version=workout.version,
        title=workout.title,
        workoutType=workout.workout_type,
        status=workout.status,
        plannedDurationMin=workout.planned_duration_min,
        intensityTarget=workout.intensity_target,
        source=workout.source,
        structuredWorkout=dict(workout.structured_workout or {}),
    )


def _day_out(day: PlanDay) -> PlanDayOut:
    return PlanDayOut(
        date=day.date.isoformat(),
        dayState=DayStateOut(
            categories=day.day_state.categories,
            label=day.day_state.label,
            isRest=day.day_state.is_rest,
        ),
        workouts=[_workout_out(workout) for workout in day.workouts],
    )


def _quick_add_option_out(option: QuickAddOption) -> QuickAddOptionOut:
    return QuickAddOptionOut(
        subtype=option.subtype,
        label=option.label,
        defaultDurationMin=option.default_duration_min,
        minDurationMin=option.min_duration_min,
        maxDurationMin=option.max_duration_min,
    )


def _entry_out(entry: ManualEntry) -> dict[str, Any]:
    return {
        "id": str(entry.id),
        "entryDate": entry.entry_date.isoformat(),
        "entryAtUtc": _dt(entry.entry_at_utc),
        "adherenceStatus": entry.adherence_status,
        "actualWorkoutJson": entry.actual_workout_json,
        "notes": entry.notes,
    }


@router.get("/schedule", response_model=PlanScheduleEnvelope)
async def get_schedule(
    player: CurrentUser,
    start_date: date | None = None,
    days: int = Query(default=7, ge=1, le=14),
    db: AsyncSession = Depends(get_db),
) -> PlanScheduleEnvelope:
    start = start_date or _local_today(player.timezone)
    schedule = await PlanActionService(db).schedule(player, start_date=start, days=days)
    return PlanScheduleEnvelope(
        data=PlanScheduleData(
            startDate=schedule.start_date.isoformat(),
            days=days,
            schedule=[_day_out(day) for day in schedule.days],
        ),
        meta=ApiMeta(generatedAtUtc=_generated_at()),
        errors=[],
    )


@router.get("/quick-add-options", response_model=QuickAddOptionsEnvelope)
async def get_quick_add_options(
    category: str,
    player: CurrentUser,
) -> QuickAddOptionsEnvelope:
    options = quick_add_options(category)
    return QuickAddOptionsEnvelope(
        data=QuickAddOptionsData(
            category=category,
            options=[_quick_add_option_out(option) for option in options],
        ),
        meta=ApiMeta(generatedAtUtc=_generated_at()),
        errors=[],
    )


@router.post("/days/{workout_date}/workouts", response_model=WorkoutActionEnvelope)
async def add_workout(
    workout_date: date,
    body: AddWorkoutBody,
    player: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> WorkoutActionEnvelope:
    workout = await PlanActionService(db).add_workout(
        player,
        workout_date=workout_date,
        category=body.category,
        subtype=body.subtype,
        duration_min=body.durationMin,
        custom_bike=body.customBike.to_spec() if body.customBike is not None else None,
    )
    return WorkoutActionEnvelope(
        data=WorkoutActionData(workout=_workout_out(workout)),
        meta=ApiMeta(generatedAtUtc=_generated_at()),
        errors=[],
    )


@router.post(
    "/planned-workouts/{planned_workout_id}/structured",
    response_model=WorkoutActionEnvelope,
)
async def edit_structured_workout(
    planned_workout_id: uuid.UUID,
    body: CustomBikeWorkoutBody,
    player: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> WorkoutActionEnvelope:
    workout = await PlanActionService(db).edit_structured_workout(
        player,
        planned_workout_id=planned_workout_id,
        custom_bike=body.to_spec(),
    )
    return WorkoutActionEnvelope(
        data=WorkoutActionData(workout=_workout_out(workout)),
        meta=ApiMeta(generatedAtUtc=_generated_at()),
        errors=[],
    )


@router.post("/days/{target_date}/swap-in", response_model=WorkoutActionEnvelope)
async def swap_workout_into_date(
    target_date: date,
    body: SwapIntoDateBody,
    player: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> WorkoutActionEnvelope:
    workout = await PlanActionService(db).swap_workout_into_date(
        player, planned_workout_id=body.plannedWorkoutId, target_date=target_date
    )
    return WorkoutActionEnvelope(
        data=WorkoutActionData(workout=_workout_out(workout)),
        meta=ApiMeta(generatedAtUtc=_generated_at()),
        errors=[],
    )


@router.post("/days/{workout_date}/skip", response_model=WorkoutsActionEnvelope)
async def skip_day(
    workout_date: date,
    player: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> WorkoutsActionEnvelope:
    workouts = await PlanActionService(db).skip_day(player, workout_date=workout_date)
    return WorkoutsActionEnvelope(
        data=WorkoutsActionData(workouts=[_workout_out(workout) for workout in workouts]),
        meta=ApiMeta(generatedAtUtc=_generated_at()),
        errors=[],
    )


@router.post("/days/{workout_date}/actual", response_model=ManualEntryEnvelope)
async def record_actual(
    workout_date: date,
    body: RecordActualBody,
    player: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> ManualEntryEnvelope:
    entry = await PlanActionService(db).record_actual(
        player, workout_date=workout_date, label=body.label, notes=body.notes
    )
    return ManualEntryEnvelope(
        data=ManualEntryData(entry=_entry_out(entry)),
        meta=ApiMeta(generatedAtUtc=_generated_at()),
        errors=[],
    )
