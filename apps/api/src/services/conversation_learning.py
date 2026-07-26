"""Extract-and-confirm learning from user-authored coach conversations.

Batch 151 deliberately separates three boundaries:

* extraction reads recent user-authored chat, check-in notes, and corrections;
* a deterministic filter rejects transient, coercive, or verdict/rules content;
* accepted proposals can write only the versioned ``learned_context`` KB section.

The model therefore proposes memory; it never edits retained state or coaching
logic itself.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal, Protocol

from fastapi import HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models.coaching import (
    Analysis,
    BriefMessage,
    ConversationLearningProposal,
    Feedback,
    KnowledgeBase,
    ManualEntry,
)
from src.models.profile import Profile
from src.services.anthropic_text import generate_anthropic_text
from src.services.workload_budget import workload_slot

LEARNED_CONTEXT_SECTION = "learned_context"
SOURCE_WINDOW_DAYS = 30
MAX_SOURCES = 60
MAX_CANDIDATES = 12
MAX_STATEMENT_LENGTH = 500

KIND_FACT = "fact"
KIND_PREFERENCE = "preference"
KIND_TERMINOLOGY = "terminology"
KIND_RECURRING_THEME = "recurring_theme"
LearningKind = Literal["fact", "preference", "terminology", "recurring_theme"]

STATUS_PENDING = "pending"
STATUS_ACCEPTED = "accepted"
STATUS_REJECTED = "rejected"

SYSTEM_PROMPT = """You distil durable, user-confirmable memory for CheckMark,
Mark's private fitness and sleep coach.

Return strict JSON only:
{"candidates":[{"kind":"fact|preference|terminology|recurring_theme",
"statement":"one concise third-person statement",
"destination":"learned_context",
"evidence":[{"source_id":"an exact supplied source id",
"quote":"a short verbatim quote from that source"}]}]}

Keep only standing context likely to matter again: stable facts, explicit
preferences, personal terminology/equipment names, schedule constraints, stated
goals, chronic niggles, or genuinely recurring patterns. Drop today's mood,
fatigue, soreness, RPE, one-off events, questions, pleasantries, and assistant
claims. A recurring theme needs repeated evidence or explicit frequency language
such as "always", "usually", "often", or "every".

