"""Sleep history read APIs.

Batch 120 adds one lightweight calendar read: a per-date verdict map over a
small date range, so the Sleep calendar can tint a visible month without
loading full daily-loop snapshots per cell.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import CurrentUser
from src.database import get_db
from src.models.coaching import Analysis

router = APIRouter(prefix="/api/v1/sleep", tags=["sleep"])

ANALYSIS_TYPE_MORNING = "morning"


class SleepCalendarVerdictsData(BaseModel):
    from_date: date = Field(alias="from")
    to_date: date = Field(alias="to")
    verdicts: dict[str, str | None]


class SleepCalendarVerdictsMeta(BaseModel):
    generatedAtUtc: str


class SleepCalendarVerdictsEnvelope(BaseModel):
    data: SleepCalendarVerdictsData
    meta: SleepCalendarVerdictsMeta
    errors: list[str] = Field(default_factory=list)


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _parse_iso_date(label: str, raw: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{label} must be YYYY-MM-DD",
        ) from exc


@router.get("/verdicts", response_model=SleepCalendarVerdictsEnvelope)
async def get_sleep_calendar_verdicts(
    player: CurrentUser,
    db: AsyncSession = Depends(get_db),
    from_date_raw: str = Query(alias="from", description="Range start YYYY-MM-DD"),
    to_date_raw: str = Query(alias="to", description="Range end YYYY-MM-DD"),
) -> SleepCalendarVerdictsEnvelope:
    from_date = _parse_iso_date("from", from_date_raw)
    to_date = _parse_iso_date("to", to_date_raw)
    if from_date > to_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="from must be on or before to",
        )

    rows = (
        (
            await db.execute(
                select(Analysis.subject_date, Analysis.verdict)
                .where(
                    Analysis.user_id == player.id,
                    Analysis.analysis_type == ANALYSIS_TYPE_MORNING,
                    Analysis.subject_date >= from_date,
                    Analysis.subject_date <= to_date,
                )
                .order_by(
                    Analysis.subject_date.asc(),
                    desc(Analysis.generated_at_utc),
                    desc(Analysis.id),
                )
            )
        )
        .all()
    )

    verdicts: dict[str, str | None] = {}
    for subject_date, verdict in rows:
        key = subject_date.isoformat()
        if key in verdicts:
            continue
        verdicts[key] = verdict.strip().lower() if verdict else None

    return SleepCalendarVerdictsEnvelope(
        data=SleepCalendarVerdictsData.model_validate(
            {
                "from": from_date,
                "to": to_date,
                "verdicts": verdicts,
            }
        ),
        meta=SleepCalendarVerdictsMeta(generatedAtUtc=_now()),
    )
