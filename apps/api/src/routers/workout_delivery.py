from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import CurrentUser
from src.database import get_db
from src.models.coaching import PlannedWorkout, WorkoutDeliveryProposal
from src.services.executable_coaching import ExecutableCoachingService
from src.services.workout_delivery import (
    PlanActivity,
    WeekAheadDayActivities,
    WeekAheadEntry,
    WorkoutDeliveryService,
)

router = APIRouter(prefix="/api/v1/workout-delivery", tags=["workout-delivery"])


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


class WorkoutDeliveryProposalOut(BaseModel):
    id: str
    userId: str
    plannedWorkoutId: str | None
    plannedWorkoutVersion: int
    workoutDate: str
    provider: str
    status: str
    proposedAtUtc: str
    approvedAtUtc: str | None
    approvedByProfileId: str | None
    pushedAtUtc: str | None
    intervalsEventId: str | None
    structuredWorkoutIr: dict[str, Any]
    intervalsPayload: dict[str, Any]
    zwoXml: str
    lastError: str | None


class WorkoutDeliveryData(BaseModel):
    proposals: list[WorkoutDeliveryProposalOut]


class WorkoutDeliveryEnvelope(BaseModel):
    data: WorkoutDeliveryData
    meta: ApiMeta
    errors: list[ApiError]


class SameDayDeliveryBody(BaseModel):
    durationScalePct: int | None = Field(default=None, ge=50, le=125)
    intensityScalePct: int | None = Field(default=None, ge=50, le=120)


class SwapDayBody(BaseModel):
    targetDate: date


class PlannedWorkoutActionOut(BaseModel):
    id: str
    workoutDate: str
    version: int
    title: str
    workoutType: str
    status: str
    isActive: bool


class PlannedWorkoutActionData(BaseModel):
    workout: PlannedWorkoutActionOut


class PlannedWorkoutActionEnvelope(BaseModel):
    data: PlannedWorkoutActionData
    meta: ApiMeta
    errors: list[ApiError]


class WeekAheadWorkoutOut(BaseModel):
    plannedWorkoutId: str
    workoutDate: str
    version: int
    title: str
    workoutType: str
    status: str
    plannedDurationMin: int | None
    intensityTarget: str | None
    deliverable: bool
    proposal: WorkoutDeliveryProposalOut | None


class PlanActivityOut(BaseModel):
    activityKind: str
    name: str
    durationMin: int | None
    startUtc: str


class WeekAheadDayActivitiesOut(BaseModel):
    date: str
    activities: list[PlanActivityOut]


class WeekAheadData(BaseModel):
    startDate: str
    days: int
    workouts: list[WeekAheadWorkoutOut]
    dayActivities: list[WeekAheadDayActivitiesOut]


class WeekAheadEnvelope(BaseModel):
    data: WeekAheadData
    meta: ApiMeta
    errors: list[ApiError]


def _serialize(proposal: WorkoutDeliveryProposal) -> WorkoutDeliveryProposalOut:
    return WorkoutDeliveryProposalOut(
        id=str(proposal.id),
        userId=str(proposal.user_id),
        plannedWorkoutId=(
            str(proposal.planned_workout_id) if proposal.planned_workout_id else None
        ),
        plannedWorkoutVersion=proposal.planned_workout_version,
        workoutDate=proposal.workout_date.isoformat(),
        provider=proposal.provider,
        status=proposal.status,
        proposedAtUtc=_dt(proposal.proposed_at_utc) or "",
        approvedAtUtc=_dt(proposal.approved_at_utc),
        approvedByProfileId=(
            str(proposal.approved_by_profile_id) if proposal.approved_by_profile_id else None
        ),
        pushedAtUtc=_dt(proposal.pushed_at_utc),
        intervalsEventId=proposal.intervals_event_id,
        structuredWorkoutIr=proposal.structured_workout_ir,
        intervalsPayload=proposal.intervals_payload,
        zwoXml=proposal.zwo_xml,
        lastError=proposal.last_error,
    )


