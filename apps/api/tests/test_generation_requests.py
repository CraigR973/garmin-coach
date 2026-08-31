"""Concurrency/idempotency coverage for paid morning and post-session reads."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from src.models.coaching import (
    DAILY_METRIC_PHASE_MORNING,
    Activity,
    Analysis,
    DailyMetric,
    GenerationRequest,
    ManualEntry,
    Sleep,
)
from src.models.profile import Profile, UserRole
from src.services.generation_requests import (
    GenerationRequestInProgress,
    claim_generation_request,
)
from src.services.morning_analysis import (
    ClaudeGenerationResult,
    MorningAnalysisService,
)
from src.services.morning_inputs import morning_input_presence
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


@dataclass
class CountingGenerationClient:
    calls: int = 0

    async def generate(
        self,
        *,
        context_packet: dict[str, Any],
        user_prompt: str,
    ) -> ClaudeGenerationResult:
        self.calls += 1
        return ClaudeGenerationResult(
            output_markdown=f"Generated {self.calls}.",
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
        await session.flush()
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

        # Batch 232.1: the loser is refused *immediately* rather than parked on
        # the advisory lock for the length of the paid call. Before this batch it
        # waited, and on 2026-08-30 seven such waits were killed by Postgres at
        # the 120s statement timeout instead of ever being answered.
        started_at = time.monotonic()
        with pytest.raises(GenerationRequestInProgress):
            await _run()
        # Any finite bound proves the fix: under the blocking lock this call
        # waits for a release that only happens further down this test, so it
        # would never return at all. The generous ceiling is only there to keep
        # a slow CI container from turning a real result into a flake.
        refusal_seconds = time.monotonic() - started_at
        assert refusal_seconds < 5.0, refusal_seconds
        assert client.calls == 1

        client.release.set()
        first = await first_task

        # What must not change: one paid call and one artifact for the scope.
        assert first.generated is True
        assert client.calls == 1

        async with session_factory() as session:
            await _set_search_path(session)
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(Analysis)
                    .where(Analysis.user_id == user_id, Analysis.analysis_type == "morning")
                )
                == 1
            )

        # A *sequential* retry of the identical request still reuses the stored
        # analysis and pays nothing — refusing a concurrent caller did not turn
        # the reuse path off.
        reused = await _run()
        assert reused.generated is False
        assert reused.analysis.id == first.analysis.id
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
async def test_more_complete_morning_inputs_generate_new_historical_read(
    db_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The backstop must not alias a completed packet onto an earlier empty read."""
    session_factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    user_id = uuid.uuid4()
    subject_date = date(2026, 8, 20)
    client = CountingGenerationClient()

    async def packet(
        self: MorningAnalysisService,
        player: Profile,
        requested_date: date,
    ) -> dict[str, Any]:
        inputs = await morning_input_presence(
            self.session,
            user_id=player.id,
            subject_date=requested_date,
        )
        return {
            "packetType": "morning_analysis",
            "subjectDate": requested_date.isoformat(),
            "dailyMetrics": {} if inputs.daily_metrics else None,
            "sleep": {} if inputs.sleep else None,
            "verdict": {"status": "Green"},
        }

    monkeypatch.setattr(MorningAnalysisService, "assemble_context_packet", packet)

    async with session_factory() as session:
        await _set_search_path(session)
        session.add(
            Profile(
                id=user_id,
                display_name="Completeness Identity",
                role=UserRole.player,
                timezone="UTC",
                is_active=True,
            )
        )
        await session.commit()

    async def run(*, force: bool) -> Any:
        async with session_factory() as session:
            await _set_search_path(session)
            player = await session.get(Profile, user_id)
            assert player is not None
            return await MorningAnalysisService(session).generate_and_store(
                player,
                subject_date,
                client=client,
                force=force,
            )

    try:
        empty = await run(force=True)
        assert empty.generated is True
        assert empty.analysis.context_packet["inputCompletenessVersion"] == (
            "daily_metrics:0|sleep:0"
        )

        async with session_factory() as session:
            await _set_search_path(session)
            session.add_all(
                [
                    DailyMetric(
                        user_id=user_id,
                        calendar_date=subject_date,
                        phase=DAILY_METRIC_PHASE_MORNING,
                        raw_payload={},
                    ),
                    Sleep(
                        user_id=user_id,
                        calendar_date=subject_date,
                        duration_sec=7 * 3600,
                        raw_payload={},
                    ),
                ]
            )
            await session.commit()

        complete = await run(force=False)
        identical = await run(force=False)

        assert complete.generated is True
        assert complete.analysis.id != empty.analysis.id
        assert complete.analysis.context_packet["inputCompletenessVersion"] == (
            "daily_metrics:1|sleep:1"
        )
        assert identical.generated is False
        assert identical.analysis.id == complete.analysis.id
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
        await session.flush()
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

        # Batch 232.1: same contract on the activity-scoped path — refused fast,
        # never queued behind somebody else's Anthropic call.
        started_at = time.monotonic()
        with pytest.raises(GenerationRequestInProgress):
            await _run()
        assert time.monotonic() - started_at < 5.0
        assert client.calls == 1

        client.release.set()
        first = await first_task
        assert first.generated is True
        assert client.calls == 1

        reused = await _run()
        assert reused.generated is False
        assert reused.analysis.id == first.analysis.id
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
        await session.flush()
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
