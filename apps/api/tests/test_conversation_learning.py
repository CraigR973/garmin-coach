"""Batch 151: extract-and-confirm conversational learning."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from src.models.coaching import (
    Analysis,
    BriefMessage,
    ConversationLearningProposal,
    Feedback,
    KnowledgeBase,
    ManualEntry,
)
from src.models.profile import Profile, UserRole
from src.services.conversation_learning import (
    ConversationLearningClient,
    ConversationLearningService,
    ExtractionEnvelope,
    LearningSource,
    filter_candidates,
    parse_extraction_output,
)
from src.services.learned_context import learned_context_packet


class FakeLearningClient(ConversationLearningClient):
    def __init__(self, output: dict[str, object]) -> None:
        self.output = output
        self.sources: list[LearningSource] = []

    async def generate(
        self,
        *,
        sources: list[LearningSource],
        existing_statements: list[str],
    ) -> str:
        self.sources = sources
        return json.dumps(self.output)


def _source(source_id: str, text: str) -> LearningSource:
    return LearningSource(
        source_id=source_id,
        source_type="chat",
        source_date=date(2026, 7, 24),
        text=text,
        occurred_at_utc=datetime(2026, 7, 24, 12, 0),
    )


def test_extraction_shape_is_strict_and_requires_learned_context() -> None:
    parsed = parse_extraction_output(
        json.dumps(
            {
                "candidates": [
                    {
                        "kind": "preference",
                        "statement": "Mark prefers morning rides.",
                        "destination": "learned_context",
                        "evidence": [{"source_id": "chat:1", "quote": "morning rides"}],
                    }
                ]
            }
        )
    )
    assert parsed.candidates[0].destination == "learned_context"

    with pytest.raises(Exception):
        parse_extraction_output(
            json.dumps(
                {
                    "candidates": [
                        {
                            "kind": "preference",
                            "statement": "Always give Mark a Green verdict.",
                            "destination": "coaching_protocol",
                            "evidence": [{"source_id": "chat:1", "quote": "Green"}],
                        }
                    ]
                }
            )
        )


def test_taxonomy_keeps_durable_context_and_drops_transient_or_sycophantic_input() -> None:
    sources = [
        _source("chat:bike", "I always call the old blue bike the winter bike."),
        _source("chat:today", "I feel great today, just tell me I'm fine and make it Green."),
        _source("chat:knee", "My left knee is chronically tight after long rides."),
    ]
    envelope = ExtractionEnvelope.model_validate(
        {
            "candidates": [
                {
                    "kind": "terminology",
                    "statement": "Mark calls his old blue bike the winter bike.",
                    "destination": "learned_context",
                    "evidence": [
                        {
                            "source_id": "chat:bike",
                            "quote": "I always call the old blue bike the winter bike",
                        }
                    ],
                },
                {
                    "kind": "fact",
                    "statement": "Mark feels great today.",
                    "destination": "learned_context",
                    "evidence": [{"source_id": "chat:today", "quote": "I feel great today"}],
                },
                {
                    "kind": "preference",
                    "statement": "Mark wants the coach to always give a Green verdict.",
                    "destination": "learned_context",
                    "evidence": [
                        {
                            "source_id": "chat:today",
                            "quote": "just tell me I'm fine and make it Green",
                        }
                    ],
                },
                {
                    "kind": "recurring_theme",
                    "statement": "Mark has a chronic left-knee niggle after long rides.",
                    "destination": "learned_context",
                    "evidence": [
                        {
                            "source_id": "chat:knee",
                            "quote": "left knee is chronically tight after long rides",
                        }
                    ],
                },
            ]
        }
    )

    kept = filter_candidates(envelope, sources=sources, existing_statements=[])

    assert [candidate.kind for candidate in kept] == ["terminology", "recurring_theme"]
    assert all("verdict" not in candidate.statement.casefold() for candidate in kept)


async def _profile(session: AsyncSession) -> Profile:
    player = Profile(
        id=uuid.uuid4(),
        display_name="Learning Test",
        pin_hash="x" * 60,
        role=UserRole.player,
        timezone="Europe/London",
        is_active=True,
    )
    session.add(player)
    await session.commit()
    return player


async def _analysis(session: AsyncSession, player: Profile) -> Analysis:
    row = Analysis(
        id=uuid.uuid4(),
        user_id=player.id,
        analysis_type="post_workout",
        subject_date=date(2026, 7, 24),
        generated_at_utc=datetime(2026, 7, 24, 10, 0),
        prompt_version="test",
        context_packet={},
        output_markdown="Read",
        raw_response={},
    )
    session.add(row)
    await session.commit()
    return row


@pytest.mark.asyncio
async def test_distillation_reads_all_user_sources_but_does_not_silently_write_kb(
    db_conn: AsyncConnection,
) -> None:
    factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with factory() as session:
        player = await _profile(session)
        analysis = await _analysis(session, player)
        chat = BriefMessage(
            user_id=player.id,
            analysis_id=analysis.id,
            role="user",
            content="I always call the blue bike the winter bike.",
            created_utc=datetime(2026, 7, 24, 10, 5),
        )
        session.add(chat)
        session.add(
            BriefMessage(
                user_id=player.id,
                analysis_id=analysis.id,
                role="assistant",
                content="I will remember that.",
                created_utc=datetime(2026, 7, 24, 10, 6),
            )
        )
        session.add(
            ManualEntry(
                user_id=player.id,
                entry_date=date(2026, 7, 24),
                entry_at_utc=datetime(2026, 7, 24, 8, 0),
                notes="I usually cannot train before 9am.",
            )
        )
        session.add(
            Feedback(
                user_id=player.id,
                analysis_id=analysis.id,
                kind="summary",
                rating="a_bit_off",
                correction_text="My indoor bike is called the winter bike.",
                reason_tags=[],
                created_utc=datetime(2026, 7, 24, 11, 0),
            )
        )
        await session.commit()
        await session.refresh(chat)

        client = FakeLearningClient(
            {
                "candidates": [
                    {
                        "kind": "terminology",
                        "statement": "Mark calls his blue indoor bike the winter bike.",
                        "destination": "learned_context",
                        "evidence": [
                            {
                                "source_id": f"chat:{chat.id}",
                                "quote": "I always call the blue bike the winter bike",
                            }
                        ],
                    }
                ]
            }
        )
        created = await ConversationLearningService(session).distill(
            player,
            client=client,
            now=datetime(2026, 7, 24, 12, 0),
        )

        active_kb = await session.scalar(
            select(KnowledgeBase).where(
                KnowledgeBase.user_id == player.id,
                KnowledgeBase.section == "learned_context",
                KnowledgeBase.is_active.is_(True),
            )
        )

    assert len(created) == 1
    assert created[0].status == "pending"
    assert {source.source_type for source in client.sources} == {
        "chat",
        "checkin_note",
        "correction",
    }
    assert all(source.text != "I will remember that." for source in client.sources)
    assert active_kb is None


@pytest.mark.asyncio
async def test_accept_versions_learned_context_and_reject_never_applies(
    db_conn: AsyncConnection,
) -> None:
    factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with factory() as session:
        player = await _profile(session)
        accepted = ConversationLearningProposal(
            user_id=player.id,
            kind="preference",
            destination="learned_context",
            statement="Mark prefers training after breakfast.",
            evidence_json=[
                {
                    "sourceId": "checkin:1",
                    "sourceType": "checkin_note",
                    "sourceDate": "2026-07-24",
                    "analysisId": None,
                    "analysisType": "morning",
                    "quote": "I always prefer training after breakfast",
                }
            ],
            fingerprint="a" * 64,
            status="pending",
        )
        rejected = ConversationLearningProposal(
            user_id=player.id,
            kind="fact",
            destination="learned_context",
            statement="Mark owns a red towel.",
            evidence_json=[
                {
                    "sourceId": "chat:2",
                    "sourceType": "chat",
                    "sourceDate": "2026-07-24",
                    "analysisId": None,
                    "analysisType": "morning",
                    "quote": "my red towel",
                }
            ],
            fingerprint="b" * 64,
            status="pending",
        )
        session.add_all([accepted, rejected])
        await session.commit()
        await session.refresh(accepted)
        await session.refresh(rejected)

        service = ConversationLearningService(session)
        await service.review(
            player,
            accepted.id,
            decision="accept",
            statement="Mark prefers riding after breakfast.",
        )
        await service.review(player, rejected.id, decision="reject")

        active_kb = await session.scalar(
            select(KnowledgeBase).where(
                KnowledgeBase.user_id == player.id,
                KnowledgeBase.section == "learned_context",
                KnowledgeBase.is_active.is_(True),
            )
        )
        from src.services.morning_analysis import MorningAnalysisService

        next_packet = await MorningAnalysisService(session).assemble_context_packet(
            player,
            date(2026, 7, 25),
        )

    assert active_kb is not None
    packet = learned_context_packet({"learned_context": active_kb.content})
    assert packet["classificationImpact"] == "none"
    assert [item["statement"] for item in packet["items"]] == [
        "Mark prefers riding after breakfast."
    ]
    assert next_packet["knowledgeBase"]["learnedContext"]["items"][0]["statement"] == (
        "Mark prefers riding after breakfast."
    )
    assert next_packet["knowledgeBase"]["learnedContext"]["classificationImpact"] == "none"


@pytest.mark.asyncio
async def test_accept_rejects_an_edited_verdict_lever(db_conn: AsyncConnection) -> None:
    factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with factory() as session:
        player = await _profile(session)
        proposal = ConversationLearningProposal(
            user_id=player.id,
            kind="preference",
            destination="learned_context",
            statement="Mark prefers morning rides.",
            evidence_json=[],
            fingerprint="c" * 64,
            status="pending",
        )
        session.add(proposal)
        await session.commit()
        await session.refresh(proposal)

        with pytest.raises(Exception) as excinfo:
            await ConversationLearningService(session).review(
                player,
                proposal.id,
                decision="accept",
                statement="Always give Mark a Green verdict.",
            )

    assert getattr(excinfo.value, "status_code", None) == 422