def _envelope(proposals: list[WorkoutDeliveryProposal]) -> WorkoutDeliveryEnvelope:
    return WorkoutDeliveryEnvelope(
        data=WorkoutDeliveryData(proposals=[_serialize(proposal) for proposal in proposals]),
        meta=ApiMeta(generatedAtUtc=_generated_at()),
        errors=[],
    )


def _planned_envelope(workout: PlannedWorkout) -> PlannedWorkoutActionEnvelope:
    return PlannedWorkoutActionEnvelope(
        data=PlannedWorkoutActionData(
            workout=PlannedWorkoutActionOut(
                id=str(workout.id),
                workoutDate=workout.workout_date.isoformat(),
                version=workout.version,
                title=workout.title,
                workoutType=workout.workout_type,
                status=workout.status,
                isActive=workout.is_active,
            )
        ),
        meta=ApiMeta(generatedAtUtc=_generated_at()),
        errors=[],
    )


def _serialize_week_ahead(entry: WeekAheadEntry) -> WeekAheadWorkoutOut:
    workout = entry.workout
    return WeekAheadWorkoutOut(
        plannedWorkoutId=str(workout.id),
        workoutDate=workout.workout_date.isoformat(),
        version=workout.version,
        title=workout.title,
        workoutType=workout.workout_type,
        status=workout.status,
        plannedDurationMin=workout.planned_duration_min,
        intensityTarget=workout.intensity_target,
        deliverable=True,
        proposal=_serialize(entry.proposal) if entry.proposal is not None else None,
    )


def _serialize_activity(entry: PlanActivity) -> PlanActivityOut:
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


def _serialize_day_activities(entry: WeekAheadDayActivities) -> WeekAheadDayActivitiesOut:
    return WeekAheadDayActivitiesOut(
        date=entry.date.isoformat(),
        activities=[_serialize_activity(activity) for activity in entry.activities],
    )


