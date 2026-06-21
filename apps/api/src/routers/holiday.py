"""Holiday pause/resume API (Batch 15).

Surfaces:
  GET  /api/v1/holiday        — list all windows (active + history)
  POST /api/v1/holiday/pause  — open a new holiday window (skips plan workouts)
  POST /api/v1/holiday/resume — close the active window (apply block continuation)
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import CurrentUser
from src.database import get_db
from src.services.holiday_pause import HolidayPauseService, HolidayWindow

router = APIRouter(prefix="/api/v1/holiday", tags=["holiday"])


def _generated_at() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class ApiError(BaseModel):
    code: str
    detail: str


class ApiMeta(BaseModel):
    generatedAtUtc: str


class WindowOut(BaseModel):
    startDate: str
    endDate: str
    pausedAtUtc: str
    resumedAtUtc: str | None
    isActive: bool


class HolidayData(BaseModel):
    windows: list[WindowOut]
    activeWindow: WindowOut | None


class HolidayEnvelope(BaseModel):
    data: HolidayData
    meta: ApiMeta
    errors: list[ApiError]


class PauseData(BaseModel):
    window: WindowOut
    skippedCount: int


class PauseEnvelope(BaseModel):
    data: PauseData
    meta: ApiMeta
    errors: list[ApiError]


class ResumeData(BaseModel):
    window: WindowOut
    continuationLabel: str
    regeneratedCount: int


class ResumeEnvelope(BaseModel):
    data: ResumeData
    meta: ApiMeta
    errors: list[ApiError]


class PauseInput(BaseModel):
    startDate: str
    endDate: str


def _window_out(w: HolidayWindow) -> WindowOut:
    return WindowOut(
        startDate=w.start_date.isoformat(),
        endDate=w.end_date.isoformat(),
        pausedAtUtc=w.paused_at_utc.isoformat(),
        resumedAtUtc=w.resumed_at_utc.isoformat() if w.resumed_at_utc else None,
        isActive=w.is_active,
    )


@router.get("", response_model=HolidayEnvelope)
async def get_holiday_windows(
    player: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> HolidayEnvelope:
    service = HolidayPauseService(db)
    windows = await service.get_windows(player)
    outs = [_window_out(w) for w in windows]
    active = next((o for o in reversed(outs) if o.isActive), None)
    return HolidayEnvelope(
        data=HolidayData(windows=outs, activeWindow=active),
        meta=ApiMeta(generatedAtUtc=_generated_at()),
        errors=[],
    )


@router.post("/pause", response_model=PauseEnvelope)
async def pause_plan(
    body: PauseInput,
    player: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> PauseEnvelope:
    from datetime import date

    service = HolidayPauseService(db)
    result = await service.pause(
        player,
        start_date=date.fromisoformat(body.startDate),
        end_date=date.fromisoformat(body.endDate),
    )
    return PauseEnvelope(
        data=PauseData(window=_window_out(result.window), skippedCount=result.skipped_count),
        meta=ApiMeta(generatedAtUtc=_generated_at()),
        errors=[],
    )


@router.post("/resume", response_model=ResumeEnvelope)
async def resume_plan(
    player: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> ResumeEnvelope:
    service = HolidayPauseService(db)
    result = await service.resume(player)
    return ResumeEnvelope(
        data=ResumeData(
            window=_window_out(result.window),
            continuationLabel=result.continuation_label,
            regeneratedCount=result.regenerated_count,
        ),
        meta=ApiMeta(generatedAtUtc=_generated_at()),
        errors=[],
    )
