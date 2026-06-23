"""Year-on-year & seasonal trends API (Batch 21).

Read-only previews of the deterministic seasonal/period windows and the
year-on-year comparison, plus a ``/narrative/run`` endpoint that summarises the
comparison through the Batch 20 Claude boundary and records it to ``analyses``.
``GET`` previews never write (#71); ``POST`` records and is idempotent per
window, and reports "insufficient history" deterministically until a prior-year
window exists.

  GET  /api/v1/trends/seasonal       — recent per-window summary stats
  GET  /api/v1/trends/year-on-year   — same-period-vs-prior-year deltas
  GET  /api/v1/trends/narrative      — comparison packet + latest stored narrative
  POST /api/v1/trends/narrative/run  — generate + store the narrative

``bucket`` is ``month`` or ``season``.
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
from src.services.trends import (
    VALID_BUCKETS,
    ReviewError,
    TrendsService,
    window_json,
    year_on_year_json,
)

router = APIRouter(prefix="/api/v1/trends", tags=["trends"])


def _generated_at() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class ApiError(BaseModel):
    code: str
    detail: str


class ApiMeta(BaseModel):
    generatedAtUtc: str


class SeasonalData(BaseModel):
    bucket: str
    windows: list[dict[str, Any]]


class SeasonalEnvelope(BaseModel):
    data: SeasonalData
    meta: ApiMeta
    errors: list[ApiError]


class YearOnYearEnvelope(BaseModel):
    data: dict[str, Any]
    meta: ApiMeta
    errors: list[ApiError]


class StoredNarrative(BaseModel):
    generatedAtUtc: str
    modelName: str | None
    promptVersion: str
    markdown: str


class NarrativeData(BaseModel):
    bucket: str
    targetKey: str
    subjectDate: str
    yearOnYear: dict[str, Any]
    recentWindows: list[dict[str, Any]]
    status: str
    narrative: StoredNarrative | None


class NarrativeEnvelope(BaseModel):
    data: NarrativeData
    meta: ApiMeta
    errors: list[ApiError]


def _validate_bucket(bucket: str) -> str:
    if bucket not in VALID_BUCKETS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown trend bucket '{bucket}'. Use one of: {', '.join(VALID_BUCKETS)}.",
        )
    return bucket


def _stored_narrative(analysis: Analysis | None) -> StoredNarrative | None:
    if analysis is None:
        return None
    return StoredNarrative(
        generatedAtUtc=analysis.generated_at_utc.isoformat() + "Z",
        modelName=analysis.model_name,
        promptVersion=analysis.prompt_version,
        markdown=analysis.output_markdown,
    )


@router.get("/seasonal", response_model=SeasonalEnvelope)
async def get_seasonal(
    player: CurrentUser,
    bucket: str = "month",
    as_of: date | None = None,
    db: AsyncSession = Depends(get_db),
) -> SeasonalEnvelope:
    _validate_bucket(bucket)
    service = TrendsService(db)
    result = await service.seasonal(player, bucket=bucket, as_of=as_of)
    return SeasonalEnvelope(
        data=SeasonalData(
            bucket=result.bucket,
            windows=[window_json(w) for w in result.windows],
        ),
        meta=ApiMeta(generatedAtUtc=_generated_at()),
        errors=[],
    )


@router.get("/year-on-year", response_model=YearOnYearEnvelope)
async def get_year_on_year(
    player: CurrentUser,
    bucket: str = "month",
    as_of: date | None = None,
    db: AsyncSession = Depends(get_db),
) -> YearOnYearEnvelope:
    _validate_bucket(bucket)
    service = TrendsService(db)
    comparison = await service.year_on_year(player, bucket=bucket, as_of=as_of)
    return YearOnYearEnvelope(
        data=year_on_year_json(comparison),
        meta=ApiMeta(generatedAtUtc=_generated_at()),
        errors=[],
    )


def _narrative_data(
    bucket: str,
    target_key: str,
    subject_date: date,
    comparison_json: dict[str, Any],
    recent_windows: list[dict[str, Any]],
    status: str,
    narrative: Analysis | None,
) -> NarrativeData:
    return NarrativeData(
        bucket=bucket,
        targetKey=target_key,
        subjectDate=subject_date.isoformat(),
        yearOnYear=comparison_json,
        recentWindows=recent_windows,
        status=status,
        narrative=_stored_narrative(narrative),
    )


@router.get("/narrative", response_model=NarrativeEnvelope)
async def get_narrative(
    player: CurrentUser,
    bucket: str = "season",
    as_of: date | None = None,
    db: AsyncSession = Depends(get_db),
) -> NarrativeEnvelope:
    _validate_bucket(bucket)
    service = TrendsService(db)
    preview = await service.narrative_preview(player, bucket=bucket, as_of=as_of)
    return NarrativeEnvelope(
        data=_narrative_data(
            preview.bucket,
            preview.target_key,
            preview.subject_date,
            year_on_year_json(preview.comparison),
            [window_json(w) for w in preview.windows[-6:]],
            "ready" if preview.comparison.status == "ok" else preview.comparison.status,
            preview.latest_narrative,
        ),
        meta=ApiMeta(generatedAtUtc=_generated_at()),
        errors=[],
    )


@router.post("/narrative/run", response_model=NarrativeEnvelope)
async def run_narrative(
    player: CurrentUser,
    bucket: str = "season",
    as_of: date | None = None,
    force: bool = False,
    db: AsyncSession = Depends(get_db),
) -> NarrativeEnvelope:
    _validate_bucket(bucket)
    service = TrendsService(db)
    errors: list[ApiError] = []
    try:
        result = await service.narrative_run(player, bucket=bucket, as_of=as_of, force=force)
        preview = result.preview
        status = result.status
        narrative = result.narrative
    except ReviewError as exc:
        preview = await service.narrative_preview(player, bucket=bucket, as_of=as_of)
        status = "generation_failed"
        narrative = None
        errors.append(ApiError(code="trend_generation_failed", detail=str(exc)))

    return NarrativeEnvelope(
        data=_narrative_data(
            preview.bucket,
            preview.target_key,
            preview.subject_date,
            year_on_year_json(preview.comparison),
            [window_json(w) for w in preview.windows[-6:]],
            status,
            narrative,
        ),
        meta=ApiMeta(generatedAtUtc=_generated_at()),
        errors=errors,
    )
