"""Monitoring + insight API (Batch 17).

Read-only previews of the three deterministic insight engines, plus a ``/run``
endpoint that records the actionable findings to the ``analyses`` audit log:

  GET  /api/v1/insights/ftp-drift     — FTP drift from ride efficiency (17.1)
  GET  /api/v1/insights/early-warning — degrading-trend alert before a Red (17.2)
  GET  /api/v1/insights/drivers       — strongest movers of sleep/recovery (17.3)
  POST /api/v1/insights/run           — compute all three + audit the findings
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import CurrentUser
from src.database import get_db
from src.services.insights import (
    DriversReport,
    EarlyWarningResult,
    FtpDriftResult,
    InsightsService,
)

router = APIRouter(prefix="/api/v1/insights", tags=["insights"])


def _generated_at() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class ApiError(BaseModel):
    code: str
    detail: str


class ApiMeta(BaseModel):
    generatedAtUtc: str


class FtpDriftData(BaseModel):
    status: str
    sampleCount: int
    windowStart: str | None
    windowEnd: str | None
    baselineEf: float | None
    recentEf: float | None
    pctChange: float | None
    currentFtpWatts: int
    suggestedFtpWatts: int | None
    reasons: list[str]


class FtpDriftEnvelope(BaseModel):
    data: FtpDriftData
    meta: ApiMeta
    errors: list[ApiError]


class EarlyWarningData(BaseModel):
    status: str
    fired: bool
    windowStart: str | None
    windowEnd: str | None
    hrvSlope: float | None
    sleepSlope: float | None
    readinessSlope: float | None
    degradingMetrics: list[str]
    reasons: list[str]


class EarlyWarningEnvelope(BaseModel):
    data: EarlyWarningData
    meta: ApiMeta
    errors: list[ApiError]


class DriverOut(BaseModel):
    driver: str
    coefficient: float
    direction: str
    sampleCount: int
    summary: str | None = None


class DriversData(BaseModel):
    recordCount: int
    windowStart: str | None
    windowEnd: str | None
    outcomes: dict[str, list[DriverOut]]


class DriversEnvelope(BaseModel):
    data: DriversData
    meta: ApiMeta
    errors: list[ApiError]


class RunData(BaseModel):
    ftpDrift: FtpDriftData
    earlyWarning: EarlyWarningData
    drivers: DriversData
    recorded: list[str]


class RunEnvelope(BaseModel):
    data: RunData
    meta: ApiMeta
    errors: list[ApiError]


def _ftp_data(drift: FtpDriftResult) -> FtpDriftData:
    return FtpDriftData(
        status=drift.status,
        sampleCount=drift.sample_count,
        windowStart=drift.window_start.isoformat() if drift.window_start else None,
        windowEnd=drift.window_end.isoformat() if drift.window_end else None,
        baselineEf=drift.baseline_ef,
        recentEf=drift.recent_ef,
        pctChange=drift.pct_change,
        currentFtpWatts=drift.current_ftp_watts,
        suggestedFtpWatts=drift.suggested_ftp_watts,
        reasons=drift.reasons,
    )


def _warning_data(warning: EarlyWarningResult) -> EarlyWarningData:
    return EarlyWarningData(
        status=warning.status,
        fired=warning.fired,
        windowStart=warning.window_start.isoformat() if warning.window_start else None,
        windowEnd=warning.window_end.isoformat() if warning.window_end else None,
        hrvSlope=warning.hrv_slope,
        sleepSlope=warning.sleep_slope,
        readinessSlope=warning.readiness_slope,
        degradingMetrics=warning.degrading_metrics,
        reasons=warning.reasons,
    )


def _drivers_data(report: DriversReport) -> DriversData:
    return DriversData(
        recordCount=report.record_count,
        windowStart=report.window_start.isoformat() if report.window_start else None,
        windowEnd=report.window_end.isoformat() if report.window_end else None,
        outcomes={
            outcome: [
                DriverOut(
                    driver=c.driver,
                    coefficient=c.coefficient,
                    direction=c.direction,
                    sampleCount=c.sample_count,
                    summary=c.summary,
                )
                for c in correlations
            ]
            for outcome, correlations in report.outcomes.items()
        },
    )


def _meta() -> ApiMeta:
    return ApiMeta(generatedAtUtc=_generated_at())


@router.get("/ftp-drift", response_model=FtpDriftEnvelope)
async def get_ftp_drift(
    player: CurrentUser,
    as_of: date | None = None,
    db: AsyncSession = Depends(get_db),
) -> FtpDriftEnvelope:
    service = InsightsService(db)
    drift = await service.ftp_drift(player, as_of=as_of)
    return FtpDriftEnvelope(data=_ftp_data(drift), meta=_meta(), errors=[])


@router.get("/early-warning", response_model=EarlyWarningEnvelope)
async def get_early_warning(
    player: CurrentUser,
    as_of: date | None = None,
    db: AsyncSession = Depends(get_db),
) -> EarlyWarningEnvelope:
    service = InsightsService(db)
    warning = await service.early_warning(player, as_of=as_of)
    return EarlyWarningEnvelope(data=_warning_data(warning), meta=_meta(), errors=[])


@router.get("/drivers", response_model=DriversEnvelope)
async def get_drivers(
    player: CurrentUser,
    as_of: date | None = None,
    db: AsyncSession = Depends(get_db),
) -> DriversEnvelope:
    service = InsightsService(db)
    report = await service.drivers(player, as_of=as_of)
    return DriversEnvelope(data=_drivers_data(report), meta=_meta(), errors=[])


@router.post("/run", response_model=RunEnvelope)
async def run_insights(
    player: CurrentUser,
    as_of: date | None = None,
    db: AsyncSession = Depends(get_db),
) -> RunEnvelope:
    service = InsightsService(db)
    result = await service.run(player, as_of=as_of)
    return RunEnvelope(
        data=RunData(
            ftpDrift=_ftp_data(result["ftpDrift"]),
            earlyWarning=_warning_data(result["earlyWarning"]),
            drivers=_drivers_data(result["drivers"]),
            recorded=result["recorded"],
        ),
        meta=_meta(),
        errors=[],
    )
