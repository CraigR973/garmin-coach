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
import re
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
    generate_anthropic_text_with_tools,
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
    RECORD_CONTRADICTION_RULE,
    floors_sentence,
    internal_vocabulary_hits,
)
from src.services.coach_tools import COACH_TOOLS, CoachToolbox
from src.services.interval_workout_editor import (
    MAX_POWER_PCT,
    MAX_REPEATS,
    MAX_REST_DURATION_SEC,
    MAX_WORK_DURATION_SEC,
    MIN_POWER_PCT,
    MIN_REPEATS,
    MIN_REST_DURATION_SEC,
    MIN_WORK_DURATION_SEC,
    PROPOSED_BLOCK_FIELDS,
    IntervalEditorSnapshot,
    block_from_proposal,
    block_to_source,
    format_interval_block,
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
    "PROPOSAL_MARKER_CLOSE",
    "PROPOSAL_MARKER_OPEN",
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

# Batch 260: v14 names the three new past-data capabilities together. Tools
# render before the cached prefix, so shipping them separately would invalidate
# the whole request cache three times; the closed capability enumeration must
# move with the tool definitions once.
# Batch 259: v13 tells the coach a session lookup can be narrowed by Garmin type.
# Batch 257: v12 tells the coach it can go and fetch what it does not hold. The
# same reasoning that forced v10 and v11 forces this one — the enumeration of
# what the coach has is closed and the model reads it as closed (Batch 238
# measured that on the morning brief) — and a capability is closed the same way:
# tool definitions alone put the tools in reach, but a coach that has spent
# months being told to say "that is not in front of me" will keep saying it.
# Chat regenerates nothing on a bump (`prompt_artifacts`: UNFILTERED, "a past
# answer stays what was said"), so this withdraws no stored artifact.
# Batch 289: v16 names the week as the mornings left it among what the coach holds
# (the enumeration is closed, so a section it is not told about reads as absent),
# and adds Craig's rule that the record decides when Mark and the record disagree.
# UNFILTERED, so this withdraws no stored artifact.
PROMPT_VERSION = "coach-chat-v16-2026-09-26"
#: Batch 264: the marker now carries the change. It was a bare flag meaning "I
#: offered something"; the offer itself lived only in prose, so the app could
#: never act on it. ``brief_chat`` is UNFILTERED in ``prompt_artifacts`` with no
#: analysis types, so this bump withdraws no stored artifact.
PROPOSAL_MARKER_OPEN = "[[PROPOSE_WORKOUT_ADJUSTMENT "
PROPOSAL_MARKER_CLOSE = "]]"
#: Matches the marker with or without a payload, so a v14-shaped bare marker is
#: still stripped from Mark's copy rather than shown to him.
_PROPOSAL_MARKER_PATTERN = re.compile(
    r"\[\[PROPOSE_WORKOUT_ADJUSTMENT\s*(?P<payload>\{.*?\})?\s*\]\]",
    re.DOTALL,
)
#: The two states a turn's offer can be in. There is no third: an answer that
#: made no offer carries no change at all.
STATUS_PROPOSED = "proposed"
STATUS_UNAVAILABLE = "unavailable"

SYSTEM_PROMPT = f"""You are CheckMark, Mark's coach, talking with him.

You have where the app stands right now in front of you - his week ahead, what
each morning read of the past week did to his sessions and whether he approved
the change, his measured trend series, his latest review conclusions, his recent
sessions and sleep, today's plan, everything he logged in his own check-ins
today, including what he ate and how he set his bedroom up, his own profile and
rules and protocols, today's readiness and body-battery reading, last night's
bedroom climate and the weather around it, and his own measured baseline bands -
and, when he asked from one of your reads, that read and the information it was
written from. Use all of it. If the answer to his
question is something the app has already worked out, give him that answer
rather than telling him you cannot see it.

When what he asks about is outside what you are holding, look it up before you
answer. You can fetch his recorded sleep and bedroom climate for any range of
nights; his Garmin wake recovery readings, completed sessions (narrowed to one
Garmin session type when useful), and prescribed workouts for any range of
dates; the check-ins he wrote on any past day; and any earlier read you wrote
for him. Reach for a lookup when the question turns on a specific night, an
older recovery reading or session, what was prescribed versus completed,
something he told you before today, or what you said on a particular day -
"that is not in front of me" is the wrong answer when you can go and get it.
Ask for everything you need in one go rather than one thing at a time. If a
lookup comes back empty or fails, say so plainly and answer from what you do
have; never fill the gap with a number you did not read. A night with no bedroom
readings is missing data, not evidence that the room was fine. If it says it was
truncated, its rows are only part of the requested range: say that limitation
rather than treating them as the whole period.

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

{RECORD_CONTRADICTION_RULE}

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
        toolbox: CoachToolbox | None = None,
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
        toolbox: CoachToolbox | None = None,
    ) -> str:
        """One answer, with or without the lookups (Batch 257).

        ``toolbox is None`` keeps the exact single-call path every question took
        before this batch — same function, same payload — so the tool loop is one
        argument away from being switched off if it ever misbehaves in front of
        Mark, rather than a rewrite to back out.
        """
        if not self.api_key:
            raise BriefChatError("ANTHROPIC_API_KEY is not configured.")
        if toolbox is None:
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
        result = await generate_anthropic_text_with_tools(
            api_key=self.api_key,
            model_name=self.model_name,
            max_tokens=self.max_tokens,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            prior_messages=list(prior_messages),
            thinking=self.thinking,
            effort=self.effort,
            error_cls=BriefChatError,
            tools=COACH_TOOLS,
            execute_tool=toolbox.execute,
        )
        if result.tool_uses:
            # 257.6: chat runs in-request, so the cost of a lookup is time Mark
            # spends waiting. Logged per answer rather than inferred, so the cap
            # can be tuned from what he actually triggers.
            log.info(
                "coach_chat_used_tools",
                tool_uses=result.tool_uses,
                api_calls=result.api_calls,
            )
        return result.output_markdown


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@dataclass(frozen=True)
class BriefChatTurn:
    user_message: BriefMessage
    assistant_message: BriefMessage


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


def _capability_instruction(adjustable_set: IntervalEditorSnapshot | None) -> str:
    """What the coach may offer, in the exact terms the app can carry out.

    Batch 179.3 keyed this on whether a live workout exists today. Batch 264
    keys it on what can actually be *done* to that workout, because the previous
    wording bounded nothing: on 2026-09-08 the coach told Mark it would queue a
    35s/25s change and the affordance beneath it re-proposed the unchanged
    40s/20s session, which was the only thing it had ever been able to do. The
    enumeration below is closed on purpose — Batch 238 measured that the model
    reads a capability list as closed — and the five numbers are the five the
    interval editor already validates.
    """
    if adjustable_set is None:
        return (
            "Capability right now: there is no session you can change today - it is rest, "
            "away, already done, or not an indoor bike session. Do not say the app can "
            "propose, queue, confirm, upload, or change a workout from this conversation."
        )
    current = adjustable_set.current
    sets = len(adjustable_set.editable_step_indices)
    matching = (
        f" Today's session repeats that set {sets} times around a fixed recovery, and a "
        "change moves every matching set together, so give the numbers for ONE set."
        if sets > 1
        else ""
    )
    fixed = ", ".join(step.label for step in adjustable_set.fixed_steps) or "none"
    return (
        "Capability right now: today's plan holds a live indoor bike session whose main "
        f"interval set is {format_interval_block(current)}.{matching} You can offer to "
        "change that set, and only that set: how many intervals, how long each effort is, "
        "what percentage of FTP it is ridden at, how long the recovery is, and what "
        "percentage of FTP the recovery is. Everything else is held exactly as prescribed "
        f"({fixed}), including cadence, and you cannot move the session to another day, "
        "change what kind of session it is, or alter anything outside that one set.\n\n"
        "If Mark asks for a change you can express in those five numbers and your answer "
        "offers it to him, end the answer with the marker on its own line, carrying the "
        "numbers the session would have AFTER the change:\n"
        f'{PROPOSAL_MARKER_OPEN}{{"repeat": {current.repeat}, '
        f'"workSec": {current.work.duration_sec}, "workPct": {current.work.power_pct}, '
        f'"restSec": {current.rest.duration_sec}, "restPct": {current.rest.power_pct}}}'
        f"{PROPOSAL_MARKER_CLOSE}\n"
        f"Whole numbers only, within these bounds: repeats {MIN_REPEATS}-{MAX_REPEATS}, "
        f"effort {MIN_WORK_DURATION_SEC}-{MAX_WORK_DURATION_SEC} seconds, recovery "
        f"{MIN_REST_DURATION_SEC}-{MAX_REST_DURATION_SEC} seconds, both percentages "
        f"{MIN_POWER_PCT}-{MAX_POWER_PCT}. The app removes the marker before Mark sees it "
        "and shows him the change with its before and after; it reaches his plan and his "
        "turbo only when he confirms it there.\n\n"
        "So describe what you are putting in front of him to confirm, and never say you "
        "have queued, applied, changed, scheduled or uploaded anything - you have not, and "
        "he has not confirmed yet. If what he wants cannot be expressed in those five "
        "numbers, say plainly that it is not a change you can make here, and what he would "
        "have to do instead; do not offer it anyway."
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
            adjustable_set=context.adjustable_interval_set,
        )
        chat_client = client or AnthropicBriefChatClient()
        async with workload_slot(workload="anthropic", user_id=player.id):
            answer = await chat_client.generate(
                system_prompt=system_prompt,
                user_prompt=cleaned,
                prior_messages=prior_messages,
                # Batch 257: the lookups, bound to *this* profile. The toolbox
                # holds the authenticated player, so no tool can be executed
                # against a ``user_id`` this request did not authenticate — the
                # scoping cannot be forgotten at a call site because no call site
                # supplies it.
                toolbox=CoachToolbox(self.session, player),
            )
        answer_for_mark, payload, model_offered_proposal = _extract_proposal(answer)

        # Batch 264 retires the keyword gate on Mark's own words. It was a proxy
        # for "he asked for a change" and it was wrong in both directions: on
        # 2026-09-08 it fired on *"had to slightly adjust last week"*, a
        # retrospective clause, and it would have blocked a plain "can we do
        # 35/25 instead?" because "instead" is not one of its ten words. What
        # replaces it is a stronger deterministic gate than any wording test —
        # the offer must resolve to a validated block that differs from what
        # today's live plan row actually prescribes.
        proposed_change = (
            _proposed_change(
                payload=payload,
                adjustable_set=context.adjustable_interval_set,
                workout_id=context.adjustable_workout_id,
                workout_version=context.adjustable_workout_version,
            )
            if model_offered_proposal
            else None
        )
        proposed_id = (
            context.adjustable_workout_id
            if proposed_change is not None and proposed_change["status"] == STATUS_PROPOSED
            else None
        )
        if proposed_change is not None and proposed_change["status"] == STATUS_UNAVAILABLE:
            log.info(
                "coach offered a change the app cannot carry",
                profile_id=str(player.id),
                reason=proposed_change["reason"],
                payload=payload,
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
            proposed_interval_change=proposed_change,
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
    adjustable_set: IntervalEditorSnapshot | None,
) -> str:
    return "\n\n".join(
        (
            _build_system_prompt_prefix(
                analysis=analysis,
                origin=origin,
                local_today=local_today,
                adjustable_set=adjustable_set,
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
    adjustable_set: IntervalEditorSnapshot | None,
) -> list[AnthropicSystemTextBlock]:
    return [
        {
            "type": "text",
            "text": _build_system_prompt_prefix(
                analysis=analysis,
                origin=origin,
                local_today=local_today,
                adjustable_set=adjustable_set,
            ),
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": _app_state_system_text(app_state),
            # Batch 257.4 made the live block a cache breakpoint because a tool
            # round trip reads it at 0.1x rather than paying for it again. Batch
            # 258 moves the one per-question field out of this block, so the
            # same cache entry also survives a follow-up question.
            #
            # The 2026-09-06 measurement showed 22,791-24,246 tokens here (93%
            # of an unanchored question). It was already a win within a lookup
            # answer: round 2 read 25,942 tokens from cache. It was not yet a
            # win across questions because ``assembledAtUtc`` sorted first in
            # the JSON and made every rebuilt block differ at character 35.
            #
            # Cache writes still cost 1.25x, but once a follow-up is a cache read
            # the write amortises independently of whether either answer uses a
            # tool. The old +0.25x/-0.65x tool-rate break-even therefore no
            # longer describes this block. The five-minute TTL remains deliberate:
            # 74 of 141 questions were inside it; a one-hour entry costs 2x to
            # write and needs three requests before it wins.
            #
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": _assembled_at_system_text(app_state),
        },
    ]


def _build_system_prompt_prefix(
    *,
    analysis: Analysis | None,
    origin: CoachOrigin,
    local_today: date,
    adjustable_set: IntervalEditorSnapshot | None,
) -> str:
    parts = [SYSTEM_PROMPT]
    if analysis is not None:
        parts.append(_read_description(analysis))
    else:
        parts.append(_origin_description(origin, local_today=local_today))
    parts.append(_capability_instruction(adjustable_set))
    if analysis is not None:
        parts.append(f"What you wrote in that read:\n{analysis.output_markdown}")
        parts.append(
            "Mark's information behind that read, as it stood when you wrote it:\n"
            f"{_packet_json(analysis.context_packet)}"
        )
    return "\n\n".join(parts)


def _app_state_system_text(app_state: dict[str, Any]) -> str:
    cacheable_state = {key: value for key, value in app_state.items() if key != "assembledAtUtc"}
    return f"Where things stand right now:\n{app_state_json(cacheable_state)}"


def _assembled_at_system_text(app_state: dict[str, Any]) -> str:
    """Keep volatile assembly metadata after every cache breakpoint (Batch 258.1)."""

    assembled_at = app_state.get("assembledAtUtc")
    return f"This context was assembled at UTC: {assembled_at}."


def _packet_json(context_packet: dict[str, Any]) -> str:
    return json.dumps(
        _packet_without_stored_system_prompt(context_packet),
        ensure_ascii=True,
        sort_keys=True,
        default=str,
    )


#: Why a change the coach offered could not be put in front of Mark. Plain,
#: closed, and rendered by the web as a sentence — never an internal token
#: (:data:`NO_PLUMBING_RULE`), and never silence, because a claim with nothing
#: under it is the 2026-09-08 failure itself.
UNAVAILABLE_NOT_EDITABLE = "not_editable"
UNAVAILABLE_MALFORMED = "malformed"
UNAVAILABLE_OUT_OF_RANGE = "out_of_range"
UNAVAILABLE_UNCHANGED = "unchanged"


def _extract_proposal(answer: str) -> tuple[str, str | None, bool]:
    """Split Mark's copy from the change the answer carries.

    Returns the answer with the marker removed, the raw payload when there was
    one, and whether a marker was present at all. A v14-shaped bare marker is
    still removed — Mark must never see the plumbing — but carries no change, so
    it is reported as an offer with nothing under it rather than as no offer.
    """
    match = _PROPOSAL_MARKER_PATTERN.search(answer)
    if match is None:
        return answer, None, False
    cleaned = _PROPOSAL_MARKER_PATTERN.sub("", answer).strip()
    return cleaned, match.group("payload"), True


def _proposed_change(
    *,
    payload: str | None,
    adjustable_set: IntervalEditorSnapshot | None,
    workout_id: uuid.UUID | None,
    workout_version: int | None,
) -> dict[str, Any]:
    """The change to put in front of Mark, or an honest reason there is none.

    Every check here is deterministic and run against live plan rows: the model
    supplies five numbers and nothing else decides. ``validate_interval_block``
    bounds each leg exactly as it does for a number typed into the editor, so a
    coach-composed change is not a wider authority than Mark's own.
    """
    if adjustable_set is None or workout_id is None:
        return {"status": STATUS_UNAVAILABLE, "reason": UNAVAILABLE_NOT_EDITABLE}
    if payload is None:
        return {"status": STATUS_UNAVAILABLE, "reason": UNAVAILABLE_MALFORMED}
    try:
        parsed = json.loads(payload)
    except ValueError:
        return {"status": STATUS_UNAVAILABLE, "reason": UNAVAILABLE_MALFORMED}
    # A payload of the wrong shape and a payload of the wrong size are different
    # answers to Mark: one is the app failing to read an offer, the other is the
    # offer being outside what this editor may set.
    if not isinstance(parsed, dict) or any(field not in parsed for field in PROPOSED_BLOCK_FIELDS):
        return {"status": STATUS_UNAVAILABLE, "reason": UNAVAILABLE_MALFORMED}
    current = adjustable_set.current
    try:
        block = block_from_proposal(parsed, current=current)
    except HTTPException:
        return {"status": STATUS_UNAVAILABLE, "reason": UNAVAILABLE_OUT_OF_RANGE}
    if block == current:
        return {"status": STATUS_UNAVAILABLE, "reason": UNAVAILABLE_UNCHANGED}
    return {
        "status": STATUS_PROPOSED,
        "plannedWorkoutId": str(workout_id),
        "plannedWorkoutVersion": workout_version,
        "matchingSets": len(adjustable_set.editable_step_indices),
        "current": block_to_source(current),
        "changeTo": block_to_source(block),
        "currentLabel": format_interval_block(current),
        "changeToLabel": format_interval_block(block),
        "heldConstant": [step.label for step in adjustable_set.fixed_steps],
    }


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
