from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from src.models.coaching import Activity, ActivityTimeSeries, Analysis, ManualEntry
from src.models.profile import Profile, UserRole
from src.services.post_workout_analysis import (
    PROMPT_VERSION,
    ClaudeGenerationResult,
    PostWorkoutAnalysisService,
    _is_ride,
    _recovery_decision_packet,
)


@pytest.mark.parametrize(
    ("activity_type", "expected"),
    [
        ("cycling", True),
        ("indoor_cycling", True),
        ("virtual_ride", True),
        ("road_biking", True),  # regression: outdoor rides were silently skipped
        ("mountain_biking", True),
        ("gravel_cycling", True),
        ("walking", False),
        ("breathwork", False),
        ("strength_training", False),
        ("yoga", False),
    ],
)
def test_is_ride_recognizes_garmin_cycling_typekeys(activity_type: str, expected: bool) -> None:
    activity = Activity(activity_type=activity_type, activity_name="Morning session")
    assert _is_ride(activity) is expected


@dataclass
class FakePostWorkoutClient:
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
                "**Workout rating:** strong controlled tempo.\n\n"
                "- **Recovery protocol:** 20 min carbs/protein, 10 min mobility, early sleep.\n"
                "- **Tomorrow impact:** keep tomorrow endurance easy unless HRV holds."
            ),
            raw_response={
                "id": "msg_post_workout_test",
                "model": "claude-test",
                "content": [{"type": "text", "text": "ok"}],
                "packetType": context_packet["packetType"],
            },
            model_name="claude-test",
        )


