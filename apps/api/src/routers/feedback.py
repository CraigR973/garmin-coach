"""Rate & correct any AI summary — feedback API (Batch 64).

  PUT /api/v1/analyses/{analysis_id}/feedback   — upsert this user's feedback

Every AI summary is one ``analyses`` row, so a single endpoint keyed to
``analysis_id`` covers the verdict, post-session reads, and reviews. The write is
user-scoped: 404 when the analysis does not exist, 403 when it belongs to another
profile. One row per ``(user, analysis)`` — repeat calls upsert (Decision #137).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import CurrentUser
from src.database import get_db
from src.models.coaching import Feedback
from src.services.feedback import FeedbackService

router = APIRouter(prefix="/api/v1/analyses", tags=["feedback"])


def _generated_at() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class ApiError(BaseModel):
    code: str
    detail: str


class ApiMeta(BaseModel):
    generatedAtUtc: str


class FeedbackInput(BaseModel):
    kind: str = Field(..., description="'summary' (accuracy) or 'suggestion' (agreement)")
    rating: str = Field(..., description="A short per-axis token")
    correctionText: str | None = Field(default=None, max_length=2000)
    reasonTags: list[str] = Field(
        default_factory=list, description="One-tap, kind-scoped 'what's off' reasons"
    )


class FeedbackOut(BaseModel):
    id: str
    analysisId: str
    kind: str
    rating: str
    correctionText: str | None
    reasonTags: list[str]
    createdAtUtc: str


class FeedbackEnvelope(BaseModel):
    data: FeedbackOut
    meta: ApiMeta
    errors: list[ApiError]


def serialize_feedback(row: Feedback) -> FeedbackOut:
    return FeedbackOut(
        id=str(row.id),
        analysisId=str(row.analysis_id),
        kind=row.kind,
        rating=row.rating,
        correctionText=row.correction_text,
        reasonTags=list(row.reason_tags or []),
        createdAtUtc=row.created_utc.isoformat() + "Z",
    )


@router.put("/{analysis_id}/feedback", response_model=FeedbackEnvelope)
async def upsert_feedback(
    analysis_id: uuid.UUID,
    payload: FeedbackInput,
    player: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> FeedbackEnvelope:
    service = FeedbackService(db)
    row = await service.upsert(
        player,
        analysis_id,
        kind=payload.kind,
        rating=payload.rating,
        correction_text=payload.correctionText,
        reason_tags=payload.reasonTags,
    )
    return FeedbackEnvelope(
        data=serialize_feedback(row),
        meta=ApiMeta(generatedAtUtc=_generated_at()),
        errors=[],
    )
