"""Tests for Batch 119 — follow-up chat on a brief.

Covers the acceptance pillars:
  119.1/119.2 — a follow-up is answered grounded in the brief's context packet
  119.3 kickoff decisions — storage/threading, the turn cap, and the
        deterministic (never model-decided) propose-adjustment trigger
  119.4 — guardrails hold (no fabrication beyond the packet) and history threads
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from src.auth import get_current_user
from src.database import get_db
from src.main import app
from src.models.coaching import Analysis, BriefMessage
from src.models.profile import Profile, UserRole
from src.services.brief_chat import (
    MAX_USER_TURNS_PER_ANALYSIS,
    BriefChatClient,
    BriefChatService,
)


class FakeBriefChatClient(BriefChatClient):
    def __init__(self, answer: str = "Grounded answer.") -> None:
        self.answer = answer
        self.calls: list[dict[str, object]] = []

    async def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        prior_messages: list[dict[str, str]],
    ) -> str:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "prior_messages": prior_messages,
            }
        )
        return self.answer


def _db_override(session_factory: async_sessionmaker[AsyncSession]):
    async def _override() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    return _override


async def _make_profile(session: AsyncSession, name: str = "Chat Test") -> Profile:
    user = Profile(
        id=uuid.uuid4(),
        display_name=name,
        pin_hash="x" * 60,
        role=UserRole.admin,
        timezone="Europe/London",
        is_active=True,
    )
    session.add(user)
    await session.commit()
    return user


async def _make_analysis(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    context_packet: dict[str, object] | None = None,
    output_markdown: str = "a brief",
) -> Analysis:
    analysis = Analysis(
        id=uuid.uuid4(),
        user_id=user_id,
        analysis_type="morning",
        subject_date=datetime(2026, 7, 14, 6, 30).date(),
        generated_at_utc=datetime(2026, 7, 14, 6, 30),
        prompt_version="morning-x",
        context_packet=context_packet or {},
        output_markdown=output_markdown,
        raw_response={},
    )
    session.add(analysis)
    await session.commit()
    return analysis


# ---------------------------------------------------------------------------
# Service: grounding, history threading, turn cap
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ask_grounds_in_packet_and_stores_both_turns(db_conn: AsyncConnection) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        user = await _make_profile(session)
        analysis = await _make_analysis(
            session, user.id, context_packet={"verdict": {"status": "Green"}}
        )

        client = FakeBriefChatClient("Because your HRV was strong overnight.")
        turn = await BriefChatService(session).ask(
            user, analysis.id, question="Why is today Green?", client=client
        )

    assert turn.user_message.role == "user"
    assert turn.user_message.content == "Why is today Green?"
    assert turn.assistant_message.role == "assistant"
    assert turn.assistant_message.content == "Because your HRV was strong overnight."
    # The packet is embedded in the system prompt so the answer is grounded.
    assert "Green" in client.calls[0]["system_prompt"]

    async with session_factory() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(BriefMessage)
            .where(BriefMessage.analysis_id == analysis.id)
        )
        assert count == 2


@pytest.mark.asyncio
async def test_ask_threads_prior_history_into_the_next_call(db_conn: AsyncConnection) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        user = await _make_profile(session)
        analysis = await _make_analysis(session, user.id)
        service = BriefChatService(session)
        client = FakeBriefChatClient()

        await service.ask(user, analysis.id, question="First question?", client=client)
        await service.ask(user, analysis.id, question="Second question?", client=client)

    second_call_prior = client.calls[1]["prior_messages"]
    assert {"role": "user", "content": "First question?"} in second_call_prior
    assert {"role": "assistant", "content": "Grounded answer."} in second_call_prior


@pytest.mark.asyncio
async def test_ask_enforces_the_per_brief_turn_cap(db_conn: AsyncConnection) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        user = await _make_profile(session)
        analysis = await _make_analysis(session, user.id)
        service = BriefChatService(session)
        client = FakeBriefChatClient()

        for i in range(MAX_USER_TURNS_PER_ANALYSIS):
            await service.ask(user, analysis.id, question=f"Question {i}?", client=client)

        with pytest.raises(Exception) as excinfo:
            await service.ask(user, analysis.id, question="One too many?", client=client)

    assert getattr(excinfo.value, "status_code", None) == 422


@pytest.mark.asyncio
async def test_ask_only_offers_a_proposal_on_a_deterministic_keyword_match(
    db_conn: AsyncConnection,
) -> None:
    """The model's answer never decides whether to attach a proposal — Mark's
    own question does, and only when there's a deliverable ride today."""
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        user = await _make_profile(session)
        packet = {
            "restDay": {"isRestDay": False},
            "plannedWorkouts": [
                {
                    "id": str(uuid.uuid4()),
                    "workoutType": "bike",
                    "status": "planned",
                    "structuredWorkout": {"segments": []},
                }
            ],
        }
        analysis = await _make_analysis(session, user.id, context_packet=packet)
        service = BriefChatService(session)
        client = FakeBriefChatClient("Sure, want me to ease it?")

        neutral = await service.ask(user, analysis.id, question="How did I sleep?", client=client)
        wants_ease = await service.ask(
            user, analysis.id, question="Can you ease today's ride?", client=client
        )

    assert neutral.assistant_message.proposed_planned_workout_id is None
    assert wants_ease.assistant_message.proposed_planned_workout_id == uuid.UUID(
        packet["plannedWorkouts"][0]["id"]
    )


