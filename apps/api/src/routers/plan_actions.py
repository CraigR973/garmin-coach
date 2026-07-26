from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import CurrentUser
from src.database import get_db
from src.models.coaching import (
    Analysis,
    Feedback,
    GarminWorkoutDelivery,
    ManualEntry,
    PlannedWorkout,
)
from src.routers.feedback import FeedbackOut, serialize_feedback
from src.services.garmin_workout_delivery import GarminWorkoutDeliveryService
from src.services.plan_actions import (
    PlanActionService,
    PlanActivity,
    PlanDay,
    QuickAddOption,
    WeekCharacter,
    quick_add_options,
)
from src.services.post_activity_state import (
    STATUS_FAILED,
    STATUS_GENERATING,
    SUPPORTED_POST_SESSION_ANALYSIS_TYPES,
    PostActivityGenerationStatusService,
    effective_generation_state,
)
from src.services.structured_workout_builder import (
    ABS_MAX_POWER_PCT,
    ABS_MIN_POWER_PCT,
    MAX_TOTAL_DURATION_MIN,
    DeliveryTarget,
    FreeformBikeWorkoutSpec,
    WorkoutSegment,
)

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


class ApiWarning(BaseModel):
    """Advisory returned on a *successful* save (Batch 88) — the non-blocking analog
    of ``ApiError``, sibling to ``errors`` on the envelope."""

    code: str
    detail: str


class ApiMeta(BaseModel):
    generatedAtUtc: str


class OutdoorDeliveryOut(BaseModel):
    status: str
    lastError: str | None = None


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
    # Batch 78: the outdoor ride's Garmin delivery state (None for indoor/non-bike).
    outdoorDelivery: OutdoorDeliveryOut | None = None


class PlanActivityOut(BaseModel):
    activityKind: str
    name: str
    durationMin: int | None
    startUtc: str


class DayStateOut(BaseModel):
    categories: list[str]
    label: str
    isRest: bool


class WeekCharacterOut(BaseModel):
    label: str
    sequenceIndex: int | None
    blockType: str | None
    isHoliday: bool
    isReset: bool


class PlanDayOut(BaseModel):
    date: str
    dayState: DayStateOut
    workouts: list[PlanWorkoutOut]
    activities: list[PlanActivityOut]
    weekCharacter: WeekCharacterOut | None = None


class PlanScheduleData(BaseModel):
    startDate: str
    days: int
    schedule: list[PlanDayOut]


class PlanScheduleEnvelope(BaseModel):
    data: PlanScheduleData
    meta: ApiMeta
    errors: list[ApiError]


class WorkoutReadOut(BaseModel):
    """Batch 152: the persisted post-workout read for a completed planned workout.

    ``verdict`` is the post-session recovery status the read stored, not the
    morning Green/Amber/Red. ``feedback`` mirrors the Home read so the same
    rate/correct control shows Mark's existing rating.
    """

    analysisId: str
    analysisType: str
    verdict: str | None
    generatedAtUtc: str
    outputMarkdown: str
    feedback: FeedbackOut | None = None


class WorkoutReadData(BaseModel):
    state: Literal["absent", "generating", "failed", "ready"]
    reason: str | None = None
    read: WorkoutReadOut | None


class WorkoutReadEnvelope(BaseModel):
    data: WorkoutReadData
    meta: ApiMeta
    errors: list[ApiError]


# Pydantic enforces the *absolute* deliverable floor only (power 1-300% FTP,
# positive durations up to the total cap). The coaching-sensible 45-150% band is
# deliberately NOT enforced here — an out-of-band value saves and warns on Mark's
# manual authoring path (Batch 88, Decision #161); the builder decides warn-vs-block.
_PowerPct = Annotated[int, Field(ge=ABS_MIN_POWER_PCT, le=ABS_MAX_POWER_PCT)]
_DurationMin = Annotated[int, Field(ge=1, le=MAX_TOTAL_DURATION_MIN)]


class RampSegmentBody(BaseModel):
    kind: Literal["ramp"]
    durationMin: _DurationMin
    startFtpPct: _PowerPct
    endFtpPct: _PowerPct


class SteadySegmentBody(BaseModel):
    kind: Literal["steady"]
    durationMin: _DurationMin
    ftpPct: _PowerPct


class IntervalSegmentBody(BaseModel):
    kind: Literal["interval"]
    repeats: int = Field(ge=1, le=50)
    workMin: _DurationMin
    workFtpPct: _PowerPct
    recoverMin: _DurationMin
    recoverFtpPct: _PowerPct