Never extract a desired verdict, pressure to reassure, coaching thresholds,
Green/Amber/Red rules, Red/VO2 rules, data-quality/reliability rules, power-meter
rules, or instructions to ignore objective data. Never infer beyond the supplied
user-authored text. Every candidate needs at least one exact, verbatim evidence
quote. The only allowed destination is learned_context. If nothing qualifies,
return {"candidates":[]}."""


class ConversationLearningError(Exception):
    pass


@dataclass(frozen=True)
class LearningSource:
    source_id: str
    source_type: str
    source_date: date
    text: str
    occurred_at_utc: datetime
    analysis_id: uuid.UUID | None = None
    analysis_type: str | None = None

    def to_prompt(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "source_type": self.source_type,
            "source_date": self.source_date.isoformat(),
            "analysis_id": str(self.analysis_id) if self.analysis_id else None,
            "analysis_type": self.analysis_type,
            "text": self.text,
        }


class ExtractedEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    source_id: str = Field(min_length=1, max_length=120)
    quote: str = Field(min_length=1, max_length=300)


class ExtractedCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    kind: LearningKind
    statement: str = Field(min_length=5, max_length=MAX_STATEMENT_LENGTH)
    destination: Literal["learned_context"]
    evidence: list[ExtractedEvidence] = Field(min_length=1, max_length=4)


class ExtractionEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    candidates: list[ExtractedCandidate] = Field(default_factory=list, max_length=MAX_CANDIDATES)


class ConversationLearningClient(Protocol):
    async def generate(
        self,
        *,
        sources: list[LearningSource],
        existing_statements: list[str],
    ) -> str: ...


class AnthropicConversationLearningClient:
    def __init__(self, *, api_key: str | None = None, model_name: str | None = None) -> None:
        self.api_key = api_key if api_key is not None else settings.anthropic_api_key
        self.model_name = model_name or settings.anthropic_model
        self.max_tokens = 1800

    async def generate(
        self,
        *,
        sources: list[LearningSource],
        existing_statements: list[str],
    ) -> str:
        if not self.api_key:
            raise ConversationLearningError("ANTHROPIC_API_KEY is not configured.")
        result = await generate_anthropic_text(
            api_key=self.api_key,
            model_name=self.model_name,
            max_tokens=self.max_tokens,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=json.dumps(
                {
                    "existing_memory_statements": existing_statements,
                    "user_authored_sources": [source.to_prompt() for source in sources],
                },
                ensure_ascii=True,
                sort_keys=True,
            ),
            error_cls=ConversationLearningError,
        )
        return result.output_markdown


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _normalise(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.casefold()).split())


_FORBIDDEN_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bverdict\b",
        r"\b(?:green|amber|red)\s+(?:day|verdict|classification)\b",
        r"\b(?:green|amber|red)\s+(?:recommendation|status|rating)s?\b",
        r"\b(?:always|just)\s+(?:say|tell|give|mark).*(?:fine|green|ready)\b",
        r"\btell me (?:i am|i'm) fine\b",
        r"\bignore (?:the )?(?:data|metrics|readiness|hrv|sleep)\b",
        r"\bdata[- ]quality\b",
        r"\breliab(?:le|ility)\s+(?:from|since|rule)\b",
        r"\bleft\s*/?\s*right power balance\b",
        r"\bsingle[- ]sided (?:power )?meter\b",
        r"\b(?:spo2|hrv).*\breliab(?:le|ility)\b",
        r"\bwrist.*\bstrength.*\brecovery\b",
        r"\bexcel.*\bduration\b",
        r"\bred.*\bvo2\b",
        r"\bvo2\b.*\bred\b",
        r"\b(?:verdict|readiness|hrv|sleep|data|score)\s+thresholds?\b",
    )
)

_TRANSIENT_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(today|tonight|this morning|this afternoon|right now|currently)\b",
        r"\b(i am|i'm|i feel|felt)\s+(great|fine|tired|fatigued|sore|rough|ill)\b",
        r"\b(?:my )?rpe (?:was|is)?\s*\d",
        r"\bone[- ]off\b",
    )
)

_DURABLE_CUES = re.compile(
    r"\b(always|usually|normally|often|regularly|every|chronic|recurring|"
    r"long[- ]term|tends? to|prefer|preference|call(?:s|ed)?|known as|goal|"
    r"cannot|can't|avoid|schedule|constraint)\b",
    re.IGNORECASE,
)


def statement_is_durable(statement: str, *, kind: str) -> bool:
    """Pure code-side taxonomy and integrity filter.

    The prompt improves recall; this function is the enforcement boundary and
    also validates user edits before acceptance.
    """
    cleaned = statement.strip()
    if kind not in {
        KIND_FACT,
        KIND_PREFERENCE,
        KIND_TERMINOLOGY,
        KIND_RECURRING_THEME,
    }:
        return False
    if len(cleaned) < 5 or len(cleaned) > MAX_STATEMENT_LENGTH:
        return False
    if any(pattern.search(cleaned) for pattern in _FORBIDDEN_PATTERNS):
        return False
    if any(pattern.search(cleaned) for pattern in _TRANSIENT_PATTERNS):
        return bool(_DURABLE_CUES.search(cleaned))
    return True


def parse_extraction_output(output: str) -> ExtractionEnvelope:
    """Parse the model response as a strict typed object, accepting JSON fences only."""
    cleaned = output.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    try:
        raw = json.loads(cleaned)
        return ExtractionEnvelope.model_validate(raw)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ConversationLearningError("Conversation learning returned invalid JSON.") from exc


def _quote_is_verbatim(quote: str, source_text: str) -> bool:
    normalised_quote = _normalise(quote)
    return bool(normalised_quote) and normalised_quote in _normalise(source_text)


def filter_candidates(
    envelope: ExtractionEnvelope,
    *,
    sources: list[LearningSource],
    existing_statements: list[str],
) -> list[ExtractedCandidate]:
    """Keep only typed, durable candidates with real user-authored evidence."""
    source_by_id = {source.source_id: source for source in sources}
    existing = {_normalise(statement) for statement in existing_statements}
    accepted: list[ExtractedCandidate] = []
    seen: set[str] = set()

    for candidate in envelope.candidates:
        if not statement_is_durable(candidate.statement, kind=candidate.kind):
            continue
        normalised = _normalise(candidate.statement)
        if not normalised or normalised in existing or normalised in seen:
            continue
        if not all(
            evidence.source_id in source_by_id
            and _quote_is_verbatim(evidence.quote, source_by_id[evidence.source_id].text)
            and not any(pattern.search(evidence.quote) for pattern in _FORBIDDEN_PATTERNS)
            for evidence in candidate.evidence
        ):
            continue
        if (
            candidate.kind == KIND_RECURRING_THEME
            and len({evidence.source_id for evidence in candidate.evidence}) < 2
            and not _DURABLE_CUES.search(candidate.statement)
        ):
            continue
        accepted.append(candidate)
        seen.add(normalised)
    return accepted


def _fingerprint(candidate: ExtractedCandidate) -> str:
    evidence_ids = sorted({evidence.source_id for evidence in candidate.evidence})
    payload = json.dumps(
        {
            "kind": candidate.kind,
            "statement": _normalise(candidate.statement),
            "evidence_ids": evidence_ids,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ConversationLearningService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _sources(
        self,
        user_id: uuid.UUID,
        *,
        now: datetime,
    ) -> list[LearningSource]:
        cutoff = now - timedelta(days=SOURCE_WINDOW_DAYS)

        chat_rows = (
            await self.session.execute(
                select(BriefMessage, Analysis)
                .join(Analysis, BriefMessage.analysis_id == Analysis.id)
                .where(
                    BriefMessage.user_id == user_id,
                    BriefMessage.role == "user",
                    BriefMessage.created_utc >= cutoff,
                )
                .order_by(BriefMessage.created_utc.desc())
                .limit(MAX_SOURCES)
            )
        ).all()
        checkin_rows = (
            (
                await self.session.execute(
                    select(ManualEntry)
                    .where(
                        ManualEntry.user_id == user_id,
                        ManualEntry.entry_date >= cutoff.date(),
                        ManualEntry.notes.isnot(None),
                    )
                    .order_by(ManualEntry.entry_at_utc.desc())
                    .limit(MAX_SOURCES)
                )
            )
            .scalars()
            .all()
        )
        correction_rows = (
            await self.session.execute(
                select(Feedback, Analysis)
                .join(Analysis, Feedback.analysis_id == Analysis.id)
                .where(
                    Feedback.user_id == user_id,
                    Feedback.created_utc >= cutoff,
                    Feedback.correction_text.isnot(None),
                )
                .order_by(Feedback.created_utc.desc())
                .limit(MAX_SOURCES)
            )
        ).all()

        sources: list[LearningSource] = []
        for message, analysis in chat_rows:
            text = message.content.strip()
            if text:
                sources.append(
                    LearningSource(
                        source_id=f"chat:{message.id}",
                        source_type="chat",
                        source_date=analysis.subject_date,
                        text=text,
                        occurred_at_utc=message.created_utc,
                        analysis_id=analysis.id,
                        analysis_type=analysis.analysis_type,
                    )
                )
        for entry in checkin_rows:
            text = (entry.notes or "").strip()
            if text:
                linked_analysis = None
                if entry.activity_id is not None:
                    linked_analysis = await self.session.scalar(
                        select(Analysis)
                        .where(
                            Analysis.user_id == user_id,
                            Analysis.activity_id == entry.activity_id,
                        )
                        .order_by(Analysis.generated_at_utc.desc())
                        .limit(1)
                    )
                else:
                    linked_analysis = await self.session.scalar(
                        select(Analysis)
                        .where(
                            Analysis.user_id == user_id,
                            Analysis.analysis_type == "morning",
                            Analysis.subject_date == entry.entry_date,
                        )
                        .order_by(Analysis.generated_at_utc.desc())
                        .limit(1)
                    )
                sources.append(
                    LearningSource(
                        source_id=f"checkin:{entry.id}",
                        source_type="checkin_note",
                        source_date=entry.entry_date,
                        text=text,
                        occurred_at_utc=entry.entry_at_utc,
                        analysis_id=linked_analysis.id if linked_analysis else None,
                        analysis_type=(
                            linked_analysis.analysis_type
                            if linked_analysis
                            else ("post_workout" if entry.activity_id else "morning")
                        ),
                    )
                )
        for feedback, analysis in correction_rows:
            text = (feedback.correction_text or "").strip()
            if text:
                sources.append(
                    LearningSource(
                        source_id=f"correction:{feedback.id}",
                        source_type="correction",
                        source_date=analysis.subject_date,
                        text=text,
                        occurred_at_utc=feedback.created_utc,
                        analysis_id=analysis.id,
                        analysis_type=analysis.analysis_type,
                    )
                )
        sources.sort(key=lambda source: source.occurred_at_utc, reverse=True)
        return sources[:MAX_SOURCES]

    async def _active_learned_context(self, user_id: uuid.UUID) -> KnowledgeBase | None:
        result = await self.session.scalars(
            select(KnowledgeBase).where(
                KnowledgeBase.user_id == user_id,
                KnowledgeBase.section == LEARNED_CONTEXT_SECTION,
                KnowledgeBase.is_active.is_(True),
            )
        )
        return result.one_or_none()

    async def _existing_statements(self, user_id: uuid.UUID) -> list[str]:
        row = await self._active_learned_context(user_id)
        raw_items = row.content.get("items", []) if row is not None else []
        items = raw_items if isinstance(raw_items, list) else []
        accepted = [
            statement
            for item in items
            if isinstance(item, dict)
            and isinstance((statement := item.get("statement")), str)
            and statement.strip()
        ]
        proposals = (
            (
                await self.session.execute(
                    select(ConversationLearningProposal).where(
                        ConversationLearningProposal.user_id == user_id
                    )
                )
            )
            .scalars()
            .all()
        )
        return [
            *accepted,
            *[
                proposal.reviewed_statement or proposal.statement
                for proposal in proposals
                if (proposal.reviewed_statement or proposal.statement).strip()
            ],
        ]

    async def distill(
        self,
        player: Profile,
        *,
        client: ConversationLearningClient | None = None,
        now: datetime | None = None,
    ) -> list[ConversationLearningProposal]:
        observed_at = now or _utcnow()
        sources = await self._sources(player.id, now=observed_at)
        if not sources:
            return []
        existing_statements = await self._existing_statements(player.id)
        extractor = client or AnthropicConversationLearningClient()
        async with workload_slot(workload="anthropic", user_id=player.id):
            output = await extractor.generate(
                sources=sources,
                existing_statements=existing_statements,
            )
        candidates = filter_candidates(
            parse_extraction_output(output),
            sources=sources,
            existing_statements=existing_statements,
        )
        if not candidates:
            return []

        fingerprints = [_fingerprint(candidate) for candidate in candidates]
        existing_fingerprints = set(
            (
                await self.session.execute(
                    select(ConversationLearningProposal.fingerprint).where(
                        ConversationLearningProposal.user_id == player.id,
                        ConversationLearningProposal.fingerprint.in_(tuple(fingerprints)),
                    )
                )
            )
            .scalars()
            .all()
        )
        source_by_id = {source.source_id: source for source in sources}
        created: list[ConversationLearningProposal] = []
        for candidate, fingerprint in zip(candidates, fingerprints, strict=True):
            if fingerprint in existing_fingerprints:
                continue
            evidence_json: list[dict[str, Any]] = []
            for evidence in candidate.evidence:
                source = source_by_id[evidence.source_id]
                evidence_json.append(
                    {
                        "sourceId": source.source_id,
                        "sourceType": source.source_type,
                        "sourceDate": source.source_date.isoformat(),
                        "analysisId": str(source.analysis_id) if source.analysis_id else None,
                        "analysisType": source.analysis_type,
                        "quote": evidence.quote.strip(),
                    }
                )
            row = ConversationLearningProposal(
                user_id=player.id,
                kind=candidate.kind,
                destination=LEARNED_CONTEXT_SECTION,
                statement=candidate.statement.strip(),
                evidence_json=evidence_json,
                fingerprint=fingerprint,
                status=STATUS_PENDING,
            )
            self.session.add(row)
            created.append(row)
        if created:
            await self.session.commit()
            for row in created:
                await self.session.refresh(row)
        return created

    async def proposals(self, player: Profile) -> list[ConversationLearningProposal]:
        rows = (
            (
                await self.session.execute(
                    select(ConversationLearningProposal)
                    .where(ConversationLearningProposal.user_id == player.id)
                    .order_by(ConversationLearningProposal.created_at.desc())
                    .limit(100)
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    async def _owned_pending(
        self,
        player: Profile,
        proposal_id: uuid.UUID,
    ) -> ConversationLearningProposal:
        row = await self.session.scalar(
            select(ConversationLearningProposal)
            .where(ConversationLearningProposal.id == proposal_id)
            .with_for_update()
        )
        if row is None or row.user_id != player.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Memory proposal not found",
            )
        if row.status != STATUS_PENDING:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This memory proposal has already been reviewed.",
            )
        return row

    async def review(
        self,
        player: Profile,
        proposal_id: uuid.UUID,
        *,
        decision: Literal["accept", "reject"],
        statement: str | None = None,
    ) -> ConversationLearningProposal:
        row = await self._owned_pending(player, proposal_id)
        now = _utcnow()

        if decision == "reject":
            row.status = STATUS_REJECTED
            row.reviewed_by_profile_id = player.id
            row.reviewed_at_utc = now
            row.updated_at = now
            await self.session.commit()
            await self.session.refresh(row)
            return row

        reviewed = (statement if statement is not None else row.statement).strip()
        if not statement_is_durable(reviewed, kind=row.kind):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Accepted memory must be durable context and cannot change "
                    "verdict, threshold, or data-quality rules."
                ),
            )
        row.reviewed_by_profile_id = player.id
        row.reviewed_at_utc = now
        row.updated_at = now
        row.status = STATUS_ACCEPTED
        row.reviewed_statement = reviewed

        active = await self._active_learned_context(player.id)
        existing_items: list[dict[str, Any]] = []
        if active is not None:
            raw_items = active.content.get("items", [])
            if isinstance(raw_items, list):
                existing_items = [item for item in raw_items if isinstance(item, dict)]
        current_version = await self.session.scalar(
            select(func.max(KnowledgeBase.version)).where(
                KnowledgeBase.user_id == player.id,
                KnowledgeBase.section == LEARNED_CONTEXT_SECTION,
            )
        )
        await self.session.execute(
            update(KnowledgeBase)
            .where(
                KnowledgeBase.user_id == player.id,
                KnowledgeBase.section == LEARNED_CONTEXT_SECTION,
            )
            .values(is_active=False, updated_at=now)
        )
        learned_item = {
            "id": str(row.id),
            "kind": row.kind,
            "statement": reviewed,
            "evidence": row.evidence_json,
            "acceptedAtUtc": now.isoformat() + "Z",
        }
        self.session.add(
            KnowledgeBase(
                user_id=player.id,
                section=LEARNED_CONTEXT_SECTION,
                version=(current_version or 0) + 1,
                is_active=True,
                source="conversation_learning_confirmed",
                content={"items": [*existing_items, learned_item]},
                updated_by_profile_id=player.id,
            )
        )
        await self.session.commit()
        await self.session.refresh(row)
        return row
