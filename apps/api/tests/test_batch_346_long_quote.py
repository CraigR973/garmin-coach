"""Batch 346 fix (29 Oct): one over-long evidence quote must not void the whole read.

The first paid read returned 200 with two quotes longer than the 300-character limit;
the strict envelope rejected all of it, nothing was saved and the mark stayed unset, so
every night would have paid for the same failing read again. All text here is made up.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from src.models.coaching import BriefMessage
from src.models.profile import Profile
from src.services.conversation_learning import (
    MAX_QUOTE_LENGTH,
    SYSTEM_PROMPT,
    ConversationLearningClient,
    ConversationLearningService,
    LearningSource,
    _quote_is_verbatim,
    clip_quote,
    filter_candidates,
    parse_extraction_output,
)
from tests.test_batch_346_coach_memory import NOW, _ask, _profile, _reviewed_through

_LONG_TEXT = (
    "I ride the turbo trainer in the garage every Tuesday evening before tea and "
    + " ".join(f"word{index}" for index in range(60))
    + " then I stretch for ten minutes."
)


def _candidate(quote: str, *, source_id: str = "chat:1", statement: str | None = None) -> dict:
    return {
        "kind": "fact",
        "statement": statement or "Mark rides the turbo trainer in the garage every Tuesday.",
        "destination": "learned_context",
        "evidence": [{"source_id": source_id, "quote": quote}],
    }


def _source(text: str, source_id: str = "chat:1") -> LearningSource:
    return LearningSource(
        source_id=source_id,
        source_type="chat",
        source_date=date(2026, 10, 27),
        text=text,
        occurred_at_utc=datetime(2026, 10, 27, 9, 0),
    )


def test_a_cut_quote_is_verbatim_short_enough_and_ends_on_a_word() -> None:
    assert len(_LONG_TEXT) > MAX_QUOTE_LENGTH
    cut = clip_quote(_LONG_TEXT)

    assert len(cut) <= MAX_QUOTE_LENGTH
    assert _LONG_TEXT.startswith(cut)
    assert _LONG_TEXT[len(cut)] == " "  # the next character is a space: no word was split
    assert _quote_is_verbatim(cut, _LONG_TEXT)


def test_a_quote_within_the_limit_is_left_alone() -> None:
    assert clip_quote("short and sweet") == "short and sweet"
    exact = "a" * MAX_QUOTE_LENGTH
    assert clip_quote(exact) == exact


def test_one_unbroken_run_is_cut_at_the_limit() -> None:
    cut = clip_quote("x" * 500)
    assert cut == "x" * MAX_QUOTE_LENGTH


def test_an_envelope_with_one_long_quote_still_yields_every_other_candidate() -> None:
    envelope = parse_extraction_output(
        json.dumps(
            {
                "candidates": [
                    _candidate("every Tuesday evening", statement="Mark rides every Tuesday."),
                    _candidate(_LONG_TEXT),
                    _candidate("stretch for ten minutes", statement="Mark stretches ten minutes."),
                ]
            }
        )
    )

    assert len(envelope.candidates) == 3
    assert len(envelope.candidates[1].evidence[0].quote) <= MAX_QUOTE_LENGTH


def test_a_cut_quote_that_no_longer_supports_the_statement_is_dropped_by_the_filter() -> None:
    # The supporting words sit at the very end, past the cut.
    text = " ".join(f"filler{index}" for index in range(70)) + " I limp after kettlebell swings"
    statement = "Mark limps after kettlebell swings."
    envelope = parse_extraction_output(
        json.dumps({"candidates": [_candidate(text, statement=statement)]})
    )

    kept = filter_candidates(envelope, sources=[_source(text)], existing_statements=[])

    assert len(envelope.candidates) == 1
    assert kept == []


def test_a_cut_quote_that_still_supports_the_statement_is_kept() -> None:
    envelope = parse_extraction_output(json.dumps({"candidates": [_candidate(_LONG_TEXT)]}))

    kept = filter_candidates(envelope, sources=[_source(_LONG_TEXT)], existing_statements=[])

    assert len(kept) == 1
    assert len(kept[0].evidence[0].quote) <= MAX_QUOTE_LENGTH


def test_a_candidate_that_breaks_the_schema_is_dropped_on_its_own_and_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    broken = {**_candidate("every Tuesday evening"), "destination": "coaching_protocol"}
    no_evidence = {**_candidate("x"), "evidence": []}
    good = _candidate("every Tuesday evening", statement="Mark rides every Tuesday.")

    with caplog.at_level(logging.WARNING):
        envelope = parse_extraction_output(
            json.dumps({"candidates": [broken, good, no_evidence, "not an object"]})
        )

    assert [c.statement for c in envelope.candidates] == ["Mark rides every Tuesday."]
    assert "dropped 3 of 4" in caplog.text


def test_more_candidates_than_the_cap_are_trimmed_not_fatal() -> None:
    many = [
        _candidate("every Tuesday evening", statement=f"Mark rides on day {i}.") for i in range(15)
    ]

    envelope = parse_extraction_output(json.dumps({"candidates": many}))

    assert len(envelope.candidates) == 12


def test_the_prompt_tells_the_model_the_quote_limit() -> None:
    assert "at most 300 characters" in SYSTEM_PROMPT


class _LongQuoteClient(ConversationLearningClient):
    def __init__(self, chat_id: object, other_id: object) -> None:
        self.chat_id = chat_id
        self.other_id = other_id

    async def generate(
        self,
        *,
        sources: list[LearningSource],
        existing_statements: list[str],
    ) -> str:
        return json.dumps(
            {
                "candidates": [
                    _candidate(_LONG_TEXT, source_id=f"chat:{self.chat_id}"),
                    _candidate(
                        "I stretch for ten minutes",
                        source_id=f"chat:{self.other_id}",
                        statement="Mark stretches for ten minutes.",
                    ),
                ]
            }
        )


@pytest.mark.asyncio
async def test_a_read_with_a_long_quote_proposes_and_marks_mark_as_reviewed(
    db_conn: AsyncConnection,
) -> None:
    factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with factory() as session:
        player: Profile = await _profile(session)
        long_ask: BriefMessage = _ask(player, _LONG_TEXT, datetime(2026, 10, 26, 18, 0))
        other_ask: BriefMessage = _ask(
            player, "I stretch for ten minutes afterwards.", datetime(2026, 10, 26, 18, 5)
        )
        session.add_all([long_ask, other_ask])
        await session.commit()
        await session.refresh(long_ask)
        await session.refresh(other_ask)

        service = ConversationLearningService(session)
        created = await service.distill(
            player, client=_LongQuoteClient(long_ask.id, other_ask.id), now=NOW
        )
        reviewed = await _reviewed_through(session, player)
        still_due = await service.has_new_chat(player)

    assert len(created) == 2
    assert all(
        len(item["quote"]) <= MAX_QUOTE_LENGTH for row in created for item in row.evidence_json
    )
    assert reviewed == NOW
    assert still_due is False