@pytest.mark.asyncio
async def test_generate_and_store_post_workout_analysis_is_idempotent(
    db_conn: AsyncConnection,
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()

    async with session_factory() as session:
        player = Profile(
            id=user_id,
            display_name="Post Workout Test",
            pin_hash="x" * 60,
            role=UserRole.admin,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(player)
        await session.flush()

        activity = Activity(
            user_id=user_id,
            garmin_activity_id=123456,
            activity_name="Indoor tempo ride",
            activity_type="indoor_cycling",
            start_utc=datetime(2026, 1, 1, 11, 0),
            duration_sec=3600,
            avg_heart_rate_bpm=141,
            max_heart_rate_bpm=166,
            avg_power_watts=221,
            max_power_watts=410,
            normalized_power_watts=234,
            intensity_factor=0.84,
            training_load=85,
            aerobic_training_effect=4.2,
            anaerobic_training_effect=1.1,
            avg_cadence_rpm=86,
            raw_summary={"leftRightBalance": "should not leak into packet"},
        )
        session.add(activity)
        await session.flush()
        session.add_all(
            [
                ActivityTimeSeries(
                    activity_id=activity.id,
                    sample_index=0,
                    elapsed_sec=0,
                    power_watts=120,
                    heart_rate_bpm=92,
                    cadence_rpm=82,
                    performance_condition=1,
                    available_stamina=100,
                    potential_stamina=100,
                    raw_metrics={},
                ),
                ActivityTimeSeries(
                    activity_id=activity.id,
                    sample_index=1,
                    elapsed_sec=300,
                    power_watts=250,
                    heart_rate_bpm=150,
                    cadence_rpm=88,
                    respiration=32,
                    performance_condition=-1,
                    available_stamina=82,
                    potential_stamina=90,
                    raw_metrics={},
                ),
            ]
        )
        await session.commit()

        service = PostWorkoutAnalysisService(session)
        fake_client = FakePostWorkoutClient()
        pending = await service.pending_ride_activities(user_id, since=datetime(2026, 1, 1))
        assert [item.id for item in pending] == [activity.id]

        result = await service.generate_and_store(player, activity, client=fake_client)

        assert result.generated is True
        assert fake_client.calls == 1
        assert fake_client.last_prompt is not None
        assert "Context packet JSON" in fake_client.last_prompt

        packet = result.analysis.context_packet
        assert packet["prompt"]["version"] == PROMPT_VERSION
        assert packet["activity"]["avgPowerWatts"] == 221
        assert packet["activity"]["aerobicTrainingEffect"] == 4.2
        assert packet["timeSeriesSummary"]["performanceCondition"]["start"] == 1
        assert packet["timeSeriesSummary"]["performanceCondition"]["end"] == -1
        assert packet["timeSeriesSummary"]["stamina"]["availableEnd"] == 82
        assert packet["timeSeriesSummary"]["powerZones"]
        assert packet["postRideCheckIn"] is None
        assert packet["recoveryDecision"]["excluded"] is False
        assert "leftRightBalance" not in json.dumps(packet)

        stored = await session.scalar(select(Analysis).where(Analysis.id == result.analysis.id))
        assert stored is not None
        assert stored.activity_id == activity.id
        assert stored.analysis_type == "post_workout"
        assert stored.prompt_version == PROMPT_VERSION
        assert stored.output_markdown.startswith("**Workout rating:**")

        second = await service.generate_and_store(player, activity, client=fake_client)
        assert second.generated is False
        assert second.analysis.id == result.analysis.id
        assert fake_client.calls == 1
        assert await service.pending_ride_activities(user_id, since=datetime(2026, 1, 1)) == []


@pytest.mark.asyncio
async def test_post_ride_checkin_is_folded_into_next_post_workout_analysis(
    db_conn: AsyncConnection,
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()

    async with session_factory() as session:
        player = Profile(
            id=user_id,
            display_name="Post Ride Checkin",
            pin_hash="x" * 60,
            role=UserRole.admin,
            timezone="Europe/London",
            is_active=True,
        )
        activity = Activity(
            user_id=user_id,
            garmin_activity_id=987654,
            activity_name="Lunch ride",
            activity_type="indoor_cycling",
            start_utc=datetime(2026, 6, 20, 12, 0),
            duration_sec=2700,
            avg_power_watts=205,
            raw_summary={},
        )
        session.add(player)
        await session.flush()
        session.add(activity)
        await session.flush()

        service = PostWorkoutAnalysisService(session)
        fake_client = FakePostWorkoutClient()
        first = await service.generate_and_store(player, activity, client=fake_client)

        assert first.generated is True
        assert first.analysis.context_packet["postRideCheckIn"] is None
        assert fake_client.calls == 1

        session.add(
            ManualEntry(
                user_id=user_id,
                activity_id=activity.id,
                entry_date=datetime(2026, 6, 20).date(),
                entry_at_utc=datetime(2026, 6, 20, 13, 5),
                subjective_score=6,
                rpe=7.5,
                feel="legs loaded but no niggles",
                notes="Left calf tight at the end.",
            )
        )
        await session.commit()

        pending = await service.pending_ride_activities(user_id, since=datetime(2026, 6, 20))
        assert [item.id for item in pending] == [activity.id]

        second = await service.generate_and_store(player, activity, client=fake_client)

        assert second.generated is True
        assert second.analysis.id != first.analysis.id
        assert fake_client.calls == 2
        checkin = second.analysis.context_packet["postRideCheckIn"]
        assert checkin["rpe"] == 7.5
        assert checkin["subjectiveScore"] == 6
        assert "calf" in checkin["notes"]
        assert await service.pending_ride_activities(user_id, since=datetime(2026, 6, 20)) == []


def test_strength_session_is_excluded_from_recovery_decisions() -> None:
    activity = Activity(
        user_id=uuid.uuid4(),
        garmin_activity_id=654321,
        activity_name="Strength maintenance",
        activity_type="strength_training",
        start_utc=datetime(2026, 1, 2, 18, 0),
        exclude_from_recovery=True,
        raw_summary={},
    )

    packet = _recovery_decision_packet(activity)

    assert packet["excluded"] is True
    assert packet["status"] == "excluded"
    assert "wrist-HR" in packet["reason"]
