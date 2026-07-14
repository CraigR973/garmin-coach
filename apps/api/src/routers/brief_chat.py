"""Follow-up chat on a brief — Batch 119.

  GET  /api/v1/briefs/{analysis_id}/messages   — this user's conversation history
  POST /api/v1/briefs/{analysis_id}/messages   — ask a follow-up, get the answer

Every AI summary is one ``analyses`` row, so the conversation is keyed to
``analysis_id`` the same way ``feedback`` is. The write is user-scoped: 404
when the analysis does not exist, 403 when it belongs to another profile.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import CurrentUser
from src.database import get_db
from src.models.coaching import BriefMessage
from src.services.brief_chat import BriefChatService

router = APIRouter(prefix="/api/v1/briefs", tags=["brief-chat"])


def _generated_at() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class ApiError(BaseModel):
    code: str
    detail: str


class ApiMeta(BaseModel):
    generatedAtUtc: str


class BriefMessageInput(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)


class BriefMessageOut(BaseModel):
    id: str
    analysisId: str
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


def _serialize(row: BriefMessage) -> BriefMessageOut:
    return BriefMessageOut(
        id=str(row.id),
        analysisId=str(row.analysis_id),
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
        data=[_serialize(row) for row in rows],
        meta=ApiMeta(generatedAtUtc=_generated_at()),
        errors=[],
    )


@router.post("/{analysis_id}/messages", response_model=BriefMessageTurnEnvelope)
async def ask_brief_followup(
    analysis_id: uuid.UUID,
    payload: BriefMessageInput,
    player: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> BriefMessageTurnEnvelope:
    service = BriefChatService(db)
    turn = await service.ask(player, analysis_id, question=payload.question)
    return BriefMessageTurnEnvelope(
        data=BriefMessageTurnData(
            userMessage=_serialize(turn.user_message),
            assistantMessage=_serialize(turn.assistant_message),
        ),
        meta=ApiMeta(generatedAtUtc=_generated_at()),
        errors=[],
    )
