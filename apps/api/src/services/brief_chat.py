"""Follow-up chat on a brief (Batch 119).

Today's morning brief only answers one question left in Mark's check-in notes
(``morning_analysis.SYSTEM_PROMPT``'s "your question" rule). This adds a real
back-and-forth: he can ask further questions about an already-generated brief
and get an answer grounded in that brief's stored ``context_packet`` — no new
claims beyond what the packet already holds, mirroring the brief's own
guardrails.

Kickoff decisions (Batch 119.3, `/batch-start`):

* **Storage** — a new ``brief_messages`` table keyed to ``analysis_id`` (same
  referential pattern as ``Feedback``), not a transient/in-memory history.
* **Turn cap** — :data:`MAX_USER_TURNS_PER_ANALYSIS` user turns per brief.
* **Action scope** — a follow-up can surface a suggestion to propose an
  adjustment to today's ride, but the model never triggers a mutation itself.
  A **deterministic keyword check on Mark's own question** (not the model's
  answer) decides whether to attach ``proposed_planned_workout_id``; the
  frontend then shows a confirm button that calls the *existing*
  ``POST /api/v1/workout-delivery/planned-workouts/{id}/proposals`` endpoint
  used by Delivery today — this module never calls it directly, so the
  propose→approve→push gate (Decision #29) stays exactly as it is.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models.coaching import Analysis, BriefMessage
from src.models.profile import Profile
from src.services.anthropic_text import generate_anthropic_text
from src.services.workout_categories import is_bike_workout_type

ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"

MAX_USER_TURNS_PER_ANALYSIS = 10
MAX_HISTORY_TURNS_IN_PROMPT = 10
QUESTION_MAX_LENGTH = 1000

PROMPT_VERSION = "brief-chat-v1-2026-07-14"

SYSTEM_PROMPT = """You are CheckMark, answering a follow-up question about a
brief you already wrote for Mark. You are given that brief's full context
packet (the same metrics/plan/environment data the brief itself was written
from) and the brief's own markdown text.

Answer only from the packet and the brief. Do not invent metrics, plan
details, or recommendations that are not supported by what you were given.
If the packet does not hold what is needed to answer, say so plainly rather
than guessing.

Keep the same floors as the brief: never recommend VO2 on a Red day, never
reference left/right power balance, state any clock times in Mark's local
timezone (never UTC), and never narrate a skipped or holiday workout as if it
were live training.

