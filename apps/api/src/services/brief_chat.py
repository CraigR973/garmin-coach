"""Mark's coach conversation (Batch 119 → 150 → 178, opened up by Batch 179).

This started as a follow-up chat bolted to one generated read and grew into the
only place Mark talks to his coach. Batch 179 finished that: there is now **one
rolling conversation**, reachable from any surface, and the document a question
was asked from is a context seed rather than a fence.

Kickoff decisions carried forward:

* **Batch 119.3 / 202.3** — turns are rows in ``brief_messages``; a plan change
  is only ever *offered* when Mark's own question carries adjustment intent, a
  live workout exists, and the model's answer explicitly marks that it made the
  offer. Application still flows through the existing
  ``POST /api/v1/workout-delivery/planned-workouts/{id}/proposals`` endpoint, so
  the propose→approve→push gate (Decision #29) is untouched.
* **Batch 178** — context is assembled when the question is asked, not frozen at
  read time (:mod:`src.services.chat_context`), and the app's internal
  vocabulary never reaches Mark.

Batch 179 kickoff decisions (`/batch-start`):

* **One rolling thread, nullable anchor.** The rows already were the thread, so
  ``analysis_id`` simply became optional (migration 026) rather than growing a
  ``conversations``/``conversation_messages`` pair. History for the prompt is
  the tail of the *conversation*, not of one document, so it survives a read
  rolling over; the per-read view stays readable because filtering by
  ``analysis_id`` still selects exactly the rows it always did.
* **The cap moved with it.** A per-document cap made no sense once the document
  stopped bounding the conversation, so :data:`MAX_USER_TURNS_PER_DAY` bounds
  the paid calls over Mark's local day instead.
* **The propose gate is keyed on the plan, not the paperwork** (179.3). The old
  ``analysis_type == "morning"`` test was a proxy for "there is a live
  adjustable ride"; :attr:`ChatContext.adjustable_workout_id` answers that
  question directly from live plan rows, so the affordance appears from every
  entry point exactly when it can do something — and is absent on a rest day,
  inside a holiday, or once the ride is completed or skipped, which is what
  "never on a retrospective read" means in plan terms. Blocking a genuine "make
  today easier" just because it was asked from yesterday's read would recreate
  the document-fencing this batch exists to remove.
* **The rules live in one module** (:mod:`src.services.coach_policy`), so every
  entry point is handed the same floors.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Protocol

from fastapi import HTTPException, status
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models.coaching import Analysis, BriefMessage
from src.models.profile import Profile
from src.services.anthropic_text import generate_anthropic_text
from src.services.chat_context import (
    ChatContextService,
    CoachOrigin,
    app_state_json,
    day_start_utc,
    local_date,
    normalize_origin_kind,
)
from src.services.coach_policy import (
    ANTI_SYCOPHANCY_RULE,
    GENERAL_SCIENCE_RULE,
    GROUNDING_RULE,
    INTERNAL_VOCABULARY,
    NO_PLUMBING_RULE,
    PROPOSE_CONFIRM_RULE,
    floors_sentence,
    internal_vocabulary_hits,
)
from src.services.prompt_metadata import prompt_system_hash
from src.services.workload_budget import workload_slot

__all__ = [
    "INTERNAL_VOCABULARY",
    "MAX_HISTORY_TURNS_IN_PROMPT",
    "MAX_USER_TURNS_PER_DAY",
    "NO_PLUMBING_RULE",
    "PROMPT_VERSION",
    "PROPOSAL_MARKER",
    "QUESTION_MAX_LENGTH",
    "SYSTEM_PROMPT",
    "THREAD_PAGE_LIMIT",
    "AnthropicBriefChatClient",
    "BriefChatClient",
    "BriefChatError",
    "BriefChatService",
    "BriefChatTurn",
    "internal_vocabulary_hits",
]

ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"

#: Paid Anthropic calls per local day. Batch 179 replaced the per-read cap of 10
#: with a daily one: two reads used to allow 20 questions across two dead-end
#: chats, so this is the same order of spend spent on one conversation that
#: actually continues.
MAX_USER_TURNS_PER_DAY = 20
MAX_HISTORY_TURNS_IN_PROMPT = 10
#: Messages returned when the whole thread is read. The conversation is rolling,
#: so the API returns a recent window rather than everything Mark has ever asked.
THREAD_PAGE_LIMIT = 60
QUESTION_MAX_LENGTH = 1000

PROMPT_VERSION = "coach-chat-v8-2026-08-15"
PROPOSAL_MARKER = "[[PROPOSE_WORKOUT_ADJUSTMENT]]"

SYSTEM_PROMPT = f"""You are CheckMark, Mark's coach, talking with him.

