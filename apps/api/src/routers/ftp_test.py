"""Batch 336.1: his decision on a ramp test's result (CI330-02)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import CurrentUser
from src.database import get_db
from src.routers.daily_loop_schemas import ApiError, ApiMeta
from src.services.daily_loop_envelope import local_today
from src.services.ftp_test import FtpTestService

router = APIRouter(prefix="/api/v1/ftp-test", tags=["ftp-test"])


def _generated_at() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class FtpTestDecisionBody(BaseModel):
    plannedWorkoutId: uuid.UUID
    choice: Literal["set", "keep"]
    #: Zwift's own number, when it differs from the app's; ``None`` takes the app's.
    ftpWatts: int | None = Field(default=None, ge=1, le=1000)


class FtpTestDecisionOut(BaseModel):
    choice: str
    testDate: str
    ftpWatts: int | None
    previousFtpWatts: int | None


class FtpTestDecisionEnvelope(BaseModel):
    data: FtpTestDecisionOut
    meta: ApiMeta
    errors: list[ApiError] = Field(default_factory=list)


@router.post("/decision", response_model=FtpTestDecisionEnvelope)
async def decide(
    body: FtpTestDecisionBody,
    player: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> FtpTestDecisionEnvelope:
    """Set his FTP from the test (the app's number or Zwift's), or keep the one he has.

    Refused (409) when no test result waits; Zwift's number must sit within 10% of the
    app's (422)."""
    decision = await FtpTestService(db).decide(
        player,
        planned_workout_id=body.plannedWorkoutId,
        choice=body.choice,
        today=local_today(player.timezone),
        ftp_watts=body.ftpWatts if body.choice == "set" else None,
    )
    return FtpTestDecisionEnvelope(
        data=FtpTestDecisionOut(
            choice=decision.choice,
            testDate=decision.test_date.isoformat(),
            ftpWatts=decision.ftp_watts,
            previousFtpWatts=decision.previous_ftp_watts,
        ),
        meta=ApiMeta(generatedAtUtc=_generated_at()),
    )
