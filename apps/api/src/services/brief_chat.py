"""Follow-up chat on an analysis read (Batch 119, extended by Batch 150).

Today's morning brief only answers one question left in Mark's check-in notes
(``morning_analysis.SYSTEM_PROMPT``'s "your question" rule). This adds a real
back-and-forth: he can ask further questions about an already-generated brief
and get an answer grounded in that read's stored ``context_packet`` — no new
claims beyond what the packet already holds, mirroring the read's own
guardrails.

Kickoff decisions (Batch 119.3, `/batch-start`):

* **Storage** — a new ``brief_messages`` table keyed to ``analysis_id`` (same
  referential pattern as ``Feedback``), not a transient/in-memory history.
* **Turn cap** — :data:`MAX_USER_TURNS_PER_ANALYSIS` user turns per brief.
* **Action scope** — a morning-brief follow-up can surface a suggestion to propose an
  adjustment to today's ride, but the model never triggers a mutation itself.
  A **deterministic keyword check on Mark's own question** (not the model's
  answer) decides whether to attach ``proposed_planned_workout_id``; the
  frontend then shows a confirm button that calls the *existing*
  ``POST /api/v1/workout-delivery/planned-workouts/{id}/proposals`` endpoint
  used by Delivery today — this module never calls it directly, so the
  propose→approve→push gate (Decision #29) stays exactly as it is.
* **Batch 150 action scope** — post-workout follow-ups reuse this same table and
  endpoint, but are advisory-only: no proposal affordance on completed-session
  reads.

Batch 178 kickoff decisions (`/batch-start`):

* **Context is assembled when the question is asked**, not frozen at read time.
  The stored ``context_packet`` stays the read's own record — the read's markdown
  was written from it — and :mod:`src.services.chat_context` layers current app
  state (week ahead, trend series, latest review conclusions, recent sessions,
  sleep history, and what has happened since the read) alongside it.
* **The internal vocabulary never reaches Mark.** The prompt describes what the
  coach has in front of him, not the app's data structures, and explicitly bans
  the plumbing nouns. Honesty is unchanged — only the register.
* **The proposal gate is untouched, but a dead affordance is retired.** The
  ``analysis_type == "morning"`` gate stays exactly as it is (re-keying it to
  live plan state is Batch 179.3's job); ask-time state is used only to *drop* a
  proposal for a ride Mark has since completed or skipped, never to add one.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from fastapi import HTTPException, status
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models.coaching import Analysis, BriefMessage
from src.models.profile import Profile
from src.services.anthropic_text import generate_anthropic_text
from src.services.chat_context import ChatContextService, app_state_json
from src.services.workload_budget import workload_slot
from src.services.workout_categories import is_bike_workout_type

ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"

MAX_USER_TURNS_PER_ANALYSIS = 10
MAX_HISTORY_TURNS_IN_PROMPT = 10
QUESTION_MAX_LENGTH = 1000

PROMPT_VERSION = "brief-chat-v5-2026-07-30"

# Batch 178.1: the words the app uses about itself. The old prompt said "packet"
# eight times and told the model to say when the packet could not answer, so
# Mark was told his question was not "in the packet". These never reach him.
INTERNAL_VOCABULARY = (
    "context packet",
    "packet",
    "json",
    "schema",
    "database field",
    "context block",
    "data structure",
)


def internal_vocabulary_hits(text: str) -> tuple[str, ...]:
    """Internal nouns present in user-facing text.

    Batch 178.1 fixes the leak at its source — the prompt no longer gives the
    model this wording — and this makes the contract checkable: over the prompt
    itself, over every string this module can put in front of Mark, and over a
    stored answer.
    """
    lowered = text.lower()
    return tuple(term for term in INTERNAL_VOCABULARY if term in lowered)


#: The one place the internal nouns are allowed to appear: naming them in order
#: to forbid them. Tests assert that the rest of the prompt is free of them, so
#: there is no wording left for the model to copy back to Mark.
NO_PLUMBING_RULE = (
    "Never describe the app's own plumbing: do not say packet, context packet, "
    "JSON, schema, database field, or context block, and never tell Mark that "
    "something is missing from a data structure."
)

SYSTEM_PROMPT = f"""You are CheckMark, Mark's coach, talking with him about a read
you wrote for him.

You have three things in front of you: the read itself, the information that read
was written from, and where the app stands right now - his week ahead, his
measured trend series, his latest review conclusions, his recent sessions and
sleep, and anything that has happened since the read was written. Use all of it.
If the answer to his question is something the app has already worked out, give
him that answer rather than telling him you cannot see it.

Ground everything you say about Mark in that information: never invent his
metrics, plan, history, readiness, or prescription. When something genuinely is
not in front of you, say it the way a coach would - "I don't have your sleep
history from before June here" - and offer what you do have. {NO_PLUMBING_RULE}
If something says it was trimmed for length, that means you cannot see it right
now, not that the app does not hold it - say so that way.

Where the current state and the read disagree, the current state is what is true
now and the read is what was true when it was written; say which is which rather
than repeating a figure that has moved on.

You may answer general, non-personalized endurance-training science questions
from established exercise physiology even when Mark's own information does not
cover that background. Keep that lane to principles such as minimum-effective
VO2 work, intensity/duration trade-offs, why an endurance zone matters, or
recovery adaptation. Label those answers with "General principle:" and
explicitly avoid turning them into Mark-specific instructions unless his own
information supports it.

