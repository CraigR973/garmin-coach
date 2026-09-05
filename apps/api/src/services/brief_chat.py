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

import structlog
from fastapi import HTTPException, status
from sqlalchemy import String, and_, case, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models.coaching import Analysis, BriefMessage
from src.models.profile import Profile
from src.services.anthropic_text import (
    AnthropicSystemPrompt,
    AnthropicSystemTextBlock,
    configured_effort,
    configured_thinking,
    generate_anthropic_text,
)
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
from src.services.learned_context import LEARNED_CONTEXT_PROMPT_GUARDRAIL
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
    "ThreadPage",
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

# Batch 256: v11 adds Mark's own rules, today's readiness, last night's bedroom
# and his personal bands. The list is closed and the model reads it as closed —
# Batch 238 proved that on the morning brief, where a four-item sentence written
# when the brief had four sections silently deleted the other four, and Batch 255
# bumped v9 → v10 for exactly this reason. Handing the block four new sections
# without naming them here would be that defect inverted: given the data, told it
# did not have it. Chat regenerates nothing on a bump (`prompt_artifacts`:
# UNFILTERED, "a past answer stays what was said"), so this withdraws no stored
# artifact.
PROMPT_VERSION = "coach-chat-v11-2026-09-05"
PROPOSAL_MARKER = "[[PROPOSE_WORKOUT_ADJUSTMENT]]"

