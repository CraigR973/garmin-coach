"""Overnight bedroom chart read API (Batch 31).

``GET /api/v1/bedroom/overnight`` is a **pure DB read** (it never writes) that
joins, for one overnight window, the room-temperature curve
(``temperature_readings``), what the fan actually did (``fan_state_readings``,
Batch 31), and the night's sleep — so the ``/bedroom`` chart can show whether the
room cost Mark sleep and whether the autopilot is helping. Kept off
``/api/v1/daily-loop`` deliberately: it is a heavy detail read (Batch 24 ethos).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from datetime import date as date_type
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import CurrentUser
from src.database import get_db
from src.models.coaching import FanStateReading, Sleep, TemperatureReading
from src.services.bedroom_overnight import (
    THRESHOLD_CRITICAL_C,
    THRESHOLD_ON_C,
    default_night,
    extract_hypnogram,
    iso_z,
    night_window,
    recent_nights,
    sleep_calendar_date,
    summarize_overnight,
)

router = APIRouter(prefix="/api/v1/bedroom", tags=["bedroom"])

# How far back the night pager looks for nights with data.
PAGER_DAYS = 14


class TemperaturePoint(BaseModel):
    t: str
    c: float


class FanPoint(BaseModel):
    t: str
    on: bool | None = None
    speed: int | None = None
    action: str
    reason: str | None = None
    observedTempC: float | None = None
    autoEnabled: bool


class SleepStageSpan(BaseModel):
    start: str
    end: str
    stage: str


class OvernightSleep(BaseModel):
    start: str | None = None
    end: str | None = None
    score: int | None = None
    ageAdjustedScore: int | None = None
    durationSec: int | None = None
    awakeSec: int | None = None
    restlessMoments: int | None = None
    stages: list[SleepStageSpan] = Field(default_factory=list)


class OvernightThresholds(BaseModel):
    onC: float
    criticalC: float


class OvernightSummaryOut(BaseModel):
    minTempC: float | None = None
    maxTempC: float | None = None
    fanRanMinutes: int
    peakSpeed: int | None = None
    warningMinutes: int
    criticalMinutes: int
    roomVerdict: str


class OvernightData(BaseModel):
    night: str
    timezone: str
    windowStartUtc: str
    windowEndUtc: str
    thresholds: OvernightThresholds
    temperature: list[TemperaturePoint]
    fan: list[FanPoint]
    sleep: OvernightSleep | None = None
    summary: OvernightSummaryOut | None = None
    nights: list[str]


class OvernightMeta(BaseModel):
    generatedAtUtc: str


class OvernightEnvelope(BaseModel):
    data: OvernightData
    meta: OvernightMeta
    errors: list[str] = Field(default_factory=list)


def _zone(timezone: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@router.get("/overnight", response_model=OvernightEnvelope)
async def get_overnight(
    player: CurrentUser,
    db: AsyncSession = Depends(get_db),
    date: str | None = Query(default=None, description="Night start date YYYY-MM-DD"),
) -> OvernightEnvelope:
    tz = _zone(player.timezone)
    now_local = datetime.now(tz)
    night = _resolve_night(date, now_local)

    start_utc, end_utc = night_window(night, tz)

    temp_rows = (
        (
            await db.execute(
                select(TemperatureReading)
                .where(
                    TemperatureReading.user_id == player.id,
                    TemperatureReading.captured_at_utc >= start_utc,
                    TemperatureReading.captured_at_utc < end_utc,
                )
                .order_by(TemperatureReading.captured_at_utc)
            )
        )
        .scalars()
        .all()
    )
    fan_rows = (
        (
            await db.execute(
                select(FanStateReading)
                .where(
                    FanStateReading.user_id == player.id,
                    FanStateReading.captured_at_utc >= start_utc,
                    FanStateReading.captured_at_utc < end_utc,
                )
                .order_by(FanStateReading.captured_at_utc)
            )
        )
        .scalars()
        .all()
    )
    sleep_row = await db.scalar(
        select(Sleep).where(
            Sleep.user_id == player.id,
            Sleep.calendar_date == sleep_calendar_date(night),
        )
    )

    temperature = [
        TemperaturePoint(t=iso_z(r.captured_at_utc), c=r.temperature_c) for r in temp_rows
    ]
    fan = [
        FanPoint(
            t=iso_z(r.captured_at_utc),
            on=r.fan_on,
            speed=r.fan_speed,
            action=r.action,
            reason=r.reason,
            observedTempC=r.observed_temp_c,
            autoEnabled=r.auto_enabled,
        )
        for r in fan_rows
    ]

    summary_core = summarize_overnight(
        [r.temperature_c for r in temp_rows],
        [(r.fan_on, r.fan_speed) for r in fan_rows],
    )
    summary = (
        OvernightSummaryOut(
            minTempC=summary_core.min_temp_c,
            maxTempC=summary_core.max_temp_c,
            fanRanMinutes=summary_core.fan_ran_minutes,
            peakSpeed=summary_core.peak_speed,
            warningMinutes=summary_core.warning_minutes,
            criticalMinutes=summary_core.critical_minutes,
            roomVerdict=summary_core.room_verdict,
        )
        if temperature or fan
        else None
    )

    return OvernightEnvelope(
        data=OvernightData(
            night=night.isoformat(),
            timezone=player.timezone,
            windowStartUtc=iso_z(start_utc),
            windowEndUtc=iso_z(end_utc),
            thresholds=OvernightThresholds(onC=THRESHOLD_ON_C, criticalC=THRESHOLD_CRITICAL_C),
            temperature=temperature,
            fan=fan,
            sleep=_serialize_sleep(sleep_row),
            summary=summary,
            nights=await _recent_nights(db, player.id, tz, now_local, viewed=night),
        ),
        meta=OvernightMeta(generatedAtUtc=_now()),
    )


def _resolve_night(raw: str | None, now_local: datetime) -> date_type:
    if raw is None:
        return default_night(now_local)
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="date must be YYYY-MM-DD",
        ) from exc


def _serialize_sleep(row: Sleep | None) -> OvernightSleep | None:
    if row is None:
        return None
    return OvernightSleep(
        start=iso_z(row.sleep_start_utc) if row.sleep_start_utc else None,
        end=iso_z(row.sleep_end_utc) if row.sleep_end_utc else None,
        score=row.score,
        ageAdjustedScore=row.age_adjusted_score,
        durationSec=row.duration_sec,
        awakeSec=row.awake_sleep_sec,
        restlessMoments=row.restless_moments_count,
        stages=[SleepStageSpan(**span) for span in extract_hypnogram(row.raw_payload)],
    )


async def _recent_nights(
    db: AsyncSession,
    user_id: uuid.UUID,
    tz: ZoneInfo,
    now_local: datetime,
    *,
    viewed: date_type,
) -> list[str]:
    """Recent nights with temp or fan data (newest first), always incl. the viewed one."""
    horizon = now_local.astimezone(UTC).replace(tzinfo=None) - timedelta(days=PAGER_DAYS)
    temp_ts = (
        (
            await db.execute(
                select(TemperatureReading.captured_at_utc).where(
                    TemperatureReading.user_id == user_id,
                    TemperatureReading.captured_at_utc >= horizon,
                )
            )
        )
        .scalars()
        .all()
    )
    fan_ts = (
        (
            await db.execute(
                select(FanStateReading.captured_at_utc).where(
                    FanStateReading.user_id == user_id,
                    FanStateReading.captured_at_utc >= horizon,
                )
            )
        )
        .scalars()
        .all()
    )
    local = [ts.replace(tzinfo=UTC).astimezone(tz) for ts in (*temp_ts, *fan_ts)]
    nights = set(recent_nights(local, limit=PAGER_DAYS))
    nights.add(viewed)
    return [n.isoformat() for n in sorted(nights, reverse=True)]
