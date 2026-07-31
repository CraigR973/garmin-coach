"""The one coach conversation, reachable from anywhere — Batch 179.

  GET  /api/v1/coach/messages   — the rolling conversation
  POST /api/v1/coach/messages   — ask, from any surface, with or without a read

``/api/v1/briefs/{analysis_id}/messages`` (Batch 119) still exists and still
returns only the turns asked from that read, because the inline chat on a read
should keep showing that read's own exchange rather than everything Mark has
ever asked. Both endpoints write into the same thread: the difference is the
view, not the storage.

A question may name the read it came from (``analysisId``) or, for the surfaces
that have no ``Analysis`` row at all — Sleep, the breathwork/strength/walking
briefs — just where it came from (``originKind``/``originDate``). Either way it
is a seed for the answer, not a fence around it.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import CurrentUser
from src.database import get_db
from src.rate_limit import paid_generation_limit
from src.routers.brief_chat import (
    ApiMeta,
    BriefMessageListEnvelope,
    BriefMessageTurnData,
    BriefMessageTurnEnvelope,
    generated_at,
    serialize_message,
)
from src.services.anthropic_text import (
    AnthropicApiError,
    anthropic_http_status,
    anthropic_user_message,
)
from src.services.brief_chat import QUESTION_MAX_LENGTH, BriefChatService
from src.services.nudge_alerts import NudgeAlertService

router = APIRouter(prefix="/api/v1/coach", tags=["coach-chat"])


def _local_today(timezone_name: str) -> date:
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        zone = ZoneInfo("UTC")
    return datetime.now(zone).date()


class CoachMessageInput(BaseModel):
    question: str = Field(..., min_length=1, max_length=QUESTION_MAX_LENGTH)
    #: The read this was asked from, when there is one.
    analysisId: uuid.UUID | None = None
    #: Which surface it was asked from otherwise. An unknown value degrades to
    #: the general origin rather than erroring — and is never interpolated into
    #: the prompt as free text (``chat_context.normalize_origin_kind``).
    originKind: str | None = Field(default=None, max_length=32)
    originDate: date | None = None


@router.get("/messages", response_model=BriefMessageListEnvelope)
async def list_coach_messages(
    player: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> BriefMessageListEnvelope:
    rows = await BriefChatService(db).thread(player)
    return BriefMessageListEnvelope(
        data=[serialize_message(row) for row in rows],
        meta=ApiMeta(generatedAtUtc=generated_at()),
        errors=[],
    )


@router.post("/messages", response_model=BriefMessageTurnEnvelope)
@paid_generation_limit
async def ask_coach(
    payload: CoachMessageInput,
    request: Request,
    player: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> BriefMessageTurnEnvelope:
    service = BriefChatService(db)
    try:
        turn = await service.ask(
            player,
            question=payload.question,
            analysis_id=payload.analysisId,
            origin_kind=payload.originKind,
            origin_date=payload.originDate,
        )
    except AnthropicApiError as exc:
        # Same handling as the per-read surface (Batch 143): this LLM call runs
        # in-request, so an outage would otherwise surface as an unparseable 500.
        if exc.reason == "billing":
            await NudgeAlertService(db).notify_admin_generation_failure(
                reason=exc.reason, subject_date=_local_today(player.timezone), commit=True
            )
        raise HTTPException(
            status_code=anthropic_http_status(exc.reason),
            detail=anthropic_user_message(exc.reason),
        ) from exc
    return BriefMessageTurnEnvelope(
        data=BriefMessageTurnData(
            userMessage=serialize_message(turn.user_message),
            assistantMessage=serialize_message(turn.assistant_message),
        ),
        meta=ApiMeta(generatedAtUtc=generated_at()),
        errors=[],
    )


__all__ = ["CoachMessageInput", "router"]
