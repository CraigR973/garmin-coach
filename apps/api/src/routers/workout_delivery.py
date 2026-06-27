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
from src.models.coaching import WorkoutDeliveryProposal
from src.services.executable_coaching import ExecutableCoachingService
from src.services.workout_delivery import WeekAheadEntry, WorkoutDeliveryService

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


class WeekAheadData(BaseModel):
    startDate: str
    days: int
    workouts: list[WeekAheadWorkoutOut]


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
    entries = await service.list_week_ahead(player, start_date=start, days=days)
    return WeekAheadEnvelope(
        data=WeekAheadData(
            startDate=start.isoformat(),
            days=days,
            workouts=[_serialize_week_ahead(entry) for entry in entries],
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
