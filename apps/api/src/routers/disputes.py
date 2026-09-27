"""Record Mark's disputes (Batch 274).

  POST /api/v1/disputes/figures   — contest a derived figure on a read
  POST /api/v1/disputes/verdicts  — dissent from a day's verdict
  GET  /api/v1/disputes           — his disputes over a date range

A contest snapshots the working the app showed for the figure, read from the stored
read on the server, and tells Craig. A dissent records the verdict as it stood.
Neither changes any figure, verdict, VO2 block or chronic cluster.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import CurrentUser
from src.database import get_db
from src.models.coaching import Dispute
from src.services.disputes import MAX_REASON_LENGTH, DisputeService

router = APIRouter(prefix="/api/v1/disputes", tags=["disputes"])

MAX_RANGE_DAYS = 400


def _generated_at() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class ApiError(BaseModel):
    code: str
    detail: str


class ApiMeta(BaseModel):
    generatedAtUtc: str


class FigureContestInput(BaseModel):
    analysisId: uuid.UUID
    figure: str = Field(..., min_length=1, max_length=120)
    reason: str = Field(..., max_length=MAX_REASON_LENGTH)


class VerdictDissentInput(BaseModel):
    subjectDate: date
    reason: str = Field(..., max_length=MAX_REASON_LENGTH)


class DisputeOut(BaseModel):
    id: str
    kind: str
    analysisId: str | None
    subjectDate: str
    figure: str | None
    label: str | None
    verdict: str | None
    reason: str
    createdAtUtc: str


class DisputeEnvelope(BaseModel):
    data: DisputeOut
    meta: ApiMeta
    errors: list[ApiError]


class DisputeListEnvelope(BaseModel):
    data: list[DisputeOut]
    meta: ApiMeta
    errors: list[ApiError]


def serialize_dispute(row: Dispute) -> DisputeOut:
    snapshot = row.snapshot if isinstance(row.snapshot, dict) else {}
    label = snapshot.get("label")
    verdict = snapshot.get("status")
    return DisputeOut(
        id=str(row.id),
        kind=row.kind,
        analysisId=str(row.analysis_id) if row.analysis_id else None,
        subjectDate=row.subject_date.isoformat(),
        figure=row.figure,
        label=label if isinstance(label, str) else None,
        verdict=verdict if isinstance(verdict, str) else None,
        reason=row.reason,
        createdAtUtc=row.created_at.isoformat() + "Z",
    )


def _envelope(row: Dispute) -> DisputeEnvelope:
    return DisputeEnvelope(
        data=serialize_dispute(row), meta=ApiMeta(generatedAtUtc=_generated_at()), errors=[]
    )


@router.post("/figures", response_model=DisputeEnvelope, status_code=status.HTTP_201_CREATED)
async def contest_figure(
    body: FigureContestInput,
    player: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> DisputeEnvelope:
    row = await DisputeService(db).contest_figure(
        player, analysis_id=body.analysisId, figure=body.figure, reason=body.reason
    )
    return _envelope(row)


@router.post("/verdicts", response_model=DisputeEnvelope, status_code=status.HTTP_201_CREATED)
async def dissent_from_verdict(
    body: VerdictDissentInput,
    player: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> DisputeEnvelope:
    row = await DisputeService(db).dissent_from_verdict(
        player, subject_date=body.subjectDate, reason=body.reason
    )
    return _envelope(row)


@router.get("", response_model=DisputeListEnvelope)
async def list_disputes(
    player: CurrentUser,
    start: date = Query(...),
    end: date = Query(...),
    db: AsyncSession = Depends(get_db),
) -> DisputeListEnvelope:
    if end < start or end - start > timedelta(days=MAX_RANGE_DAYS):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Ask for a range of at most {MAX_RANGE_DAYS} days.",
        )
    rows = await DisputeService(db).between(player.id, start, end)
    return DisputeListEnvelope(
        data=[serialize_dispute(row) for row in rows],
        meta=ApiMeta(generatedAtUtc=_generated_at()),
        errors=[],
    )