@router.get("/proposals", response_model=WorkoutDeliveryEnvelope)
async def list_workout_delivery_proposals(
    player: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> WorkoutDeliveryEnvelope:
    service = WorkoutDeliveryService(db)
    proposals = await service.list_proposals(player)
    return _envelope(proposals)


@router.get("/week-ahead", response_model=WeekAheadEnvelope)
async def list_workout_delivery_week_ahead(
    player: CurrentUser,
    start_date: date | None = None,
    days: int = Query(default=7, ge=1, le=14),
    db: AsyncSession = Depends(get_db),
) -> WeekAheadEnvelope:
    service = WorkoutDeliveryService(db)
    start = start_date or _local_today(player.timezone)
    entries, day_activities = await service.list_week_ahead(player, start_date=start, days=days)
    return WeekAheadEnvelope(
        data=WeekAheadData(
            startDate=start.isoformat(),
            days=days,
            workouts=[_serialize_week_ahead(entry) for entry in entries],
            dayActivities=[_serialize_day_activities(entry) for entry in day_activities],
        ),
        meta=ApiMeta(generatedAtUtc=_generated_at()),
        errors=[],
    )


@router.post(
    "/planned-workouts/{planned_workout_id}/proposals",
    response_model=WorkoutDeliveryEnvelope,
)
async def propose_workout_delivery(
    planned_workout_id: uuid.UUID,
    player: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> WorkoutDeliveryEnvelope:
    service = WorkoutDeliveryService(db)
    proposal = await service.propose(player=player, planned_workout_id=planned_workout_id)
    return _envelope([proposal])


@router.post(
    "/planned-workouts/{planned_workout_id}/send-today",
    response_model=WorkoutDeliveryEnvelope,
)
async def send_workout_delivery_today(
    planned_workout_id: uuid.UUID,
    body: SameDayDeliveryBody,
    player: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> WorkoutDeliveryEnvelope:
    service = ExecutableCoachingService(db)
    proposal = await service.send_today(
        player,
        planned_workout_id=planned_workout_id,
        duration_scale_pct=body.durationScalePct,
        intensity_scale_pct=body.intensityScalePct,
    )
    return _envelope([proposal])


@router.post(
    "/planned-workouts/{planned_workout_id}/edit",
    response_model=WorkoutDeliveryEnvelope,
)
async def edit_today_workout(
    planned_workout_id: uuid.UUID,
    body: SameDayDeliveryBody,
    player: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> WorkoutDeliveryEnvelope:
    """Today card — Manual Edit: re-sync the live Zwift event with a scaled IR."""
    service = ExecutableCoachingService(db)
    proposal = await service.edit_today(
        player,
        planned_workout_id=planned_workout_id,
        duration_scale_pct=body.durationScalePct,
        intensity_scale_pct=body.intensityScalePct,
    )
    return _envelope([proposal])


@router.post(
    "/planned-workouts/{planned_workout_id}/approve-adjustment",
    response_model=WorkoutDeliveryEnvelope,
)
async def approve_today_adjustment(
    planned_workout_id: uuid.UUID,
    player: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> WorkoutDeliveryEnvelope:
    """Today card — Approve & upload: replace the live event with the coach-adjusted
    IR. Red-never-VO2 still gates this at the delivery boundary."""
    service = ExecutableCoachingService(db)
    proposal = await service.approve_adjustment(player, planned_workout_id=planned_workout_id)
    return _envelope([proposal])


@router.post(
    "/planned-workouts/{planned_workout_id}/skip",
    response_model=PlannedWorkoutActionEnvelope,
)
async def skip_today_workout(
    planned_workout_id: uuid.UUID,
    player: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> PlannedWorkoutActionEnvelope:
    """Today card — Skip: a ``planned → skipped`` transition plus a Zwift delete."""
    service = ExecutableCoachingService(db)
    workout = await service.skip_workout(player, planned_workout_id=planned_workout_id)
    return _planned_envelope(workout)


@router.post(
    "/planned-workouts/{planned_workout_id}/remove",
    response_model=PlannedWorkoutActionEnvelope,
)
async def remove_added_workout(
    planned_workout_id: uuid.UUID,
    player: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> PlannedWorkoutActionEnvelope:
    """Today card — Remove: deactivate a user-added workout and delete any live
    Zwift event, keeping Skip for coach-planned adherence tracking."""
    service = ExecutableCoachingService(db)
    workout = await service.remove_workout(player, planned_workout_id=planned_workout_id)
    return _planned_envelope(workout)


@router.post(
    "/planned-workouts/{planned_workout_id}/swap",
    response_model=PlannedWorkoutActionEnvelope,
)
async def swap_today_workout_day(
    planned_workout_id: uuid.UUID,
    body: SwapDayBody,
    player: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> PlannedWorkoutActionEnvelope:
    """Today card — Swap day: unified move-or-swap to ``targetDate`` with the
    affected Zwift events moved in place."""
    service = ExecutableCoachingService(db)
    workout = await service.swap_day(
        player,
        planned_workout_id=planned_workout_id,
        target_date=body.targetDate,
    )
    return _planned_envelope(workout)


@router.post("/proposals/{proposal_id}/approve", response_model=WorkoutDeliveryEnvelope)
async def approve_workout_delivery_proposal(
    proposal_id: uuid.UUID,
    player: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> WorkoutDeliveryEnvelope:
    service = WorkoutDeliveryService(db)
    proposal = await service.approve(player=player, proposal_id=proposal_id)
    return _envelope([proposal])


@router.post("/proposals/{proposal_id}/push", response_model=WorkoutDeliveryEnvelope)
async def push_workout_delivery_proposal(
    proposal_id: uuid.UUID,
    player: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> WorkoutDeliveryEnvelope:
    service = WorkoutDeliveryService(db)
    proposal = await service.push(player=player, proposal_id=proposal_id)
    return _envelope([proposal])


@router.get("/proposals/{proposal_id}/zwo")
async def download_workout_delivery_zwo(
    proposal_id: uuid.UUID,
    player: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> Response:
    service = WorkoutDeliveryService(db)
    proposal = await service._proposal(player.id, proposal_id)
    filename = f"{proposal.workout_date.isoformat()}-garmin-coach.zwo"
    return Response(
        proposal.zwo_xml,
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
