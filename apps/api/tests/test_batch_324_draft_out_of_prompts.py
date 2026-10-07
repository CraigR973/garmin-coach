"""Batch 324.1: no prompt reads the plan builder's raw draft.

The draft of his next plan is a ``knowledge_base`` row (``generated_block``) beside his
real Coach memory, and on 7 Oct 2026 every reader that loads active Coach-memory rows for a
model loaded it too: the morning brief and the chat put every row verbatim into
``knowledgeBase.sections``, so the 69,702-character Plan No. 3 draft would have gone whole
into both. The draft is working state, read by the coach only through the plan's own
compact view and tool. These tests hold every model-facing reader to that, and hold the
packet builder to it even if a reader forgets.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy.dialects import postgresql

from src.models.coaching import KnowledgeBase
from src.services.block_generator import GENERATED_BLOCK_SECTION
from src.services.chat_context import ChatContextService
from src.services.coach_policy import MODEL_HIDDEN_SECTIONS
from src.services.coach_sections import knowledge_base_section
from src.services.handover import HandoverService
from src.services.morning_analysis import MorningAnalysisService
from src.services.post_flexibility_analysis import PostFlexibilityAnalysisService
from src.services.post_strength_analysis import PostStrengthAnalysisService
from src.services.post_walk_analysis import PostWalkAnalysisService
from src.services.post_workout_analysis import PostWorkoutAnalysisService


class _Result:
    def scalars(self) -> _Result:
        return self

    def all(self) -> list[Any]:
        return []


class _CapturingSession:
    """Records each statement a reader sends, and answers with no rows."""

    def __init__(self) -> None:
        self.statements: list[Any] = []

    async def execute(self, statement: Any, *args: Any, **kwargs: Any) -> _Result:
        self.statements.append(statement)
        return _Result()


def _sql(statement: Any) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),  # type: ignore[no-untyped-call]
            compile_kwargs={"literal_binds": True},
        )
    )


def test_the_draft_is_the_hidden_section() -> None:
    assert MODEL_HIDDEN_SECTIONS == (GENERATED_BLOCK_SECTION,)
    assert GENERATED_BLOCK_SECTION == "generated_block"


@pytest.mark.parametrize(
    ("service_class", "method"),
    [
        (MorningAnalysisService, "_active_knowledge_base"),
        (ChatContextService, "_active_knowledge_base"),
        (PostWorkoutAnalysisService, "_active_knowledge_base"),
        (PostStrengthAnalysisService, "_active_knowledge_base"),
        (PostWalkAnalysisService, "_active_knowledge_base"),
        (PostFlexibilityAnalysisService, "_active_knowledge_base"),
        (HandoverService, "_knowledge_base"),
    ],
)
async def test_every_model_facing_reader_leaves_the_draft_out(
    service_class: Any, method: str
) -> None:
    session = _CapturingSession()
    await getattr(service_class(session), method)(uuid.uuid4())

    assert len(session.statements) == 1
    sql = _sql(session.statements[0])
    assert "knowledge_base.section NOT IN ('generated_block')" in sql
    assert "knowledge_base.is_active IS true" in sql


def _row(section: str, content: dict[str, Any]) -> KnowledgeBase:
    return KnowledgeBase(
        user_id=uuid.uuid4(),
        section=section,
        version=1,
        is_active=True,
        source="block_generator" if section == GENERATED_BLOCK_SECTION else "batch_5_seed",
        content=content,
    )


def test_the_packet_never_carries_the_draft_even_if_a_reader_loads_it() -> None:
    rows = [
        _row("profile", {"athleteName": "Mark"}),
        _row(GENERATED_BLOCK_SECTION, {"status": "draft", "planName": "Plan No. 3"}),
        _row("holiday_windows", {"windows": []}),
    ]

    packet = knowledge_base_section(rows)

    sections = [section["section"] for section in packet["sections"]]
    assert sections == ["profile", "holiday_windows"]
    assert "Plan No. 3" not in repr(packet)