AnySegmentBody = RampSegmentBody | SteadySegmentBody | IntervalSegmentBody
WorkoutSegmentBody = Annotated[AnySegmentBody, Field(discriminator="kind")]


def _segment_to_spec(body: AnySegmentBody) -> WorkoutSegment:
    if isinstance(body, RampSegmentBody):
        return WorkoutSegment(
            kind="ramp",
            duration_min=body.durationMin,
            start_ftp_pct=body.startFtpPct,
            end_ftp_pct=body.endFtpPct,
        )
    if isinstance(body, SteadySegmentBody):
        return WorkoutSegment(kind="steady", duration_min=body.durationMin, ftp_pct=body.ftpPct)
    return WorkoutSegment(
        kind="interval",
        repeats=body.repeats,
        work_min=body.workMin,
        work_ftp_pct=body.workFtpPct,
        recover_min=body.recoverMin,
        recover_ftp_pct=body.recoverFtpPct,
    )


class FreeformBikeWorkoutBody(BaseModel):
    delivery: DeliveryTarget = "indoor"
    segments: list[WorkoutSegmentBody] = Field(min_length=1, max_length=40)

    def to_spec(self) -> FreeformBikeWorkoutSpec:
        return FreeformBikeWorkoutSpec(
            delivery=self.delivery,
            segments=tuple(_segment_to_spec(segment) for segment in self.segments),
        )


class AddWorkoutBody(BaseModel):
    category: str = Field(pattern="^(cycle|weights|flexibility)$")
    subtype: str | None = None
    durationMin: int | None = Field(default=None, ge=1, le=180)
    customBike: FreeformBikeWorkoutBody | None = None


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
    warnings: list[ApiWarning] = Field(default_factory=list)


class WorkoutsActionEnvelope(BaseModel):
    data: WorkoutsActionData
    meta: ApiMeta
    errors: list[ApiError]


class ManualEntryEnvelope(BaseModel):
    data: ManualEntryData
    meta: ApiMeta
    errors: list[ApiError]


def _workout_out(
    workout: PlannedWorkout, delivery: GarminWorkoutDelivery | None = None
) -> PlanWorkoutOut:
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
        outdoorDelivery=(
            OutdoorDeliveryOut(status=delivery.status, lastError=delivery.last_error)
            if delivery is not None
            else None
        ),
    )


def _week_character_out(character: WeekCharacter | None) -> WeekCharacterOut | None:
    if character is None:
        return None
    return WeekCharacterOut(
        label=character.label,
        sequenceIndex=character.sequence_index,
        blockType=character.block_type,
        isHoliday=character.is_holiday,
        isReset=character.is_reset,
    )


def _day_out(
    day: PlanDay, deliveries: dict[uuid.UUID, GarminWorkoutDelivery] | None = None
) -> PlanDayOut:
    deliveries = deliveries or {}
    return PlanDayOut(
        date=day.date.isoformat(),
        dayState=DayStateOut(
            categories=day.day_state.categories,
            label=day.day_state.label,
            isRest=day.day_state.is_rest,
        ),
        workouts=[_workout_out(workout, deliveries.get(workout.id)) for workout in day.workouts],
        activities=[_activity_out(activity) for activity in day.activities],
        weekCharacter=_week_character_out(day.week_character),
    )


