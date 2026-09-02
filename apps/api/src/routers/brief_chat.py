"""Follow-up chat on an analysis read — Batch 119, extended by Batch 150/179.

  GET  /api/v1/briefs/{analysis_id}/messages   — the turns asked from this read
  POST /api/v1/briefs/{analysis_id}/messages   — ask from this read, get the answer

The write is user-scoped: 404 when the analysis does not exist, 403 when it
belongs to another profile.

Batch 179 turned the storage underneath into one rolling conversation
(``/api/v1/coach/messages``), but kept this surface unchanged: the inline chat
on a read should show that read's own exchange, not everything Mark has ever
asked. The two endpoints are two views of the same thread, and the envelope
they share is defined here.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import CurrentUser
from src.database import get_db
from src.models.coaching import BriefMessage
from src.rate_limit import paid_generation_limit
from src.services.anthropic_text import (
    AnthropicApiError,
    anthropic_http_status,
    anthropic_user_message,
)
from src.services.brief_chat import BriefChatError, BriefChatService
from src.services.nudge_alerts import NudgeAlertService

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/briefs", tags=["brief-chat"])


def generated_at() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _local_today(timezone_name: str) -> date:
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        zone = ZoneInfo("UTC")
    return datetime.now(zone).date()


class ApiError(BaseModel):
    code: str
    detail: str


class ApiMeta(BaseModel):
    generatedAtUtc: str


class BriefMessageInput(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)


class BriefMessageOut(BaseModel):
    id: str
    #: Null since Batch 179: a conversation no longer needs a document.
    analysisId: str | None
    originKind: str | None
    originDate: str | None
    role: str
    content: str
    proposedPlannedWorkoutId: str | None
    createdAtUtc: str


class BriefMessageListEnvelope(BaseModel):
    data: list[BriefMessageOut]
    meta: ApiMeta
    errors: list[ApiError]


class BriefMessageTurnData(BaseModel):
    userMessage: BriefMessageOut
    assistantMessage: BriefMessageOut


class BriefMessageTurnEnvelope(BaseModel):
    data: BriefMessageTurnData
    meta: ApiMeta
    errors: list[ApiError]


def serialize_message(row: BriefMessage) -> BriefMessageOut:
    return BriefMessageOut(
        id=str(row.id),
        analysisId=str(row.analysis_id) if row.analysis_id else None,
        originKind=row.origin_kind,
        originDate=row.origin_date.isoformat() if row.origin_date else None,
        role=row.role,
        content=row.content,
        proposedPlannedWorkoutId=(
            str(row.proposed_planned_workout_id) if row.proposed_planned_workout_id else None
        ),
        createdAtUtc=row.created_utc.isoformat() + "Z",
    )


@router.get("/{analysis_id}/messages", response_model=BriefMessageListEnvelope)
async def list_brief_messages(
    analysis_id: uuid.UUID,
    player: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> BriefMessageListEnvelope:
    service = BriefChatService(db)
    rows = await service.history(player, analysis_id)
    return BriefMessageListEnvelope(
        data=[serialize_message(row) for row in rows],
        meta=ApiMeta(generatedAtUtc=generated_at()),
        errors=[],
    )


@router.post("/{analysis_id}/messages", response_model=BriefMessageTurnEnvelope)
@paid_generation_limit
async def ask_brief_followup(
    analysis_id: uuid.UUID,
    payload: BriefMessageInput,
    request: Request,
    player: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> BriefMessageTurnEnvelope:
    service = BriefChatService(db)
    try:
        turn = await service.ask(player, question=payload.question, analysis_id=analysis_id)
    except AnthropicApiError as exc:
        # Batch 143: this LLM call runs in-request, so an Anthropic outage (the
        # 2026-07-20/21 credit freeze) used to propagate to a bare 500 whose
        # plain-text "Internal Server Error" body the web client couldn't parse.
        # Return an honest, retryable JSON error instead (no half-written turn is
        # persisted — the model call precedes every DB write in ``ask``), and route
        # a billing outage through the same admin alert as the morning brief (141).
        # Batch 248 (AI238-03): alert on every reason. A chat turn that fails
        # on a spend cap, a timeout or a 429 is as operator-visible as one that
        # fails on an empty credit balance — and until this, only the last was.
        await NudgeAlertService(db).notify_admin_generation_failure(
            reason=exc.reason, subject_date=_local_today(player.timezone), commit=True
        )
        raise HTTPException(
            status_code=anthropic_http_status(exc.reason),
            detail=anthropic_user_message(exc.reason),
        ) from exc
    except BriefChatError as exc:
        # Batch 248 (AI238-11): ``BriefChatError`` is the *other* way this call
        # fails — a missing API key, or a response the boundary could not parse
        # into text — and nothing caught it. It escaped to a bare 500 whose
        # plain-text body the web client cannot parse, which is exactly the
        # regression Batch 143 closed for ``AnthropicApiError`` and left open
        # here. Same shape of answer: a real JSON body, and the operator told.
        log.exception("brief chat failed", profile_id=str(player.id))
        await NudgeAlertService(db).notify_admin_generation_failure(
            reason="chat_error", subject_date=_local_today(player.timezone), commit=True
        )
        raise HTTPException(
            status_code=502,
            detail=anthropic_user_message("chat_error"),
        ) from exc
    return BriefMessageTurnEnvelope(
        data=BriefMessageTurnData(
            userMessage=serialize_message(turn.user_message),
            assistantMessage=serialize_message(turn.assistant_message),
        ),
        meta=ApiMeta(generatedAtUtc=generated_at()),
        errors=[],
    )
