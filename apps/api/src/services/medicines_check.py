"""Every three months Home asks whether he has started any new medicines (Batch 370.3).

His profile's medication fact (Batch 315.6, set by Craig on 6 Oct 2026) was seeded once and
nothing asked again, so a beta-blocker started later would leave every heart-rate zone, the
resting-heart-rate rail and the HRV floor reading against the wrong normal (HS361-06). Home
asks once a quarter. "No" dates the fact today. "Yes" records his words in the fact, so the
coach and the brief know, and the card tells him to mention it to Craig, who can check his
zones; nothing is sent to Craig (Craig, 4 Nov: "He tells you himself").
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.coaching import KnowledgeBase
from src.models.profile import Profile

#: A quarter: asked again this many days after the fact was last dated.
ASK_EVERY_DAYS: Final = 91
ANSWER_NONE: Final = "none"
ANSWER_NEW: Final = "new"
#: His words are kept to this many characters.
MAX_WORDS: Final = 120
PROFILE_SECTION: Final = "profile"
SOURCE: Final = "medicines_question"

#: What the coach and the brief read once he has said yes (draft for Craig's sign-off).
NEW_MEDICINE_NOTE: Final = (
    "He told the app he has started a new medicine (newWords, on newSince) and was asked to "
    "mention it to Craig. Until his profile says it has been checked, a change in his heart "
    "rate, resting heart rate or HRV may be the medicine rather than his recovery: say so, "
    "and never read such a change at face value."
)


def medication_as_of(medication: Mapping[str, Any] | None) -> date | None:
    """When the medication fact was last dated, or ``None`` when it never was."""

    raw = (medication or {}).get("asOf")
    try:
        return date.fromisoformat(raw) if isinstance(raw, str) else None
    except ValueError:
        return None


def question_due(medication: Mapping[str, Any] | None, today: date) -> bool:
    """Home asks when the fact is a quarter old, or was never dated."""

    as_of = medication_as_of(medication)
    return as_of is None or today >= as_of + timedelta(days=ASK_EVERY_DAYS)


def answered_medication(
    medication: Mapping[str, Any] | None, *, answer: str, words: str | None, today: date
) -> dict[str, Any]:
    """The medication fact after his answer. Pure."""

    fact = dict(medication or {})
    fact["asOf"] = today.isoformat()
    fact["source"] = f"Mark, on Home, {today.isoformat()}"
    if answer == ANSWER_NEW:
        said = " ".join((words or "").split())[:MAX_WORDS] or "one he did not name"
        before = str(fact.get("current") or "not recorded")
        fact["current"] = f"{before}; and since {today.isoformat()}, in his words: {said}"
        fact["newSince"] = today.isoformat()
        fact["newWords"] = said
        fact["note"] = NEW_MEDICINE_NOTE
    return fact


async def _profile_content(session: AsyncSession, player: Profile) -> dict[str, Any]:
    row = await session.scalar(
        select(KnowledgeBase).where(
            KnowledgeBase.user_id == player.id,
            KnowledgeBase.section == PROFILE_SECTION,
            KnowledgeBase.is_active.is_(True),
        )
    )
    return dict(row.content) if row is not None and isinstance(row.content, dict) else {}


async def medicines_question_due(session: AsyncSession, player: Profile, today: date) -> bool:
    """Whether Home asks today."""

    medication = (await _profile_content(session, player)).get("medication")
    return question_due(medication if isinstance(medication, Mapping) else None, today)


async def answer_medicines_question(
    session: AsyncSession, player: Profile, *, answer: str, words: str | None, today: date
) -> None:
    """Record his answer in the profile's medication fact, as a new version of the section."""

    from src.services.coaching_state import CoachingStateService

    service = CoachingStateService(session)
    await service.ensure_seeded(player, commit=False)
    content = await _profile_content(session, player)
    medication = content.get("medication")
    content["medication"] = answered_medication(
        medication if isinstance(medication, Mapping) else None,
        answer=answer,
        words=words,
        today=today,
    )
    await service.update_knowledge_base_section(
        player=player, section=PROFILE_SECTION, content=content, source=SOURCE
    )
