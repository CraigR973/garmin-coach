"""Walking brief API (Batch 41)."""

from __future__ import annotations

from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import CurrentUser
from src.database import get_db
from src.services.walking_brief import WalkingBriefResult, WalkingBriefService

router = APIRouter(prefix="/api/v1/walking-brief", tags=["walking-brief"])


def _generated_at() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class ApiError(BaseModel):
    code: str
    detail: str


class ApiMeta(BaseModel):
    generatedAtUtc: str


class WalkingWindowStatsOut(BaseModel):
    sessionCount: int
    totalDistanceM: float
    totalDurationMin: int
    sessionsPerWeek: float


class WalkingSessionOut(BaseModel):
    activityId: str
    activityName: str
    activityType: str
    sessionDate: str
    durationMin: int | None
    distanceM: float | None


class WalkingBriefData(BaseModel):
    asOfDate: str
    window4w: WalkingWindowStatsOut
    window12w: WalkingWindowStatsOut
    recentSessions: list[WalkingSessionOut]
    trend: str
    trendReason: str


class WalkingBriefEnvelope(BaseModel):
    data: WalkingBriefData
    meta: ApiMeta
    errors: list[ApiError]


def _serialize(result: WalkingBriefResult) -> WalkingBriefData:
    return WalkingBriefData(
        asOfDate=result.as_of_date.isoformat(),
        window4w=WalkingWindowStatsOut(
            sessionCount=result.window_4w.session_count,
            totalDistanceM=result.window_4w.total_distance_m,
            totalDurationMin=result.window_4w.total_duration_min,
            sessionsPerWeek=result.window_4w.sessions_per_week,
        ),
        window12w=WalkingWindowStatsOut(
            sessionCount=result.window_12w.session_count,
            totalDistanceM=result.window_12w.total_distance_m,
            totalDurationMin=result.window_12w.total_duration_min,
            sessionsPerWeek=result.window_12w.sessions_per_week,
        ),
        recentSessions=[
            WalkingSessionOut(
                activityId=str(session.activity_id),
                activityName=session.activity_name,
                activityType=session.activity_type,
                sessionDate=session.session_date.isoformat(),
                durationMin=session.duration_min,
                distanceM=session.distance_m,
            )
            for session in result.recent_sessions
        ],
        trend=result.trend,
        trendReason=result.trend_reason,
    )


@router.get("", response_model=WalkingBriefEnvelope)
async def get_walking_brief(
    player: CurrentUser,
    as_of: date | None = None,
    db: AsyncSession = Depends(get_db),
) -> WalkingBriefEnvelope:
    result = await WalkingBriefService(db).brief(player, as_of=as_of)
    return WalkingBriefEnvelope(
        data=_serialize(result),
        meta=ApiMeta(generatedAtUtc=_generated_at()),
        errors=[],
    )