SYSTEM_PROMPT = f"""You are CheckMark, Mark's coach, talking with him.

You have where the app stands right now in front of you - his week ahead, his
measured trend series, his latest review conclusions, his recent sessions and
sleep, today's plan, everything he logged in his own check-ins today, including
what he ate and how he set his bedroom up, his own profile and rules and
protocols, today's readiness and body-battery reading, last night's bedroom
climate and the weather around it, and his own measured baseline bands - and,
when he asked from one of your reads, that read and the information it was
written from. Use all of it. If the answer to his
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

# Batch 256: the conversation now carries `knowledgeBase.learnedContext`, which
# is confirmed user-authored memory presented as quoted, untrusted data. The
# five generated-read prompts have appended this guardrail since Batch 151; this
# one had not, because it never held that field in its own block — while already
# receiving it, on every anchored question, inside the read's frozen record. 256
# makes it universal, so the gap closes here.
SYSTEM_PROMPT = "\n\n".join((SYSTEM_PROMPT, LEARNED_CONTEXT_PROMPT_GUARDRAIL))

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
        system_prompt: AnthropicSystemPrompt,
        user_prompt: str,
        prior_messages: list[dict[str, str]],
    ) -> str: ...


class AnthropicBriefChatClient:
    def __init__(self, *, api_key: str | None = None, model_name: str | None = None) -> None:
        self.api_key = api_key if api_key is not None else settings.anthropic_api_key
        self.model_name = model_name or settings.anthropic_model
        self.max_tokens = settings.anthropic_chat_max_tokens
        self.thinking = configured_thinking()
        self.effort = configured_effort()

    async def generate(
        self,
        *,
        system_prompt: AnthropicSystemPrompt,
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
            thinking=self.thinking,
            effort=self.effort,
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


log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ThreadPage:
    """One window of the coach conversation, plus whether an older one exists."""

    messages: list[BriefMessage]
    has_more: bool


class BriefChatService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _assert_owned_analysis(self, player: Profile, analysis_id: uuid.UUID) -> None:
        """The ownership half of ``_owned_analysis``, without loading the row.

        Same 404-for-both rule (DS190-08) and the same operator log; it simply
        selects the one column the question is about.
        """
        owner = await self.session.scalar(
            select(Analysis.user_id).where(Analysis.id == analysis_id)
        )
        if owner is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Read not found")
        if owner != player.id:
            log.info(
                "brief chat anchor belongs to another user",
                analysis_id=str(analysis_id),
                requesting_user_id=str(player.id),
            )
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Read not found")

    async def _owned_analysis(self, player: Profile, analysis_id: uuid.UUID) -> Analysis:
        """404 for both an absent and a foreign anchor (DS190-08).

        An authenticated second user who obtains or guesses a UUID must not be
        able to distinguish "does not exist" from "exists but is not yours" —
        UUIDv4 entropy makes exploiting that split unlikely, but the split
        itself was avoidable disclosure. The distinction is kept only in the
        structured log, for operator diagnosis.
        """
        analysis = await self.session.scalar(select(Analysis).where(Analysis.id == analysis_id))
        if analysis is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Read not found")
        if analysis.user_id != player.id:
            log.info(
                "brief chat anchor belongs to another user",
                analysis_id=str(analysis_id),
                requesting_user_id=str(player.id),
            )
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Read not found")
        return analysis

    async def history(self, player: Profile, analysis_id: uuid.UUID) -> list[BriefMessage]:
        """The turns asked from one read.

        Kept exactly as it was so the inline chat on a read still shows that
        read's own exchange rather than the whole conversation. ``user_id`` is
        filtered redundantly alongside ``analysis_id`` (DS190-09): normal
        writes always set both from the same ownership check, so no current
        HTTP path can produce a mismatched row, but a future writer or repair
        script should not be able to make one visible here.
        """
        # Batch 253 (DS237-17): ``history`` discards the row entirely, so it asks
        # only the ownership question. ``select(Analysis)`` materialised
        # ``context_packet`` and ``raw_response`` — ~6.2 KB of JSON text per row —
        # to answer a boolean.
        await self._assert_owned_analysis(player, analysis_id)
        rows = (
            (
                await self.session.execute(
                    select(BriefMessage)
                    .where(
                        BriefMessage.analysis_id == analysis_id,
                        BriefMessage.user_id == player.id,
                    )
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
        before: uuid.UUID | None = None,
    ) -> ThreadPage:
        """One window of the rolling conversation, oldest first.

        Batch 254 (UX241-05): the window used to be all there was. The coach held
        **276** messages and showed 60, so **216** were unreachable — up from 22 at
        Batch 192 and growing at roughly four a day, which means the window keeps
        receding. Everything Mark asked before roughly mid-August was gone from his
        view: he could not go back and find what the coach told him about a session
        or re-read an explanation, while the app *still used* that history. There
        was a gap between what the coach remembered and what Mark could see it
        remembering.

        ``before`` is the id of the oldest message already on screen; the page
        returned is the window immediately older than it. ``has_more`` says whether
        another page exists, so the client shows the control only when it leads
        somewhere.
        """
        anchor = await self._message_anchor(player.id, before) if before else None
        rows = await self._recent_messages(player.id, limit=limit, before=anchor)
        oldest = rows[0] if rows else None
        has_more = await self._exists_before(player.id, self._sort_key(oldest)) if oldest else False
        return ThreadPage(messages=rows, has_more=has_more)

    @staticmethod
    def _sort_key(row: BriefMessage) -> tuple[datetime, int, str]:
        return (row.created_utc, 0 if row.role == ROLE_USER else 1, str(row.id))

    async def _message_anchor(
        self, user_id: uuid.UUID, message_id: uuid.UUID
    ) -> tuple[datetime, int, str] | None:
        """The sort position of a message the caller already has.

        Scoped to the caller's own rows, so a foreign or invented id simply pages
        from the newest end rather than disclosing that the id exists.
        """
        row = await self.session.scalar(
            select(BriefMessage).where(
                BriefMessage.id == message_id, BriefMessage.user_id == user_id
            )
        )
        return self._sort_key(row) if row is not None else None

    async def _exists_before(self, user_id: uuid.UUID, key: tuple[datetime, int, str]) -> bool:
        found = await self.session.scalar(
            select(BriefMessage.id)
            .where(BriefMessage.user_id == user_id, *self._older_than(key))
            .limit(1)
        )
        return found is not None

    @staticmethod
    def _older_than(key: tuple[datetime, int, str]) -> tuple[Any, ...]:
        """Rows strictly before ``key`` in the thread's own three-part order.

        The order is (created_utc, role, id) because a question and its answer
        share a timestamp; paging on the timestamp alone would drop or repeat one
        of the pair at every boundary.
        """
        created, role_rank, row_id = key
        rank = case(
            (BriefMessage.role == ROLE_USER, 0),
            (BriefMessage.role == ROLE_ASSISTANT, 1),
            else_=2,
        )
        return (
            or_(
                BriefMessage.created_utc < created,
                and_(
                    BriefMessage.created_utc == created,
                    or_(
                        rank < role_rank,
                        and_(rank == role_rank, cast(BriefMessage.id, String) < row_id),
                    ),
                ),
            ),
        )

    async def _recent_messages(
        self,
        user_id: uuid.UUID,
        *,
        limit: int,
        before: tuple[datetime, int, str] | None = None,
    ) -> list[BriefMessage]:
        query = (
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
        if before is not None:
            query = query.where(*self._older_than(before))
        newest_first = (await self.session.execute(query)).scalars().all()
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
        system_prompt = _build_cached_system_prompt(
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
    return "\n\n".join(
        (
            _build_system_prompt_prefix(
                analysis=analysis,
                origin=origin,
                local_today=local_today,
                adjustable_workout_id=adjustable_workout_id,
            ),
            _app_state_system_text(app_state),
        )
    )


def _build_cached_system_prompt(
    *,
    analysis: Analysis | None,
    origin: CoachOrigin,
    local_today: date,
    app_state: dict[str, Any],
    adjustable_workout_id: uuid.UUID | None,
) -> list[AnthropicSystemTextBlock]:
    return [
        {
            "type": "text",
            "text": _build_system_prompt_prefix(
                analysis=analysis,
                origin=origin,
                local_today=local_today,
                adjustable_workout_id=adjustable_workout_id,
            ),
            "cache_control": {"type": "ephemeral"},
        },
        {"type": "text", "text": _app_state_system_text(app_state)},
    ]


def _build_system_prompt_prefix(
    *,
    analysis: Analysis | None,
    origin: CoachOrigin,
    local_today: date,
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
    return "\n\n".join(parts)


def _app_state_system_text(app_state: dict[str, Any]) -> str:
    return f"Where things stand right now:\n{app_state_json(app_state)}"


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