You have where the app stands right now in front of you - his week ahead, his
measured trend series, his latest review conclusions, his recent sessions and
sleep, and today's plan - and, when he asked from one of your reads, that read
and the information it was written from. Use all of it. If the answer to his
question is something the app has already worked out, give him that answer
rather than telling him you cannot see it.

This is one continuing conversation, not a fresh start on each page. Mark may
open it from anywhere; where he opened it tells you what he is most likely
asking about, but it does not limit what he can ask. Earlier turns may be about
a different day or a different session - carry them forward rather than
pretending they did not happen.

{GROUNDING_RULE}

Where the current state and a read disagree, the current state is the app's
latest record and the read is the app's earlier record; say which is which
rather than repeating a figure that has moved on. Neither record proves what
Mark's body or own device actually showed.

{GENERAL_SCIENCE_RULE}

{PROPOSE_CONFIRM_RULE}

{floors_sentence()}

Keep answers short and conversational - a few sentences, not a restatement of
the whole read. {ANTI_SYCOPHANCY_RULE}"""

# Human labels for the read under discussion. The pre-178 prompt passed the raw
# ``analysis_type`` ("Read type: post_workout"), which is another internal name.
_READ_LABELS = {
    "morning": "this morning's brief",
    "post_workout": "the read on his completed session",
    "post_walk": "the read on his completed walk",
    "post_strength": "the read on his completed strength session",
    "post_flexibility": "the read on his completed mobility session",
    "weekly_review": "the weekly review you sent him",
}

#: Which surface an anchored question came from, so the stored row is
#: self-describing even when the client sends no origin of its own.
_ANALYSIS_ORIGINS = {
    "morning": "morning_brief",
    "post_workout": "workout",
    "post_walk": "workout",
    "post_strength": "workout",
    "post_flexibility": "workout",
    "weekly_review": "weekly_review",
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


# Deterministic intent check on Mark's own words. Batch 202 adds a second key:
# the model must also mark that its answer actually offered a proposal before
# the service attaches the planned-workout id.
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
    return (
        f"He asked this from {label}, written for {analysis.subject_date.isoformat()}. "
        "That is the starting point, not the boundary."
    )


def _origin_description(origin: CoachOrigin, *, local_today: date) -> str:
    subject = origin.subject_date or local_today
    return (
        f"He opened the conversation from {origin.label} "
        f"({subject.isoformat()}). That is the starting point, not the boundary; "
        "there is no read behind this question."
    )


def _capability_instruction(adjustable_workout_id: uuid.UUID | None) -> str:
    """What the coach may offer, from today's plan rather than the read type.

    Batch 179.3 re-keyed this: the affordance now follows whether a live,
    deliverable workout actually exists today, so it is right from every entry
    point instead of only from the morning read.
    """
    if adjustable_workout_id is not None:
        return (
            "Capability right now: today's plan holds a live workout that can still be "
            "adjusted. You cannot change it yourself, but if Mark asks for an adjustment, "
            "you may say the app can propose one for him to confirm. If and only if "
            f"your answer actually makes that offer, include {PROPOSAL_MARKER} once "
            "at the very end of the answer. The app removes that marker before Mark sees it."
        )
    return (
        "Capability right now: there is no live workout to adjust today - it is rest, "
        "away, or already done. Do not say the app can propose, confirm, upload, or "
        "change a workout from this conversation."
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
        """The turns asked from one read.

        Kept exactly as it was so the inline chat on a read still shows that
        read's own exchange rather than the whole conversation.
        """
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

    async def thread(
        self,
        player: Profile,
        *,
        limit: int = THREAD_PAGE_LIMIT,
    ) -> list[BriefMessage]:
        """The rolling conversation, most recent window, oldest first."""
        rows = await self._recent_messages(player.id, limit=limit)
        return rows

    async def _recent_messages(self, user_id: uuid.UUID, *, limit: int) -> list[BriefMessage]:
        newest_first = (
            (
                await self.session.execute(
                    select(BriefMessage)
                    .where(BriefMessage.user_id == user_id)
                    .order_by(
                        BriefMessage.created_utc.desc(),
                        case(
                            (BriefMessage.role == ROLE_ASSISTANT, 0),
                            (BriefMessage.role == ROLE_USER, 1),
                            else_=2,
                        ),
                        BriefMessage.id.desc(),
                    )
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return sorted(
            newest_first,
            key=lambda row: (row.created_utc, 0 if row.role == ROLE_USER else 1, str(row.id)),
        )

    async def ask(
        self,
        player: Profile,
        analysis_id: uuid.UUID | None = None,
        *,
        question: str,
        origin_kind: str | None = None,
        origin_date: date | None = None,
        client: BriefChatClient | None = None,
        commit: bool = True,
        now: datetime | None = None,
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

        analysis = (
            await self._owned_analysis(player, analysis_id) if analysis_id is not None else None
        )

        # ``now`` is injectable because the propose gate and the daily cap are
        # both anchored to Mark's local day (179.3/179.4); a test that cannot
        # name "today" cannot exercise either.
        now = now or _utcnow()
        local_today = local_date(now, player.timezone)
        await self._enforce_daily_cap(player, local_today)

        resolved_origin_kind = (
            _ANALYSIS_ORIGINS.get(analysis.analysis_type, "general")
            if analysis is not None and origin_kind is None
            else normalize_origin_kind(origin_kind)
        )
        origin = CoachOrigin(kind=resolved_origin_kind, subject_date=origin_date)

        prior_rows = await self._recent_messages(player.id, limit=MAX_HISTORY_TURNS_IN_PROMPT * 2)
        prior_messages = [{"role": row.role, "content": row.content} for row in prior_rows]

        # Batch 178.2: assembled now, not frozen at read time, so a ride
        # completed or a plan edited after the read is visible to this answer.
        context = await ChatContextService(self.session).build(
            player, analysis, asked_at_utc=now, origin=origin
        )
        system_prompt = _build_system_prompt(
            analysis=analysis,
            origin=origin,
            local_today=local_today,
            app_state=context.app_state,
            adjustable_workout_id=context.adjustable_workout_id,
        )
        chat_client = client or AnthropicBriefChatClient()
        async with workload_slot(workload="anthropic", user_id=player.id):
            answer = await chat_client.generate(
                system_prompt=system_prompt,
                user_prompt=cleaned,
                prior_messages=prior_messages,
            )
        answer_for_mark, model_offered_proposal = _strip_proposal_marker(answer)

        # Batch 179.3 asks whether there is a live workout to adjust today.
        # Batch 202.3 adds the answer marker so a keyword like "harder" cannot
        # attach an affordance when the coach refused or answered something else.
        proposed_id = (
            context.adjustable_workout_id
            if _wants_adjustment(cleaned) and model_offered_proposal
            else None
        )

        user_message = BriefMessage(
            user_id=player.id,
            analysis_id=analysis_id,
            origin_kind=resolved_origin_kind,
            origin_date=origin_date,
            role=ROLE_USER,
            content=cleaned,
            created_utc=now,
        )
        assistant_message = BriefMessage(
            user_id=player.id,
            analysis_id=analysis_id,
            origin_kind=resolved_origin_kind,
            origin_date=origin_date,
            role=ROLE_ASSISTANT,
            content=answer_for_mark,
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

    async def _enforce_daily_cap(self, player: Profile, local_today: date) -> None:
        since = day_start_utc(local_today, player.timezone)
        asked_today = await self.session.scalar(
            select(func.count())
            .select_from(BriefMessage)
            .where(
                BriefMessage.user_id == player.id,
                BriefMessage.role == ROLE_USER,
                BriefMessage.created_utc >= since,
            )
        )
        if (asked_today or 0) >= MAX_USER_TURNS_PER_DAY:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"You've asked {MAX_USER_TURNS_PER_DAY} questions today. "
                    "Pick it up tomorrow, or note it at your next check-in."
                ),
            )


def _build_system_prompt(
    *,
    analysis: Analysis | None,
    origin: CoachOrigin,
    local_today: date,
    app_state: dict[str, Any],
    adjustable_workout_id: uuid.UUID | None,
) -> str:
    parts = [SYSTEM_PROMPT]
    if analysis is not None:
        parts.append(_read_description(analysis))
    else:
        parts.append(_origin_description(origin, local_today=local_today))
    parts.append(_capability_instruction(adjustable_workout_id))
    if analysis is not None:
        parts.append(f"What you wrote in that read:\n{analysis.output_markdown}")
        parts.append(
            "Mark's information behind that read, as it stood when you wrote it:\n"
            f"{_packet_json(analysis.context_packet)}"
        )
    parts.append(f"Where things stand right now:\n{app_state_json(app_state)}")
    return "\n\n".join(parts)


def _packet_json(context_packet: dict[str, Any]) -> str:
    return json.dumps(
        _packet_without_stored_system_prompt(context_packet),
        ensure_ascii=True,
        sort_keys=True,
        default=str,
    )


def _strip_proposal_marker(answer: str) -> tuple[str, bool]:
    if PROPOSAL_MARKER not in answer:
        return answer, False
    return answer.replace(PROPOSAL_MARKER, "").strip(), True


def _packet_without_stored_system_prompt(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if key == "system" and isinstance(item, str):
                cleaned["systemHash"] = prompt_system_hash(item)
                continue
            cleaned[key] = _packet_without_stored_system_prompt(item)
        return cleaned
    if isinstance(value, list):
        return [_packet_without_stored_system_prompt(item) for item in value]
    return value
