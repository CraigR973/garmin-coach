"""App-generated 13-week block API (Batch 16).

Refine-then-lock workflow (Decision #16), all human-driven so nothing reaches the
plan or Zwift silently (Decision #29):

  GET  /api/v1/block-generator          — current draft (or null) + canGenerate
  POST /api/v1/block-generator/generate — produce a fresh 13-week 2121 draft
  POST /api/v1/block-generator/refine   — edit a single day in the draft
  POST /api/v1/block-generator/lock     — write the draft into the owned plan
  POST /api/v1/block-generator/discard  — drop an unlocked draft
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import CurrentUser
from src.database import get_db
from src.services.block_generator import STATUS_DRAFT, BlockGeneratorService

router = APIRouter(prefix="/api/v1/block-generator", tags=["block-generator"])


def _generated_at() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class ApiError(BaseModel):
    code: str
    detail: str


class ApiMeta(BaseModel):
    generatedAtUtc: str


class DraftData(BaseModel):
    draft: dict[str, Any] | None
    canGenerate: bool


class DraftEnvelope(BaseModel):
    data: DraftData
    meta: ApiMeta
    errors: list[ApiError]


class GenerateInput(BaseModel):
    startDate: str | None = None
    ftpWatts: int | None = Field(default=None, gt=0)


class RefineInput(BaseModel):
    weekNumber: int = Field(gt=0)
    dayOffset: int = Field(ge=0)
    title: str | None = None
    workoutType: str | None = None
    plannedDurationMin: int | None = Field(default=None, gt=0)
    intensityTarget: str | None = None
    structuredWorkout: dict[str, Any] | None = None


class LockData(BaseModel):
    blocksCreated: int
    workoutsWritten: int
    startDate: str
    endDate: str


class LockEnvelope(BaseModel):
    data: LockData
    meta: ApiMeta
    errors: list[ApiError]


class DiscardData(BaseModel):
    discarded: bool


class DiscardEnvelope(BaseModel):
    data: DiscardData
    meta: ApiMeta
    errors: list[ApiError]


def _draft_envelope(draft: dict[str, Any] | None) -> DraftEnvelope:
    can_generate = draft is None or draft.get("status") != STATUS_DRAFT
    return DraftEnvelope(
        data=DraftData(draft=draft, canGenerate=can_generate),
        meta=ApiMeta(generatedAtUtc=_generated_at()),
        errors=[],
    )


@router.get("", response_model=DraftEnvelope)
async def get_draft(
    player: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> DraftEnvelope:
    service = BlockGeneratorService(db)
    draft = await service.get_draft(player)
    return _draft_envelope(draft)


@router.post("/generate", response_model=DraftEnvelope)
async def generate_block(
    body: GenerateInput,
    player: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> DraftEnvelope:
    service = BlockGeneratorService(db)
    draft = await service.generate(
        player,
        start_date=date.fromisoformat(body.startDate) if body.startDate else None,
        ftp_watts=body.ftpWatts,
    )
    return _draft_envelope(draft)


@router.post("/refine", response_model=DraftEnvelope)
async def refine_block(
    body: RefineInput,
    player: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> DraftEnvelope:
    service = BlockGeneratorService(db)
    draft = await service.refine(
        player,
        week_number=body.weekNumber,
        day_offset=body.dayOffset,
        title=body.title,
        workout_type=body.workoutType,
        planned_duration_min=body.plannedDurationMin,
        intensity_target=body.intensityTarget,
        structured_workout=body.structuredWorkout,
    )
    return _draft_envelope(draft)


@router.post("/lock", response_model=LockEnvelope)
async def lock_block(
    player: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> LockEnvelope:
    service = BlockGeneratorService(db)
    result = await service.lock(player)
    return LockEnvelope(
        data=LockData(
            blocksCreated=result.blocks_created,
            workoutsWritten=result.workouts_written,
            startDate=result.start_date.isoformat(),
            endDate=result.end_date.isoformat(),
        ),
        meta=ApiMeta(generatedAtUtc=_generated_at()),
        errors=[],
    )


@router.post("/discard", response_model=DiscardEnvelope)
async def discard_block(
    player: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> DiscardEnvelope:
    service = BlockGeneratorService(db)
    await service.discard(player)
    return DiscardEnvelope(
        data=DiscardData(discarded=True),
        meta=ApiMeta(generatedAtUtc=_generated_at()),
        errors=[],
    )
