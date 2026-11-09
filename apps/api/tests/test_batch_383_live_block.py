"""Batch 383: the coach's live block sends each fact once.

Three changes, all to the chat block only, none to what any read is given:

* compact JSON separators (the default ", " and ": " were about 3,400 characters);
* the four knowledge-base nodes that repeat a row of ``sections`` are not sent;
* the raw ``learned_context`` row is not sent, because ``learnedContext`` carries the
  same memories as quoted, untrusted data, which is the form the guardrail names.

The data here is invented.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

from src.models.coaching import KnowledgeBase
from src.services.chat_context import app_state_json
from src.services.coach_sections import (
    CHAT_DUPLICATE_KNOWLEDGE_BASE_NODES,
    chat_knowledge_base_section,
    knowledge_base_section,
)
from src.services.learned_context import (
    LEARNED_CONTEXT_PROMPT_GUARDRAIL,
    LEARNED_CONTEXT_SECTION,
)


def _row(section: str, content: dict[str, object]) -> KnowledgeBase:
    return KnowledgeBase(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        section=section,
        version=1,
        source="batch_5_seed",
        content=content,
        is_active=True,
    )


def _rows() -> list[KnowledgeBase]:
    accepted = (datetime.now(UTC) - timedelta(days=3)).replace(tzinfo=None).isoformat() + "Z"
    return [
        _row("sleep_protocol", {"bedtimeTarget": "23:15"}),
        _row("data_quality_rules", {"rules": [{"id": "r1", "text": "Ignore a zero reading"}]}),
        _row("active_hypotheses", {"items": [{"id": "h1", "text": "Late caffeine"}]}),
        _row(
            LEARNED_CONTEXT_SECTION,
            {
                "items": [
                    {
                        "id": "m1",
                        "kind": "fact",
                        "statement": "Walks the dog at lunchtime",
                        "acceptedAtUtc": accepted,
                        "evidence": [{"quote": "I walk the dog at lunch", "sourceId": "s1"}],
                    }
                ]
            },
        ),
    ]


def test_the_chat_block_drops_the_four_copies_of_rows_it_already_holds() -> None:
    section = chat_knowledge_base_section(_rows())
    for node in CHAT_DUPLICATE_KNOWLEDGE_BASE_NODES:
        assert node not in section
    held = {packet["section"] for packet in section["sections"]}
    assert {"sleep_protocol", "data_quality_rules", "active_hypotheses"} <= held


def test_the_memory_is_sent_once_as_quoted_untrusted_data() -> None:
    section = chat_knowledge_base_section(_rows())
    assert LEARNED_CONTEXT_SECTION not in {packet["section"] for packet in section["sections"]}
    quoted = section["learnedContext"]["untrustedQuotedData"]
    assert quoted == [{"kind": "fact", "quote": "Walks the dog at lunchtime"}]
    # Neither the item id, its acceptance stamp nor its evidence reaches the block.
    text = json.dumps(section)
    for private in ("acceptedAtUtc", "evidence", "sourceId", '"m1"'):
        assert private not in text
    # The guardrail names a field that is still present.
    assert "knowledgeBase.learnedContext.untrustedQuotedData" in LEARNED_CONTEXT_PROMPT_GUARDRAIL


def test_the_morning_packets_section_is_unchanged() -> None:
    whole = knowledge_base_section(_rows())
    for node in CHAT_DUPLICATE_KNOWLEDGE_BASE_NODES:
        assert node in whole
    assert LEARNED_CONTEXT_SECTION in {packet["section"] for packet in whole["sections"]}
    # The chat copy is the whole one less exactly what is repeated.
    chat = chat_knowledge_base_section(_rows())
    assert set(whole) - set(chat) == set(CHAT_DUPLICATE_KNOWLEDGE_BASE_NODES)
    assert chat["learnedContext"] == whole["learnedContext"]


def test_the_block_is_serialised_compact_and_reads_back_the_same() -> None:
    state = {"b": [1, 2, {"c": "d e"}], "a": {"x": None, "y": "é"}}
    text = app_state_json(state)
    assert text == '{"a":{"x":null,"y":"\\u00e9"},"b":[1,2,{"c":"d e"}]}'
    assert json.loads(text) == state