Keep answers short and conversational — a few sentences, not a restatement of
the whole brief. Do not fabricate the ability to change the plan yourself;
if he wants an adjustment, say the app can propose one and he confirms it
there, but do not claim to have made any change."""


class BriefChatError(Exception):
    pass


class BriefChatClient(Protocol):
    async def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        prior_messages: list[dict[str, str]],
    ) -> str: ...


class AnthropicBriefChatClient:
    def __init__(self, *, api_key: str | None = None, model_name: str | None = None) -> None:
        self.api_key = api_key if api_key is not None else settings.anthropic_api_key
        self.model_name = model_name or settings.anthropic_model
        self.max_tokens = 1024

    async def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        prior_messages: list[dict[str, str]],
    ) -> str:
        if not self.api_key:
            raise BriefChatError("ANTHROPIC_API_KEY is not configured.")
        result = await generate_anthropic_text(
            api_key=self.api_key,
            model_name=self.model_name,
            max_tokens=self.max_tokens,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            prior_messages=prior_messages,
            error_cls=BriefChatError,
        )
        return result.output_markdown


# Deterministic intent check on Mark's own words — never the model's answer —
# so a proposal is only ever offered when he actually asked for one.
_ADJUSTMENT_KEYWORDS = (
    "ease",
    "easier",
    "lighter",
    "reduce",
    "shorter",
    "swap",
    "adjust",
    "propose",
    "change today",
    "harder",
)


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@dataclass(frozen=True)
class BriefChatTurn:
    user_message: BriefMessage
    assistant_message: BriefMessage


def _wants_adjustment(question: str) -> bool:
    lowered = question.lower()
    return any(keyword in lowered for keyword in _ADJUSTMENT_KEYWORDS)


def _todays_adjustable_workout_id(context_packet: dict[str, Any]) -> uuid.UUID | None:
    """The one planned workout a follow-up could offer to propose against.

    Mirrors ``morning_analysis._todays_bike_workout``'s selection but reads
    from the already-serialized packet, not live ORM rows, and additionally
    requires a structured workout (deliverable) and no rest day.
    """
    if context_packet.get("restDay", {}).get("isRestDay"):
        return None
    for workout in context_packet.get("plannedWorkouts", []):
        if workout.get("status") in {"completed", "skipped"}:
            continue
        if not workout.get("structuredWorkout"):
            continue
        if is_bike_workout_type(workout.get("workoutType")):
            try:
                return uuid.UUID(workout["id"])
            except (KeyError, ValueError, TypeError):
                return None
    return None


class BriefChatService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _owned_analysis(self, player: Profile, analysis_id: uuid.UUID) -> Analysis:
        analysis = await self.session.scalar(select(Analysis).where(Analysis.id == analysis_id))
        if analysis is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Brief not found")
        if analysis.user_id != player.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only chat about your own brief",
            )
        return analysis

    async def history(self, player: Profile, analysis_id: uuid.UUID) -> list[BriefMessage]:
        await self._owned_analysis(player, analysis_id)
        rows = (
            (
                await self.session.execute(
                    select(BriefMessage)
                    .where(BriefMessage.analysis_id == analysis_id)
                    .order_by(BriefMessage.created_utc.asc())
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    async def ask(
        self,
        player: Profile,
        analysis_id: uuid.UUID,
        *,
        question: str,
        client: BriefChatClient | None = None,
        commit: bool = True,
    ) -> BriefChatTurn:
        cleaned = question.strip()
        if not cleaned:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Question cannot be empty."
            )
        if len(cleaned) > QUESTION_MAX_LENGTH:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Question must be {QUESTION_MAX_LENGTH} characters or fewer.",
            )

        analysis = await self._owned_analysis(player, analysis_id)

        turn_count = await self.session.scalar(
            select(func.count())
            .select_from(BriefMessage)
            .where(BriefMessage.analysis_id == analysis_id, BriefMessage.role == ROLE_USER)
        )
        if (turn_count or 0) >= MAX_USER_TURNS_PER_ANALYSIS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"This brief's chat is limited to {MAX_USER_TURNS_PER_ANALYSIS} questions. "
                    "Ask again on tomorrow's brief, or note it at your next check-in."
                ),
            )

        prior_rows = (
            (
                await self.session.execute(
                    select(BriefMessage)
                    .where(BriefMessage.analysis_id == analysis_id)
                    .order_by(BriefMessage.created_utc.asc())
                )
            )
            .scalars()
            .all()
        )
        prior_messages = [
            {"role": row.role, "content": row.content}
            for row in prior_rows[-(MAX_HISTORY_TURNS_IN_PROMPT * 2) :]
        ]

        system_prompt = (
            f"{SYSTEM_PROMPT}\n\nBrief context packet (JSON):\n"
            f"{_packet_json(analysis.context_packet)}\n\nBrief text:\n{analysis.output_markdown}"
        )
        chat_client = client or AnthropicBriefChatClient()
        answer = await chat_client.generate(
            system_prompt=system_prompt,
            user_prompt=cleaned,
            prior_messages=prior_messages,
        )

        proposed_id = (
            _todays_adjustable_workout_id(analysis.context_packet)
            if _wants_adjustment(cleaned)
            else None
        )

        now = _utcnow()
        user_message = BriefMessage(
            user_id=player.id,
            analysis_id=analysis_id,
            role=ROLE_USER,
            content=cleaned,
            created_utc=now,
        )
        assistant_message = BriefMessage(
            user_id=player.id,
            analysis_id=analysis_id,
            role=ROLE_ASSISTANT,
            content=answer,
            proposed_planned_workout_id=proposed_id,
            created_utc=now,
        )
        self.session.add(user_message)
        self.session.add(assistant_message)
        if commit:
            await self.session.commit()
            await self.session.refresh(user_message)
            await self.session.refresh(assistant_message)
        else:
            await self.session.flush()
        return BriefChatTurn(user_message=user_message, assistant_message=assistant_message)


def _packet_json(context_packet: dict[str, Any]) -> str:
    return json.dumps(context_packet, ensure_ascii=True, sort_keys=True, default=str)
