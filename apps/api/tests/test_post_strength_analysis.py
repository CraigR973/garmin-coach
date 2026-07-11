from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from src.models.coaching import (
    Activity,
    Analysis,
    DailyMetric,
    ManualEntry,
    PlanBlock,
    PlannedWorkout,
)
from src.models.profile import Profile, UserRole
from src.services.post_strength_analysis import (
    ANALYSIS_TYPE,
    PROMPT_VERSION,
    PostStrengthAnalysisService,
)
from src.services.post_workout_analysis import ClaudeGenerationResult
from src.services.strength_brief import is_strength_activity


@pytest.mark.parametrize(
    ("activity_type", "exclude_from_recovery", "expected"),
    [
        ("strength_training", True, True),
        ("indoor_cardio", True, True),
        ("road_biking", False, False),
        ("indoor_cycling", False, False),
        ("other", False, False),
    ],
)
def test_is_strength_activity_uses_exclude_from_recovery_flag(
    activity_type: str,
    exclude_from_recovery: bool,
    expected: bool,
) -> None:
    activity = Activity(
        activity_type=activity_type,
        activity_name="session",
        exclude_from_recovery=exclude_from_recovery,
    )
    assert is_strength_activity(activity) is expected


@dataclass
class FakeStrengthClient:
    calls: int = 0
    last_prompt: str | None = None

    async def generate(
        self,
        *,
        context_packet: dict[str, Any],
        user_prompt: str,
    ) -> ClaudeGenerationResult:
        self.calls += 1
        self.last_prompt = user_prompt
        return ClaudeGenerationResult(
            output_markdown=(
                "**Strength read:** steady maintenance session.\n\n"
                "- Heart rate stayed relaxed for lifting.\n"
                "- Keep the twice-weekly rhythm."
            ),
            raw_response={
                "id": "msg_post_strength_test",
                "model": "claude-test",
                "content": [{"type": "text", "text": "ok"}],
                "packetType": context_packet["packetType"],
            },
            model_name="claude-test",
        )


