from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import AdminPlayer
from src.database import get_db
from src.models.coaching import KnowledgeBase, PlanBlock, PlannedWorkout
from src.services.coaching_state import CoachingStateService

router = APIRouter(prefix="/api/v1/admin/coaching-state", tags=["coaching-state"])


def _generated_at() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class ApiError(BaseModel):
    code: str
    detail: str


class ApiMeta(BaseModel):
    generatedAtUtc: str
    seeded: bool = False


class KnowledgeBaseUpdateBody(BaseModel):
    source: str | None = None
    content: dict[str, Any] = Field(default_factory=dict)


class PlannedWorkoutOverrideBody(BaseModel):
    planBlockId: str | None = None
    title: str
    workoutType: str
    status: str = "planned"
    plannedDurationMin: int | None = None
    intensityTarget: str | None = None
    structuredWorkout: dict[str, Any] = Field(default_factory=dict)
    source: str | None = None


class KnowledgeBaseOut(BaseModel):
    id: str
    userId: str
    section: str
    version: int
    isActive: bool
    source: str | None
    content: dict[str, Any]
    updatedByProfileId: str | None


class PlanBlockOut(BaseModel):
    id: str
    userId: str
    name: str
    version: int
    sequenceIndex: int | None
    blockType: str | None
    startDate: str
    endDate: str
    goalsJson: dict[str, Any]
    rawPlan: dict[str, Any]


class PlannedWorkoutOut(BaseModel):
    id: str
    userId: str
    planBlockId: str | None
    workoutDate: str
    version: int
    title: str
    workoutType: str
    status: str
    isActive: bool
    plannedDurationMin: int | None
    intensityTarget: str | None
    structuredWorkout: dict[str, Any]
    source: str | None


class CoachingStateData(BaseModel):
    knowledgeBaseSections: list[KnowledgeBaseOut]
    planBlocks: list[PlanBlockOut]
    plannedWorkouts: list[PlannedWorkoutOut]


class CoachingStateEnvelope(BaseModel):
    data: CoachingStateData
    meta: ApiMeta
    errors: list[ApiError]


def _serialize_knowledge_base(record: KnowledgeBase) -> KnowledgeBaseOut:
    return KnowledgeBaseOut(
        id=str(record.id),
        userId=str(record.user_id),
        section=record.section,
        version=record.version,
        isActive=record.is_active,
        source=record.source,
        content=record.content,
        updatedByProfileId=(
            str(record.updated_by_profile_id) if record.updated_by_profile_id else None
        ),
    )


def _serialize_plan_block(record: PlanBlock) -> PlanBlockOut:
    return PlanBlockOut(
        id=str(record.id),
        userId=str(record.user_id),
        name=record.name,
        version=record.version,
        sequenceIndex=record.sequence_index,
        blockType=record.block_type,
        startDate=record.start_date.isoformat(),
        endDate=record.end_date.isoformat(),
        goalsJson=record.goals_json,
        rawPlan=record.raw_plan,
    )


def _serialize_planned_workout(record: PlannedWorkout) -> PlannedWorkoutOut:
    return PlannedWorkoutOut(
        id=str(record.id),
        userId=str(record.user_id),
        planBlockId=str(record.plan_block_id) if record.plan_block_id else None,
        workoutDate=record.workout_date.isoformat(),
        version=record.version,
        title=record.title,
        workoutType=record.workout_type,
        status=record.status,
        isActive=record.is_active,
        plannedDurationMin=record.planned_duration_min,
        intensityTarget=record.intensity_target,
        structuredWorkout=record.structured_workout,
        source=record.source,
    )


def _envelope(
    *,
    knowledge_base_sections: list[KnowledgeBase],
    plan_blocks: list[PlanBlock],
    planned_workouts: list[PlannedWorkout],
    seeded: bool,
) -> CoachingStateEnvelope:
    return CoachingStateEnvelope(
        data=CoachingStateData(
            knowledgeBaseSections=[
                _serialize_knowledge_base(section) for section in knowledge_base_sections
            ],
            planBlocks=[_serialize_plan_block(block) for block in plan_blocks],
            plannedWorkouts=[_serialize_planned_workout(workout) for workout in planned_workouts],
        ),
        meta=ApiMeta(generatedAtUtc=_generated_at(), seeded=seeded),
        errors=[],
    )


@router.get("", response_model=CoachingStateEnvelope)
async def get_coaching_state(
    player: AdminPlayer,
    db: AsyncSession = Depends(get_db),
) -> CoachingStateEnvelope:
    service = CoachingStateService(db)
    snapshot = await service.get_snapshot(player)
    return _envelope(
        knowledge_base_sections=snapshot.knowledge_base_sections,
        plan_blocks=snapshot.plan_blocks,
        planned_workouts=snapshot.planned_workouts,
        seeded=snapshot.seeded,
    )


@router.put("/knowledge-base/{section}", response_model=CoachingStateEnvelope)
async def update_knowledge_base_section(
    section: str,
    body: KnowledgeBaseUpdateBody,
    player: AdminPlayer,
    db: AsyncSession = Depends(get_db),
) -> CoachingStateEnvelope:
    service = CoachingStateService(db)
    await service.update_knowledge_base_section(
        player=player,
        section=section,
        content=body.content,
        source=body.source,
    )
    snapshot = await service.get_snapshot(player)
    return _envelope(
        knowledge_base_sections=snapshot.knowledge_base_sections,
        plan_blocks=snapshot.plan_blocks,
        planned_workouts=snapshot.planned_workouts,
        seeded=snapshot.seeded,
    )


@router.put("/planned-workouts/{workout_date}", response_model=CoachingStateEnvelope)
async def override_planned_workout(
    workout_date: date,
    body: PlannedWorkoutOverrideBody,
    player: AdminPlayer,
    db: AsyncSession = Depends(get_db),
) -> CoachingStateEnvelope:
    service = CoachingStateService(db)
    plan_block_id = uuid.UUID(body.planBlockId) if body.planBlockId else None
    await service.override_planned_workout(
        player=player,
        workout_date=workout_date,
        title=body.title,
        workout_type=body.workoutType,
        status_value=body.status,
        planned_duration_min=body.plannedDurationMin,
        intensity_target=body.intensityTarget,
        structured_workout=body.structuredWorkout,
        source=body.source,
        plan_block_id=plan_block_id,
    )
    snapshot = await service.get_snapshot(player)
    return _envelope(
        knowledge_base_sections=snapshot.knowledge_base_sections,
        plan_blocks=snapshot.plan_blocks,
        planned_workouts=snapshot.planned_workouts,
        seeded=snapshot.seeded,
    )
