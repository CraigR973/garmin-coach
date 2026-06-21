"""Dynamic weekly restructuring API (Batch 14).

Two surfaces, both human-driven so nothing is rewritten or delivered silently
(Decision #29):

  * ``GET  /api/v1/restructure/week-ahead`` — read-only preview of the recovery
    signal and the proposed reassignment for a week.
  * ``POST /api/v1/restructure/apply`` — version the changed days and propose the
    changed bike workouts for delivery. Pushing to Zwift still requires the
    existing approve → push rail.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import CurrentUser
from src.database import get_db
from src.services.weekly_restructure import (
    RecoverySignal,
    RestructurePlan,
    WeeklyRestructureService,
)

router = APIRouter(prefix="/api/v1/restructure", tags=["restructure"])


def _generated_at() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _week_start(timezone_name: str, week_start: date | None) -> date:
    if week_start is not None:
        return week_start
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        timezone = ZoneInfo("UTC")
    today = datetime.now(timezone).date()
    return today - timedelta(days=today.weekday())


class ApiError(BaseModel):
    code: str
    detail: str


class ApiMeta(BaseModel):
    generatedAtUtc: str


class SignalOut(BaseModel):
    fatigued: bool
    readinessScore: int | None
    hrvStatus: str | None
    recentVerdicts: list[str]
    reasons: list[str]


class ChangeOut(BaseModel):
    workoutDate: str
    fromWorkoutId: str
    toWorkoutId: str
    reason: str


class RestructureData(BaseModel):
    weekStart: str
    fatigued: bool
    changed: bool
    signal: SignalOut
    changes: list[ChangeOut]
    conflictsBefore: list[list[str]]
    conflictsAfter: list[list[str]]
    notes: list[str]
    proposalsCreated: int


class RestructureEnvelope(BaseModel):
    data: RestructureData
    meta: ApiMeta
    errors: list[ApiError]


def _signal_out(signal: RecoverySignal) -> SignalOut:
    return SignalOut(
        fatigued=signal.fatigued,
        readinessScore=signal.readiness_score,
        hrvStatus=signal.hrv_status,
        recentVerdicts=signal.recent_verdicts,
        reasons=signal.reasons,
    )


def _data(
    plan: RestructurePlan, signal: RecoverySignal, *, proposals_created: int
) -> RestructureData:
    return RestructureData(
        weekStart=plan.week_start.isoformat(),
        fatigued=plan.fatigued,
        changed=plan.changed,
        signal=_signal_out(signal),
        changes=[
            ChangeOut(
                workoutDate=change.workout_date.isoformat(),
                fromWorkoutId=str(change.from_workout_id),
                toWorkoutId=str(change.to_workout_id),
                reason=change.reason,
            )
            for change in plan.changes
        ],
        conflictsBefore=[[d1.isoformat(), d2.isoformat()] for d1, d2 in plan.conflicts_before],
        conflictsAfter=[[d1.isoformat(), d2.isoformat()] for d1, d2 in plan.conflicts_after],
        notes=plan.notes,
        proposalsCreated=proposals_created,
    )


@router.get("/week-ahead", response_model=RestructureEnvelope)
async def preview_restructure(
    player: CurrentUser,
    week_start: date | None = None,
    db: AsyncSession = Depends(get_db),
) -> RestructureEnvelope:
    service = WeeklyRestructureService(db)
    start = _week_start(player.timezone, week_start)
    plan, signal = await service.plan_for_week(player, start)
    return RestructureEnvelope(
        data=_data(plan, signal, proposals_created=0),
        meta=ApiMeta(generatedAtUtc=_generated_at()),
        errors=[],
    )


@router.post("/apply", response_model=RestructureEnvelope)
async def apply_restructure(
    player: CurrentUser,
    week_start: date | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> RestructureEnvelope:
    service = WeeklyRestructureService(db)
    start = _week_start(player.timezone, week_start)
    result = await service.apply_for_week(player, start)
    return RestructureEnvelope(
        data=_data(result.plan, result.signal, proposals_created=len(result.proposals)),
        meta=ApiMeta(generatedAtUtc=_generated_at()),
        errors=[],
    )