def _activity_out(entry: PlanActivity) -> PlanActivityOut:
    duration_min = (
        int(round(entry.activity.duration_sec / 60))
        if entry.activity.duration_sec is not None
        else None
    )
    return PlanActivityOut(
        activityKind=entry.activity_kind,
        name=entry.activity.activity_name,
        durationMin=duration_min,
        startUtc=_dt(entry.activity.start_utc) or "",
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
    # Batch 78: attach each outdoor ride's Garmin delivery state (keyed by the delivered
    # planned-workout id) so a failed upload shows on the workout instead of vanishing.
    end = schedule.days[-1].date if schedule.days else start
    delivery_rows = await GarminWorkoutDeliveryService(db).deliveries_in_range(
        player.id, schedule.start_date, end
    )
    deliveries_by_id = {
        row.planned_workout_id: row for row in delivery_rows if row.planned_workout_id is not None
    }
    return PlanScheduleEnvelope(
        data=PlanScheduleData(
            startDate=schedule.start_date.isoformat(),
            days=days,
            schedule=[_day_out(day, deliveries_by_id) for day in schedule.days],
        ),
        meta=ApiMeta(generatedAtUtc=_generated_at()),
        errors=[],
    )


@router.get(
    "/workouts/{planned_workout_id}/analysis",
    response_model=WorkoutReadEnvelope,
)
async def get_workout_analysis(
    planned_workout_id: uuid.UUID,
    player: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> WorkoutReadEnvelope:
    """The persisted, owned post-session read for a completed planned workout.

    Batch 159 constrains selection to the four supported post-session types and
    verifies workout ownership before looking up either the read or its activity-
    scoped status. This remains retrieval-only; a foreign/unknown id is the same
    non-disclosing ``absent`` state as an owned workout with no synced read.
    """
    workout = await db.scalar(
        select(PlannedWorkout).where(
            PlannedWorkout.id == planned_workout_id,
            PlannedWorkout.user_id == player.id,
        )
    )
    analysis: Analysis | None = None
    generation_state: Literal["absent", "generating", "failed", "ready"] = "absent"
    reason: str | None = None
    if workout is not None:
        analysis = await db.scalar(
            select(Analysis)
            .where(
                Analysis.user_id == player.id,
                Analysis.planned_workout_id == planned_workout_id,
                Analysis.analysis_type.in_(SUPPORTED_POST_SESSION_ANALYSIS_TYPES),
            )
            .order_by(desc(Analysis.generated_at_utc), desc(Analysis.id))
            .limit(1)
        )
        if analysis is not None:
            generation_state = "ready"
        else:
            status_row = await PostActivityGenerationStatusService(db).latest_for_workout(
                player.id, planned_workout_id
            )
            if status_row is not None:
                effective_state, effective_reason = effective_generation_state(status_row)
                if effective_state == STATUS_GENERATING:
                    generation_state = "generating"
                    reason = effective_reason
                elif effective_state == STATUS_FAILED:
                    generation_state = "failed"
                    reason = effective_reason

    read: WorkoutReadOut | None = None
    if analysis is not None:
        feedback = await db.scalar(
            select(Feedback).where(
                Feedback.user_id == player.id,
                Feedback.analysis_id == analysis.id,
            )
        )
        read = WorkoutReadOut(
            analysisId=str(analysis.id),
            analysisType=analysis.analysis_type,
            verdict=analysis.verdict,
            generatedAtUtc=_dt(analysis.generated_at_utc) or "",
            outputMarkdown=analysis.output_markdown,
            feedback=serialize_feedback(feedback) if feedback is not None else None,
        )
    return WorkoutReadEnvelope(
        data=WorkoutReadData(state=generation_state, reason=reason, read=read),
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
    result = await PlanActionService(db).add_workout(
        player,
        workout_date=workout_date,
        category=body.category,
        subtype=body.subtype,
        duration_min=body.durationMin,
        custom_bike=body.customBike.to_spec() if body.customBike is not None else None,
    )
    return WorkoutActionEnvelope(
        data=WorkoutActionData(workout=_workout_out(result.workout)),
        meta=ApiMeta(generatedAtUtc=_generated_at()),
        errors=[],
        warnings=[ApiWarning(code=w.code, detail=w.detail) for w in result.warnings],
    )


@router.post(
    "/planned-workouts/{planned_workout_id}/structured",
    response_model=WorkoutActionEnvelope,
)
async def edit_structured_workout(
    planned_workout_id: uuid.UUID,
    body: FreeformBikeWorkoutBody,
    player: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> WorkoutActionEnvelope:
    result = await PlanActionService(db).edit_structured_workout(
        player,
        planned_workout_id=planned_workout_id,
        custom_bike=body.to_spec(),
    )
    return WorkoutActionEnvelope(
        data=WorkoutActionData(workout=_workout_out(result.workout)),
        meta=ApiMeta(generatedAtUtc=_generated_at()),
        errors=[],
        warnings=[ApiWarning(code=w.code, detail=w.detail) for w in result.warnings],
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


@router.post("/weeks/{week_date}/reset", response_model=WorkoutsActionEnvelope)
async def mark_reset_week(
    week_date: date,
    player: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> WorkoutsActionEnvelope:
    workouts = await PlanActionService(db).mark_reset_week(player, week_date=week_date)
    return WorkoutsActionEnvelope(
        data=WorkoutsActionData(workouts=[_workout_out(workout) for workout in workouts]),
        meta=ApiMeta(generatedAtUtc=_generated_at()),
        errors=[],
    )


@router.delete("/weeks/{week_date}/reset", response_model=WorkoutsActionEnvelope)
async def unset_reset_week(
    week_date: date,
    player: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> WorkoutsActionEnvelope:
    workouts = await PlanActionService(db).unset_reset_week(player, week_date=week_date)
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
