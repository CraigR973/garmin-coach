"""Strength watching-brief API (Batch 19).

Read-only endpoint exposing the deterministic strength rollups computed by
``StrengthBriefService``.  Never writes to the database and never alters the
Green/Amber/Red verdict or recovery protocol (Decision #49 / #80).

  GET /api/v1/strength-brief  — rolling 4w / 12w brief + trend
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import CurrentUser
from src.database import get_db
from src.services.strength_brief import StrengthBriefResult, StrengthBriefService

router = APIRouter(prefix="/api/v1/strength-brief", tags=["strength-brief"])


def _generated_at() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class ApiError(BaseModel):
    code: str
    detail: str


class ApiMeta(BaseModel):
    generatedAtUtc: str


class WindowStatsOut(BaseModel):
    sessionCount: int
    totalDurationMin: int
    totalLoadProxy: float
    sessionsPerWeek: float


class StrengthSessionOut(BaseModel):
    activityId: str
    activityName: str
    activityType: str
    sessionDate: str
    durationMin: int | None
    trainingLoad: float | None


class StrengthBriefData(BaseModel):
    asOfDate: str
    window4w: WindowStatsOut
    window12w: WindowStatsOut
    recentSessions: list[StrengthSessionOut]
    trend: str
    trendReason: str


class StrengthBriefEnvelope(BaseModel):
    data: StrengthBriefData
    meta: ApiMeta
    errors: list[ApiError]


def _serialize(result: StrengthBriefResult) -> StrengthBriefData:
    return StrengthBriefData(
        asOfDate=result.as_of_date.isoformat(),
        window4w=WindowStatsOut(
            sessionCount=result.window_4w.session_count,
            totalDurationMin=result.window_4w.total_duration_min,
            totalLoadProxy=result.window_4w.total_load_proxy,
            sessionsPerWeek=result.window_4w.sessions_per_week,
        ),
        window12w=WindowStatsOut(
            sessionCount=result.window_12w.session_count,
            totalDurationMin=result.window_12w.total_duration_min,
            totalLoadProxy=result.window_12w.total_load_proxy,
            sessionsPerWeek=result.window_12w.sessions_per_week,
        ),
        recentSessions=[
            StrengthSessionOut(
                activityId=str(s.activity_id),
                activityName=s.activity_name,
                activityType=s.activity_type,
                sessionDate=s.session_date.isoformat(),
                durationMin=s.duration_min,
                trainingLoad=s.training_load,
            )
            for s in result.recent_sessions
        ],
        trend=result.trend,
        trendReason=result.trend_reason,
    )


@router.get("", response_model=StrengthBriefEnvelope)
async def get_strength_brief(
    player: CurrentUser,
    as_of: date | None = None,
    db: AsyncSession = Depends(get_db),
) -> StrengthBriefEnvelope:
    service = StrengthBriefService(db)
    result = await service.brief(player, as_of=as_of)
    return StrengthBriefEnvelope(
        data=_serialize(result),
        meta=ApiMeta(generatedAtUtc=_generated_at()),
        errors=[],
    )