@pytest.mark.asyncio
async def test_ask_never_offers_a_proposal_on_a_rest_day(db_conn: AsyncConnection) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        user = await _make_profile(session)
        packet = {
            "restDay": {"isRestDay": True},
            "plannedWorkouts": [
                {
                    "id": str(uuid.uuid4()),
                    "workoutType": "bike",
                    "status": "skipped",
                    "structuredWorkout": {"segments": []},
                }
            ],
        }
        analysis = await _make_analysis(session, user.id, context_packet=packet)
        client = FakeBriefChatClient()

        turn = await BriefChatService(session).ask(
            user, analysis.id, question="Can you ease today's ride?", client=client
        )

    assert turn.assistant_message.proposed_planned_workout_id is None


# ---------------------------------------------------------------------------
# Endpoint: user-scoping + envelope
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_message_unknown_analysis_is_404(db_conn: AsyncConnection) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        user = await _make_profile(session)

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _db_override(session_factory)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/api/v1/briefs/{uuid.uuid4()}/messages", json={"question": "Hi?"}
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404, response.text


@pytest.mark.asyncio
async def test_post_message_on_another_users_brief_is_403(db_conn: AsyncConnection) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        owner = await _make_profile(session, "Owner")
        other = await _make_profile(session, "Other")
        analysis = await _make_analysis(session, owner.id)

    app.dependency_overrides[get_current_user] = lambda: other
    app.dependency_overrides[get_db] = _db_override(session_factory)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/api/v1/briefs/{analysis.id}/messages", json={"question": "Hi?"}
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403, response.text
    async with session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(BriefMessage))
        assert count == 0


@pytest.mark.asyncio
async def test_get_messages_lists_history_in_order(db_conn: AsyncConnection) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        user = await _make_profile(session)
        analysis = await _make_analysis(session, user.id)
        await BriefChatService(session).ask(
            user, analysis.id, question="Q1?", client=FakeBriefChatClient("A1")
        )

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _db_override(session_factory)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/v1/briefs/{analysis.id}/messages")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    body = response.json()["data"]
    assert [row["role"] for row in body] == ["user", "assistant"]
    assert body[0]["content"] == "Q1?"
    assert body[1]["content"] == "A1"


@pytest.mark.asyncio
async def test_post_message_rejects_empty_question(db_conn: AsyncConnection) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        user = await _make_profile(session)
        analysis = await _make_analysis(session, user.id)

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _db_override(session_factory)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/api/v1/briefs/{analysis.id}/messages", json={"question": ""}
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422, response.text