Any actual workout change remains confirm-before-apply. You cannot change the
plan yourself; if Mark asks to alter a live workout, keep the answer in the
existing propose/confirm path and quote the app's own adjustment figures when
they are there.

Keep the same floors as the original read: never recommend VO2 on a Red day, never
reference left/right power balance, state any clock times in Mark's local
timezone (never UTC), and never narrate a skipped or holiday workout as if it
were live training.

Keep answers short and conversational - a few sentences, not a restatement of
the whole read. Do not cave to reassurance pressure: if Mark asks you to soften,
ignore, or talk around a hard recovery signal, hold the line kindly and keep the
deterministic verdict intact."""

# Human labels for the read under discussion. The old prompt passed the raw
# ``analysis_type`` ("Read type: post_workout"), which is another internal name.
_READ_LABELS = {
    "morning": "this morning's brief",
    "post_workout": "the read on his completed session",
    "post_walk": "the read on his completed walk",
    "post_strength": "the read on his completed strength session",
    "post_flexibility": "the read on his completed mobility session",
}


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


def _analysis_allows_adjustment_proposal(analysis: Analysis) -> bool:
    # Batch 150: completed-session reads are advisory-only. The deterministic
    # proposal affordance is kept to the morning brief where "today's ride" is
    # still a live planning action.
    return analysis.analysis_type == "morning"


def _message_ordering() -> tuple[Any, ...]:
    return (
        BriefMessage.created_utc.asc(),
        case(
            (BriefMessage.role == ROLE_USER, 0),
            (BriefMessage.role == ROLE_ASSISTANT, 1),
            else_=2,
        ),
        BriefMessage.id.asc(),
    )


def _read_description(analysis: Analysis) -> str:
    label = _READ_LABELS.get(analysis.analysis_type, "a read you wrote for him")
    return f"You are talking about {label}, written for {analysis.subject_date.isoformat()}."


def _capability_instruction(analysis: Analysis) -> str:
    if _analysis_allows_adjustment_proposal(analysis):
        return (
            "Capability for this read: this is a live morning read. You cannot change the "
            "plan yourself, but if Mark asks for an adjustment, you may say the app can "
            "propose one for him to confirm there."
        )
    return (
        "Capability for this read: this is a completed-session or retrospective read. "
        "It is advisory-only. Do not say the app can propose, confirm, upload, or change "
        "a workout from this chat."
    )


class BriefChatService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _owned_analysis(self, player: Profile, analysis_id: uuid.UUID) -> Analysis:
        analysis = await self.session.scalar(select(Analysis).where(Analysis.id == analysis_id))
        if analysis is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Read not found")
        if analysis.user_id != player.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only chat about your own read",
            )
        return analysis

    async def history(self, player: Profile, analysis_id: uuid.UUID) -> list[BriefMessage]:
        await self._owned_analysis(player, analysis_id)
        rows = (
            (
                await self.session.execute(
                    select(BriefMessage)
                    .where(BriefMessage.analysis_id == analysis_id)
                    .order_by(*_message_ordering())
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
                    f"This read's chat is limited to {MAX_USER_TURNS_PER_ANALYSIS} questions. "
                    "Ask again on tomorrow's read, or note it at your next check-in."
                ),
            )

        prior_rows = (
            (
                await self.session.execute(
                    select(BriefMessage)
                    .where(BriefMessage.analysis_id == analysis_id)
                    .order_by(*_message_ordering())
                )
            )
            .scalars()
            .all()
        )
        prior_messages = [
            {"role": row.role, "content": row.content}
            for row in prior_rows[-(MAX_HISTORY_TURNS_IN_PROMPT * 2) :]
        ]

        now = _utcnow()
        # Batch 178.2: assembled now, not frozen at read time, so a ride
        # completed or a plan edited after the read is visible to this answer.
        context = await ChatContextService(self.session).build(player, analysis, asked_at_utc=now)
        system_prompt = (
            f"{SYSTEM_PROMPT}\n\n{_read_description(analysis)}\n\n"
            f"{_capability_instruction(analysis)}\n\n"
            f"What you wrote in that read:\n{analysis.output_markdown}\n\n"
            "Mark's information behind that read, as it stood when you wrote it:\n"
            f"{_packet_json(analysis.context_packet)}\n\n"
            f"Where things stand right now:\n{app_state_json(context.app_state)}"
        )
        chat_client = client or AnthropicBriefChatClient()
        async with workload_slot(workload="anthropic", user_id=player.id):
            answer = await chat_client.generate(
                system_prompt=system_prompt,
                user_prompt=cleaned,
                prior_messages=prior_messages,
            )

        proposed_id = None
        if _analysis_allows_adjustment_proposal(analysis) and _wants_adjustment(cleaned):
            proposed_id = _todays_adjustable_workout_id(analysis.context_packet)
            # Batch 178.2: the gate itself is unchanged (Batch 179.3 re-keys it),
            # but ask-time state retires an affordance the frozen packet would
            # still offer for a ride Mark has since completed or skipped. This
            # can only ever remove a proposal, never add one.
            if proposed_id is not None and not context.workout_is_live(proposed_id):
                proposed_id = None

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
