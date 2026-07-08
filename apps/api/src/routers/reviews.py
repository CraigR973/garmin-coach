"""Weekly & monthly deep-review API (Batch 20).

Read-only previews of the deterministic rollup packet, plus a ``/run`` endpoint
that generates the narrative through the Claude boundary and records it to the
``analyses`` audit log. ``GET`` previews never write (#71); ``POST /run`` is
idempotent per period.

  GET  /api/v1/reviews/{period}      — rollup summary + latest stored narrative
  POST /api/v1/reviews/{period}/run  — generate + store the narrative

``{period}`` is ``weekly`` or ``monthly``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import CurrentUser
from src.database import get_db
from src.models.coaching import Analysis
from src.models.profile import Profile
from src.routers.feedback import FeedbackOut, serialize_feedback
from src.services.feedback import FeedbackService
from src.services.reviews import (
    VALID_PERIODS,
    ReviewError,
    ReviewPreview,
    ReviewService,
    rollup_packet,
)

router = APIRouter(prefix="/api/v1/reviews", tags=["reviews"])


def _generated_at() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class ApiError(BaseModel):
    code: str
    detail: str


class ApiMeta(BaseModel):
    generatedAtUtc: str


class StrengthSummary(BaseModel):
    trend: str
    trendReason: str
    sessions4w: int
    sessionsPerWeek4w: float
    sessions12w: int
    sourceState: str
    zeroInterpretation: str | None


class InsightSummary(BaseModel):
    ftpDriftStatus: str
    earlyWarningStatus: str
    earlyWarningFired: bool


class StoredReview(BaseModel):
    analysisId: str
    generatedAtUtc: str
    modelName: str | None
    promptVersion: str
    markdown: str
    feedback: FeedbackOut | None = None


class ReviewData(BaseModel):
    period: str
    periodStart: str
    periodEnd: str
    dayCount: int
    rollup: dict[str, Any]
    strength: StrengthSummary
    insights: InsightSummary
    review: StoredReview | None


class ReviewEnvelope(BaseModel):
    data: ReviewData
    meta: ApiMeta
    errors: list[ApiError]


def _stored_review(analysis: Analysis | None, feedback: FeedbackOut | None) -> StoredReview | None:
    if analysis is None:
        return None
    return StoredReview(
        analysisId=str(analysis.id),
        generatedAtUtc=analysis.generated_at_utc.isoformat() + "Z",
        modelName=analysis.model_name,
        promptVersion=analysis.prompt_version,
        markdown=analysis.output_markdown,
        feedback=feedback,
    )


async def _review_feedback(
    db: AsyncSession, player: Profile, analysis: Analysis | None
) -> FeedbackOut | None:
    if analysis is None:
        return None
    rows = await FeedbackService(db).feedback_for_analyses(player.id, [analysis.id])
    row = rows.get(analysis.id)
    return serialize_feedback(row) if row is not None else None


def _data(
    preview: ReviewPreview,
    review: Analysis | None,
    review_feedback: FeedbackOut | None = None,
) -> ReviewData:
    return ReviewData(
        period=preview.period,
        periodStart=preview.period_start.isoformat(),
        periodEnd=preview.period_end.isoformat(),
        dayCount=preview.rollup.day_count,
        rollup=rollup_packet(preview.rollup),
        strength=StrengthSummary(
            trend=preview.strength_brief.trend,
            trendReason=preview.strength_brief.trend_reason,
            sessions4w=preview.strength_brief.window_4w.session_count,
            sessionsPerWeek4w=preview.strength_brief.window_4w.sessions_per_week,
            sessions12w=preview.strength_brief.window_12w.session_count,
            sourceState=(
                "tracked_strength_activity_present"
                if preview.strength_brief.window_12w.session_count > 0
                else "no_tracked_strength_activity"
            ),
            zeroInterpretation=(
                "No tracked strength activities were found in the 12-week lookback."
                if preview.strength_brief.window_12w.session_count == 0
                else None
            ),
        ),
        insights=InsightSummary(
            ftpDriftStatus=preview.ftp_drift.status,
            earlyWarningStatus=preview.early_warning.status,
            earlyWarningFired=preview.early_warning.fired,
        ),
        review=_stored_review(review, review_feedback),
    )


def _validate_period(period: str) -> str:
    if period not in VALID_PERIODS:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown review period '{period}'. Use one of: {', '.join(VALID_PERIODS)}.",
        )
    return period


@router.get("/{period}", response_model=ReviewEnvelope)
async def get_review(
    period: str,
    player: CurrentUser,
    as_of: date | None = None,
    db: AsyncSession = Depends(get_db),
) -> ReviewEnvelope:
    _validate_period(period)
    service = ReviewService(db)
    preview = await service.preview(player, period, as_of=as_of)
    feedback = await _review_feedback(db, player, preview.latest_review)
    return ReviewEnvelope(
        data=_data(preview, preview.latest_review, feedback),
        meta=ApiMeta(generatedAtUtc=_generated_at()),
        errors=[],
    )


@router.post("/{period}/run", response_model=ReviewEnvelope)
async def run_review(
    period: str,
    player: CurrentUser,
    as_of: date | None = None,
    force: bool = False,
    db: AsyncSession = Depends(get_db),
) -> ReviewEnvelope:
    _validate_period(period)
    service = ReviewService(db)
    try:
        result = await service.run(player, period, as_of=as_of, force=force)
    except ReviewError as exc:
        return ReviewEnvelope(
            data=_data(await service.preview(player, period, as_of=as_of), None),
            meta=ApiMeta(generatedAtUtc=_generated_at()),
            errors=[ApiError(code="review_generation_failed", detail=str(exc))],
        )
    feedback = await _review_feedback(db, player, result.review)
    return ReviewEnvelope(
        data=_data(result.preview, result.review, feedback),
        meta=ApiMeta(generatedAtUtc=_generated_at()),
        errors=[],
    )
