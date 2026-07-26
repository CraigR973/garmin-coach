"""Concurrency/idempotency coverage for paid morning and post-session reads."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from src.models.coaching import Activity, Analysis, GenerationRequest, ManualEntry
from src.models.profile import Profile, UserRole
from src.services.generation_requests import claim_generation_request
from src.services.morning_analysis import (
    ClaudeGenerationResult,
    MorningAnalysisService,
)
from src.services.post_workout_analysis import PostWorkoutAnalysisService


@dataclass
class BlockingGenerationClient:
    calls: int = 0
    started: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)

    async def generate(
        self,
        *,
        context_packet: dict[str, Any],
        user_prompt: str,
    ) -> ClaudeGenerationResult:
        self.calls += 1
        self.started.set()
        await self.release.wait()
        return ClaudeGenerationResult(
            output_markdown="Generated once.",
            raw_response={"id": f"call-{self.calls}"},
            model_name="test-model",
        )


async def _set_search_path(session: AsyncSession) -> None:
    await session.execute(text("SET search_path TO coach, public"))


async def _delete_profile(
    session_factory: async_sessionmaker[AsyncSession],
    user_id: uuid.UUID,
) -> None:
    async with session_factory() as session:
        await _set_search_path(session)
        await session.execute(delete(Profile).where(Profile.id == user_id))
        await session.commit()


@pytest.mark.asyncio
async def test_identical_morning_generation_calls_once_but_changed_input_adds_history(
    db_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    user_id = uuid.uuid4()
    subject_date = date(2026, 7, 26)
    entry_id = uuid.uuid4()
    client = BlockingGenerationClient()

    async def _packet(
        self: MorningAnalysisService,
        player: Profile,
        requested_date: date,
    ) -> dict[str, Any]:
        return {
            "packetType": "morning_analysis",
            "subjectDate": requested_date.isoformat(),
            "verdict": {"status": "Green"},
        }

    monkeypatch.setattr(MorningAnalysisService, "assemble_context_packet", _packet)

    async with session_factory() as session:
        await _set_search_path(session)
        session.add(
            Profile(
                id=user_id,
                display_name="Generation Lease Morning",
                role=UserRole.player,
                timezone="UTC",
                is_active=True,
            )
        )
        session.add(
            ManualEntry(
                id=entry_id,
                user_id=user_id,
                entry_date=subject_date,
                entry_at_utc=datetime(2026, 7, 26, 7, 0),
                subjective_score=6,
            )
        )
        await session.commit()

    async def _run() -> Any:
        async with session_factory() as session:
            await _set_search_path(session)
            player = await session.get(Profile, user_id)
            assert player is not None
            return await MorningAnalysisService(session).generate_and_store(
                player,
                subject_date,
                client=client,
                force=True,
            )

    try:
        first_task = asyncio.create_task(_run())
        await asyncio.wait_for(client.started.wait(), timeout=5)
        second_task = asyncio.create_task(_run())
        await asyncio.sleep(0.05)
        assert client.calls == 1
        client.release.set()
        first, second = await asyncio.gather(first_task, second_task)

        assert sorted((first.generated, second.generated)) == [False, True]
        assert first.analysis.id == second.analysis.id
        assert client.calls == 1

        async with session_factory() as session:
            await _set_search_path(session)
            entry = await session.get(ManualEntry, entry_id)
            assert entry is not None
            entry.entry_at_utc = datetime(2026, 7, 26, 7, 5)
            await session.commit()

        identical_retry = await _run()
        assert identical_retry.generated is False
        assert identical_retry.analysis.id == first.analysis.id
        assert client.calls == 1

        async with session_factory() as session:
            await _set_search_path(session)
            entry = await session.get(ManualEntry, entry_id)
            assert entry is not None
            entry.entry_at_utc = datetime(2026, 7, 26, 7, 10)
            entry.subjective_score = 4
            await session.commit()

        changed = await _run()
        assert changed.generated is True
        assert changed.analysis.id != first.analysis.id
        assert client.calls == 2

        async with session_factory() as session:
            await _set_search_path(session)
            analysis_count = await session.scalar(
                select(func.count())
                .select_from(Analysis)
                .where(Analysis.user_id == user_id, Analysis.analysis_type == "morning")
            )
            request_count = await session.scalar(
                select(func.count())
                .select_from(GenerationRequest)
                .where(GenerationRequest.user_id == user_id)
            )
            assert analysis_count == 2
            assert request_count == 2
    finally:
        await _delete_profile(session_factory, user_id)


@pytest.mark.asyncio
async def test_identical_post_activity_generation_calls_once(
    db_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    user_id = uuid.uuid4()
    activity_id = uuid.uuid4()
    client = BlockingGenerationClient()

    async def _packet(
        self: PostWorkoutAnalysisService,
        player: Profile,
        activity: Activity,
    ) -> dict[str, Any]:
        checkin = await self._post_ride_checkin(player.id, activity.id)
        return {
            "packetType": "post_workout_analysis",
            "postRideCheckIn": (
                {"entryAtUtc": checkin.entry_at_utc.isoformat() + "Z"}
                if checkin is not None
                else None
            ),
            "recoveryDecision": {"status": "Green"},
        }

    monkeypatch.setattr(PostWorkoutAnalysisService, "assemble_context_packet", _packet)
    monkeypatch.setattr(
        "src.services.post_workout_analysis.prepare_post_activity_generation",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "src.services.post_workout_analysis.mark_post_activity_generation",
        AsyncMock(return_value=None),
    )

    async with session_factory() as session:
        await _set_search_path(session)
        session.add(
            Profile(
                id=user_id,
                display_name="Generation Lease Post",
                role=UserRole.player,
                timezone="UTC",
                is_active=True,
            )
        )
        session.add(
            Activity(
                id=activity_id,
                user_id=user_id,
                garmin_activity_id=9_999_161,
                activity_name="Concurrency ride",
                activity_type="indoor_cycling",
                start_utc=datetime(2026, 7, 26, 10, 0),
                duration_sec=3600,
                raw_summary={},
            )
        )
        await session.commit()

    async def _run() -> Any:
        async with session_factory() as session:
            await _set_search_path(session)
            player = await session.get(Profile, user_id)
            activity = await session.get(Activity, activity_id)
            assert player is not None and activity is not None
            return await PostWorkoutAnalysisService(session).generate_and_store(
                player,
                activity,
                client=client,
                force=True,
            )

    try:
        first_task = asyncio.create_task(_run())
        await asyncio.wait_for(client.started.wait(), timeout=5)
        second_task = asyncio.create_task(_run())
        await asyncio.sleep(0.05)
        assert client.calls == 1
        client.release.set()
        first, second = await asyncio.gather(first_task, second_task)

        assert sorted((first.generated, second.generated)) == [False, True]
        assert first.analysis.id == second.analysis.id
        assert client.calls == 1

        async with session_factory() as session:
            await _set_search_path(session)
            analysis_count = await session.scalar(
                select(func.count())
                .select_from(Analysis)
                .where(
                    Analysis.user_id == user_id,
                    Analysis.analysis_type == "post_workout",
                )
            )
            assert analysis_count == 1
    finally:
        await _delete_profile(session_factory, user_id)


@pytest.mark.asyncio
async def test_expired_or_failed_generation_lease_can_be_reclaimed(
    db_engine: AsyncEngine,
) -> None:
    session_factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    user_id = uuid.uuid4()
    request_identity = "a" * 64
    request_id = uuid.uuid4()
    async with session_factory() as session:
        await _set_search_path(session)
        session.add(
            Profile(
                id=user_id,
                display_name="Lease Recovery",
                role=UserRole.player,
                timezone="UTC",
                is_active=True,
            )
        )
        session.add(
            GenerationRequest(
                id=request_id,
                user_id=user_id,
                request_identity=request_identity,
                generation_kind="morning",
                status="running",
                lease_expires_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1),
            )
        )
        await session.commit()

    try:
        async with session_factory() as session:
            await _set_search_path(session)
            async with claim_generation_request(
                session,
                user_id=user_id,
                request_identity=request_identity,
                generation_kind="morning",
            ) as claim:
                assert claim.row.id == request_id
                assert claim.existing_analysis is None
                claim.mark_failed("timeout")
            await session.commit()

        async with session_factory() as session:
            await _set_search_path(session)
            async with claim_generation_request(
                session,
                user_id=user_id,
                request_identity=request_identity,
                generation_kind="morning",
            ) as claim:
                assert claim.row.id == request_id
                assert claim.existing_analysis is None
                claim.mark_failed("retryable")
            await session.commit()
    finally:
        await _delete_profile(session_factory, user_id)
