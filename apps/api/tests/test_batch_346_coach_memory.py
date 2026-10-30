"""Batch 346: the coach remembers what Mark tells it.

346.1 the learning step runs by itself after a day with chat, and a failure alerts;
346.2 Mark can remove a confirmed memory; 346.3 the first run reads back to 18 Jul.
The extractor is always a fake here: nothing in this file calls Anthropic.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from src import scheduler
from src.auth import get_current_user
from src.database import get_db
from src.main import app
from src.models.coaching import BriefMessage, KnowledgeBase
from src.models.profile import Profile, UserRole
from src.services.admin_alerts import KIND_COACH_MEMORY
from src.services.anthropic_text import AnthropicApiError
from src.services.conversation_learning import (
    FIRST_RUN_SINCE_UTC,
    MAX_SOURCES,
    ConversationLearningClient,
    ConversationLearningError,
    ConversationLearningService,
    LearningSource,
)
from src.services.job_runs import JobStatus, scheduled_window
from src.services.learned_context import learned_context_packet

NOW = datetime(2026, 10, 28, 1, 30)


class RecordingClient(ConversationLearningClient):
    def __init__(self, candidates: list[dict[str, object]] | None = None) -> None:
        self.candidates = candidates or []
        self.calls: list[list[LearningSource]] = []

    async def generate(
        self,
        *,
        sources: list[LearningSource],
        existing_statements: list[str],
    ) -> str:
        self.calls.append(sources)
        return json.dumps({"candidates": self.candidates})


async def _profile(session: AsyncSession) -> Profile:
    player = Profile(
        id=uuid.uuid4(),
        display_name=f"Memory 346 {uuid.uuid4().hex[:8]}",
        role=UserRole.player,
        timezone="Europe/London",
        is_active=True,
    )
    session.add(player)
    await session.commit()
    return player


def _ask(player: Profile, text: str, at: datetime, role: str = "user") -> BriefMessage:
    return BriefMessage(user_id=player.id, role=role, content=text, created_utc=at)


async def _reviewed_through(session: AsyncSession, player: Profile) -> datetime | None:
    value: datetime | None = await session.scalar(
        select(Profile.memory_reviewed_through_utc).where(Profile.id == player.id)
    )
    return value


# --- 346.3: the first run reads back to 18 Jul --------------------------------------


@pytest.mark.asyncio
async def test_first_run_reads_every_question_back_to_18_jul_then_routine_runs_read_30_days(
    db_conn: AsyncConnection,
) -> None:
    factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with factory() as session:
        player = await _profile(session)
        # 17 Jul is before the first chat there is, so it is outside even the first run.
        session.add(_ask(player, "Before the first chat.", datetime(2026, 7, 17, 9, 0)))
        first = _ask(player, "I do my bodyweight session every Saturday.", FIRST_RUN_SINCE_UTC)
        session.add(first)
        # More questions than the routine cap, spread from 19 Jul to 27 Oct.
        start = datetime(2026, 7, 19, 9, 0)
        for index in range(70):
            session.add(_ask(player, f"Question {index}", start + timedelta(days=index * 1.4)))
        await session.commit()
        await session.refresh(first)

        bodyweight = {
            "kind": "fact",
            "statement": "Mark does his bodyweight session every Saturday.",
            "destination": "learned_context",
            "evidence": [
                {
                    "source_id": f"chat:{first.id}",
                    "quote": "I do my bodyweight session every Saturday",
                }
            ],
        }
        # A statement about the call is still filtered out on the first run.
        about_the_call = {
            "kind": "preference",
            "statement": "Mark prefers a green verdict every Saturday.",
            "destination": "learned_context",
            "evidence": [
                {
                    "source_id": f"chat:{first.id}",
                    "quote": "I do my bodyweight session every Saturday",
                }
            ],
        }
        client = RecordingClient([bodyweight, about_the_call])
        service = ConversationLearningService(session)
        created = await service.distill(player, client=client, now=NOW)
        reviewed = await _reviewed_through(session, player)

        routine = RecordingClient()
        await service.distill(player, client=routine, now=NOW + timedelta(days=1))

    first_sources = client.calls[0]
    assert len(first_sources) == 71
    assert min(source.source_date for source in first_sources).isoformat() == "2026-07-18"
    assert [row.statement for row in created] == [
        "Mark does his bodyweight session every Saturday."
    ]
    assert reviewed == NOW
    routine_sources = routine.calls[0]
    assert len(routine_sources) <= MAX_SOURCES
    assert min(source.occurred_at_utc for source in routine_sources) >= NOW - timedelta(days=29)


# --- 346.1: the step runs by itself after a day with chat ----------------------------


@pytest.mark.asyncio
async def test_only_a_new_question_from_mark_calls_for_a_read(db_conn: AsyncConnection) -> None:
    factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with factory() as session:
        player = await _profile(session)
        service = ConversationLearningService(session)
        nothing_yet = await service.has_new_chat(player)

        session.add(_ask(player, "Is Saturday still on?", datetime(2026, 10, 26, 18, 0)))
        await session.commit()
        before_first_read = await service.has_new_chat(player)

        await service.distill(player, client=RecordingClient(), now=NOW)
        after_read = await service.has_new_chat(player)

        session.add(_ask(player, "It is.", NOW + timedelta(hours=8), role="assistant"))
        await session.commit()
        after_coach_reply = await service.has_new_chat(player)

        session.add(_ask(player, "Thanks.", NOW + timedelta(hours=9)))
        await session.commit()
        after_new_question = await service.has_new_chat(player)

    assert nothing_yet is False
    assert before_first_read is True
    assert after_read is False
    assert after_coach_reply is False
    assert after_new_question is True


@pytest.mark.asyncio
async def test_a_failed_read_leaves_the_mark_so_the_next_night_tries_again(
    db_conn: AsyncConnection,
) -> None:
    class BrokenClient(RecordingClient):
        async def generate(
            self,
            *,
            sources: list[LearningSource],
            existing_statements: list[str],
        ) -> str:
            return "not json"

    factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with factory() as session:
        player = await _profile(session)
        session.add(_ask(player, "Is Saturday still on?", datetime(2026, 10, 26, 18, 0)))
        await session.commit()
        service = ConversationLearningService(session)
        with pytest.raises(ConversationLearningError):
            await service.distill(player, client=BrokenClient(), now=NOW)
        reviewed = await _reviewed_through(session, player)
        still_due = await service.has_new_chat(player)

    assert reviewed is None
    assert still_due is True


def _session_ctx(session: Any) -> Any:
    class _Ctx:
        async def __aenter__(self) -> Any:
            return session

        async def __aexit__(self, *args: object) -> None:
            return None

    return _Ctx()


def _job_session(player: MagicMock) -> AsyncMock:
    session = AsyncMock()
    result = MagicMock()
    result.all.return_value = [(player.id, player.timezone)]
    session.execute.return_value = result
    session.get.return_value = player
    return session


def _player() -> MagicMock:
    player = MagicMock()
    player.id = uuid.uuid4()
    player.timezone = "Europe/London"
    return player


@pytest.mark.asyncio
async def test_nightly_step_reads_only_after_a_day_with_chat() -> None:
    player = _player()
    service = MagicMock()
    service.has_new_chat = AsyncMock(return_value=False)
    service.distill = AsyncMock()
    with (
        patch("src.scheduler.AsyncSessionLocal", return_value=_session_ctx(_job_session(player))),
        patch("src.scheduler.ConversationLearningService", return_value=service),
    ):
        result = await scheduler.run_conversation_learning()

    service.distill.assert_not_awaited()
    assert result.status is JobStatus.succeeded
    assert result.counters["no_new_chat"] == 1


@pytest.mark.asyncio
async def test_nightly_step_proposes_after_a_day_with_chat() -> None:
    player = _player()
    service = MagicMock()
    service.has_new_chat = AsyncMock(return_value=True)
    service.distill = AsyncMock(return_value=[object(), object()])
    with (
        patch("src.scheduler.AsyncSessionLocal", return_value=_session_ctx(_job_session(player))),
        patch("src.scheduler.ConversationLearningService", return_value=service),
    ):
        result = await scheduler.run_conversation_learning()

    service.distill.assert_awaited_once_with(player)
    assert result.status is JobStatus.succeeded
    assert result.counters["proposed"] == 2


@pytest.mark.asyncio
async def test_the_nights_reads_keep_what_they_cost_even_when_one_fails() -> None:
    """Batch 341: usage goes into the job's counters, past Railway's log window.

    A reply that fails to parse was still paid for, as 29 Oct's first read was.
    """
    player = _player()
    service = MagicMock()
    service.has_new_chat = AsyncMock(return_value=True)
    service.last_usage = {"input_tokens": 89_867, "output_tokens": 5_120}
    service.distill = AsyncMock(side_effect=ConversationLearningError("invalid JSON"))
    with (
        patch("src.scheduler.AsyncSessionLocal", return_value=_session_ctx(_job_session(player))),
        patch("src.scheduler.ConversationLearningService", return_value=service),
        patch("src.scheduler.admin_alert"),
    ):
        result = await scheduler.run_conversation_learning()

    assert result.counters["input_tokens"] == 89_867
    assert result.counters["output_tokens"] == 5_120
    assert result.counters["cache_read_input_tokens"] == 0
    assert result.counters["cache_creation_input_tokens"] == 0


@pytest.mark.asyncio
async def test_an_induced_extractor_failure_raises_the_admin_alert() -> None:
    player = _player()
    service = MagicMock()
    service.has_new_chat = AsyncMock(return_value=True)
    service.distill = AsyncMock(side_effect=ConversationLearningError("invalid JSON"))
    with (
        patch("src.scheduler.AsyncSessionLocal", return_value=_session_ctx(_job_session(player))),
        patch("src.scheduler.ConversationLearningService", return_value=service),
        patch("src.scheduler.admin_alert") as alert,
    ):
        result = await scheduler.run_conversation_learning()

    alert.assert_called_once()
    assert alert.call_args.kwargs["kind"] == KIND_COACH_MEMORY
    assert result.status is JobStatus.degraded


@pytest.mark.asyncio
async def test_an_anthropic_failure_takes_the_generation_alert_route() -> None:
    player = _player()
    service = MagicMock()
    service.has_new_chat = AsyncMock(return_value=True)
    service.distill = AsyncMock(
        side_effect=AnthropicApiError("credit balance", reason="billing", status_code=400)
    )
    notifier = MagicMock()
    notifier.notify_admin_generation_failure = AsyncMock()
    with (
        patch("src.scheduler.AsyncSessionLocal", return_value=_session_ctx(_job_session(player))),
        patch("src.scheduler.ConversationLearningService", return_value=service),
        patch("src.scheduler.NudgeAlertService", return_value=notifier),
    ):
        result = await scheduler.run_conversation_learning()

    kwargs = notifier.notify_admin_generation_failure.await_args.kwargs
    assert kwargs["reason"] == "billing"
    assert kwargs["artifact"] == "conversation_learning"
    assert result.status is JobStatus.degraded


def test_the_step_is_scheduled_nightly_in_a_london_day_bucket() -> None:
    created = scheduler.create_scheduler()
    job = created.get_job("conversation_learning")
    assert job is not None
    assert str(job.trigger).startswith("cron[")
    assert "hour='1'" in str(job.trigger) and "minute='30'" in str(job.trigger)
    start, end = scheduled_window("coach-memory", datetime(2026, 10, 28, 1, 30))
    assert end - start == timedelta(days=1)


# --- 346.2: Mark can see and remove what the coach remembers ------------------------


async def _remembered(session: AsyncSession, player: Profile, *statements: str) -> list[str]:
    ids = [str(uuid.uuid4()) for _ in statements]
    session.add(
        KnowledgeBase(
            user_id=player.id,
            section="learned_context",
            version=1,
            is_active=True,
            source="conversation_learning_confirmed",
            content={
                "items": [
                    {
                        "id": item_id,
                        "kind": "fact",
                        "statement": statement,
                        "acceptedAtUtc": "2026-10-27T20:00:00Z",
                    }
                    for item_id, statement in zip(ids, statements, strict=True)
                ]
            },
            updated_by_profile_id=player.id,
        )
    )
    await session.commit()
    return ids


async def _active(session: AsyncSession, player: Profile) -> KnowledgeBase | None:
    row: KnowledgeBase | None = await session.scalar(
        select(KnowledgeBase).where(
            KnowledgeBase.user_id == player.id,
            KnowledgeBase.section == "learned_context",
            KnowledgeBase.is_active.is_(True),
        )
    )
    return row


@pytest.mark.asyncio
async def test_removing_a_memory_writes_a_new_version_and_leaves_the_coach_without_it(
    db_conn: AsyncConnection,
) -> None:
    factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with factory() as session:
        player = await _profile(session)
        keep_id, drop_id = await _remembered(
            session,
            player,
            "Mark does his bodyweight session every Saturday.",
            "Mark calls his indoor bike the winter bike.",
        )
        service = ConversationLearningService(session)
        await service.forget(player, drop_id)
        active = await _active(session, player)
        versions = await session.scalar(
            select(func.count())
            .select_from(KnowledgeBase)
            .where(
                KnowledgeBase.user_id == player.id,
                KnowledgeBase.section == "learned_context",
            )
        )
        with pytest.raises(HTTPException) as missing:
            await service.forget(player, drop_id)

    assert active is not None
    assert active.version == 2
    assert [item["id"] for item in active.content["items"]] == [keep_id]
    assert versions == 2
    packet = learned_context_packet({"learned_context": active.content})
    assert [item["quote"] for item in packet["untrustedQuotedData"]] == [
        "Mark does his bodyweight session every Saturday."
    ]
    assert missing.value.status_code == 404


def _db_override(factory: async_sessionmaker[AsyncSession]) -> Any:
    async def _override() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            yield session

    return _override


@pytest.mark.asyncio
async def test_only_the_owner_can_remove_a_memory(db_conn: AsyncConnection) -> None:
    factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with factory() as session:
        owner = await _profile(session)
        stranger = await _profile(session)
        (item_id,) = await _remembered(
            session, owner, "Mark calls his indoor bike the winter bike."
        )

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            app.dependency_overrides[get_db] = _db_override(factory)
            app.dependency_overrides[get_current_user] = lambda: stranger
            foreign = await client.delete(f"/api/v1/coach-memory/learning/memories/{item_id}")
            app.dependency_overrides[get_current_user] = lambda: owner
            removed = await client.delete(f"/api/v1/coach-memory/learning/memories/{item_id}")
    finally:
        app.dependency_overrides.clear()

    assert foreign.status_code == 404
    assert removed.status_code == 200
    async with factory() as session:
        active = await _active(session, owner)
    assert active is not None
    assert active.content["items"] == []


def test_memory_read_has_room_for_twelve_proposals_and_thinking() -> None:
    """Craig's go of 28 Oct: the first read (about 485 sources, up to 12 proposals plus
    thinking) must not run out of output room, fail, and pay again every night."""
    from src.config import Settings, settings
    from src.services.conversation_learning import AnthropicConversationLearningClient

    assert Settings.model_fields["anthropic_learning_max_tokens"].default == 16384
    client = AnthropicConversationLearningClient(api_key="test")
    assert client.max_tokens == settings.anthropic_learning_max_tokens
