"""Breathwork consistency brief API (Batch 42)."""

from __future__ import annotations

from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import CurrentUser
from src.database import get_db
from src.services.breathwork_brief import BreathworkBriefResult, BreathworkBriefService

router = APIRouter(prefix="/api/v1/breathwork-brief", tags=["breathwork-brief"])


def _generated_at() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class ApiError(BaseModel):
    code: str
    detail: str


class ApiMeta(BaseModel):
    generatedAtUtc: str


class BreathworkWindowStatsOut(BaseModel):
    sessionCount: int
    totalDurationMin: int
    sessionsPerWeek: float


class BreathworkSessionOut(BaseModel):
    activityId: str
    activityName: str
    activityType: str
    sessionDate: str
    durationMin: int | None


class BreathworkBriefData(BaseModel):
    asOfDate: str
    window4w: BreathworkWindowStatsOut
    window12w: BreathworkWindowStatsOut
    recentSessions: list[BreathworkSessionOut]
    trend: str
    trendReason: str


class BreathworkBriefEnvelope(BaseModel):
    data: BreathworkBriefData
    meta: ApiMeta
    errors: list[ApiError]


def _serialize(result: BreathworkBriefResult) -> BreathworkBriefData:
    return BreathworkBriefData(
        asOfDate=result.as_of_date.isoformat(),
        window4w=BreathworkWindowStatsOut(
            sessionCount=result.window_4w.session_count,
            totalDurationMin=result.window_4w.total_duration_min,
            sessionsPerWeek=result.window_4w.sessions_per_week,
        ),
        window12w=BreathworkWindowStatsOut(
            sessionCount=result.window_12w.session_count,
            totalDurationMin=result.window_12w.total_duration_min,
            sessionsPerWeek=result.window_12w.sessions_per_week,
        ),
        recentSessions=[
            BreathworkSessionOut(
                activityId=str(session.activity_id),
                activityName=session.activity_name,
                activityType=session.activity_type,
                sessionDate=session.session_date.isoformat(),
                durationMin=session.duration_min,
            )
            for session in result.recent_sessions
        ],
        trend=result.trend,
        trendReason=result.trend_reason,
    )


@router.get("", response_model=BreathworkBriefEnvelope)
async def get_breathwork_brief(
    player: CurrentUser,
    as_of: date | None = None,
    db: AsyncSession = Depends(get_db),
) -> BreathworkBriefEnvelope:
    result = await BreathworkBriefService(db).brief(player, as_of=as_of)
    return BreathworkBriefEnvelope(
        data=_serialize(result),
        meta=ApiMeta(generatedAtUtc=_generated_at()),
        errors=[],
    )