@pytest.mark.asyncio
async def test_generate_and_store_post_strength_analysis_is_lean_and_idempotent(
    db_conn: AsyncConnection,
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()

    async with session_factory() as session:
        player = Profile(
            id=user_id,
            display_name="Strength Test",
            pin_hash="x" * 60,
            role=UserRole.admin,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(player)
        await session.flush()

        session.add(
            DailyMetric(
                user_id=user_id,
                calendar_date=date(2026, 7, 2),
                resting_heart_rate_bpm=45,
                raw_payload={},
            )
        )
        block = PlanBlock(
            user_id=user_id,
            name="Strength Test Block",
            version=1,
            sequence_index=1,
            block_type="recovery",
            start_date=date(2026, 6, 29),
            end_date=date(2026, 7, 5),
            goals_json={},
            raw_plan={},
        )
        session.add(block)
        await session.flush()
        session.add(
            PlannedWorkout(
                user_id=user_id,
                plan_block_id=block.id,
                workout_date=date(2026, 7, 2),
                title="Strength maintenance",
                workout_type="strength",
                version=1,
                is_active=True,
                structured_workout={"format": "strength"},
            )
        )
        activity = Activity(
            user_id=user_id,
            garmin_activity_id=345678,
            activity_name="Strength maintenance",
            activity_type="strength_training",
            start_utc=datetime(2026, 7, 2, 7, 30),
            duration_sec=1800,
            avg_heart_rate_bpm=96,
            max_heart_rate_bpm=131,
            calories=210,
            exclude_from_recovery=True,
            raw_summary={"activityType": {"typeKey": "strength_training"}},
        )
        ride = Activity(
            user_id=user_id,
            garmin_activity_id=222222,
            activity_name="East Ayrshire Road Cycling",
            activity_type="road_biking",
            start_utc=datetime(2026, 7, 1, 7, 30),
            duration_sec=3600,
            exclude_from_recovery=False,
            raw_summary={"activityType": {"typeKey": "road_biking"}},
        )
        session.add_all([activity, ride])
        await session.commit()

        service = PostStrengthAnalysisService(session)
        fake_client = FakeStrengthClient()
        pending = await service.pending_strength_activities(user_id, since=datetime(2026, 7, 1))
        assert [item.id for item in pending] == [activity.id]

        result = await service.generate_and_store(player, activity, client=fake_client)

        assert result.generated is True
        assert fake_client.calls == 1
        assert fake_client.last_prompt is not None
        assert "Context packet JSON" in fake_client.last_prompt

        packet = result.analysis.context_packet
        assert packet["prompt"]["version"] == PROMPT_VERSION
        assert packet["packetType"] == "post_strength_analysis"
        assert packet["subjectWeekday"] == "Thursday"
        assert packet["knowledgeBase"]["analysisRules"]["dataQualityRules"]["rules"]
        assert packet["knowledgeBase"]["analysisRules"]["coachingProtocol"]
        assert packet["activity"]["activityName"] == "Strength maintenance"
        assert packet["heartRateReview"]["avgAboveRestingBpm"] == 51
        assert packet["consistency"]["sessions4w"] == 1
        assert packet["consistency"]["trend"] == "insufficient_data"
        assert packet["plannedWorkouts"][0]["workoutType"] == "strength"
        assert packet["activityCheckIn"] is None
        assert packet["guardrails"]["neverFeedsRecoveryDecision"] is True
        packet_json = json.dumps(packet)
        assert "timeSeriesSummary" not in packet_json
        assert "powerZones" not in packet_json
        assert "avgPowerWatts" not in packet_json

        stored = await session.scalar(select(Analysis).where(Analysis.id == result.analysis.id))
        assert stored is not None
        assert stored.analysis_type == ANALYSIS_TYPE
        assert stored.activity_id == activity.id
        assert stored.verdict == "advisory"
        assert stored.output_markdown.startswith("**Strength read:**")

        second = await service.generate_and_store(player, activity, client=fake_client)
        assert second.generated is False
        assert second.analysis.id == result.analysis.id
        assert fake_client.calls == 1
        assert await service.pending_strength_activities(user_id, since=datetime(2026, 7, 1)) == []


@pytest.mark.asyncio
async def test_newer_activity_checkin_makes_strength_analysis_pending(
    db_conn: AsyncConnection,
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()

    async with session_factory() as session:
        player = Profile(
            id=user_id,
            display_name="Strength Checkin",
            pin_hash="x" * 60,
            role=UserRole.admin,
            timezone="Europe/London",
            is_active=True,
        )
        activity = Activity(
            user_id=user_id,
            garmin_activity_id=987654,
            activity_name="Lower Body Strength",
            activity_type="strength_training",
            start_utc=datetime(2026, 7, 2, 8, 30),
            duration_sec=2100,
            avg_heart_rate_bpm=98,
            exclude_from_recovery=True,
            raw_summary={},
        )
        session.add(player)
        await session.flush()
        session.add(activity)
        await session.flush()

        service = PostStrengthAnalysisService(session)
        fake_client = FakeStrengthClient()
        first = await service.generate_and_store(player, activity, client=fake_client)
        assert first.analysis.context_packet["activityCheckIn"] is None

        session.add(
            ManualEntry(
                user_id=user_id,
                activity_id=activity.id,
                entry_date=date(2026, 7, 2),
                entry_at_utc=datetime(2026, 7, 2, 9, 5),
                subjective_score=7,
                rpe=6.0,
                feel="legs worked",
            )
        )
        await session.commit()

        pending = await service.pending_strength_activities(user_id, since=datetime(2026, 7, 2))
        assert [item.id for item in pending] == [activity.id]

        second = await service.generate_and_store(player, activity, client=fake_client)
        assert second.generated is True
        assert second.analysis.id != first.analysis.id
        assert second.analysis.context_packet["activityCheckIn"]["feel"] == "legs worked"
