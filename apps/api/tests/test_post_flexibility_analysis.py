from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from src.models.coaching import (
    Activity,
    Analysis,
    DailyMetric,
    KnowledgeBase,
    ManualEntry,
    PlanBlock,
    PlannedWorkout,
)
from src.models.profile import Profile, UserRole
from src.services.post_flexibility_analysis import (
    ANALYSIS_TYPE,
    PROMPT_VERSION,
    FlexibilitySession,
    PostFlexibilityAnalysisService,
    compute_flexibility_consistency,
    is_flexibility_activity,
)
from src.services.post_workout_analysis import ClaudeGenerationResult


@pytest.mark.parametrize(
    ("activity_type", "activity_name", "expected"),
    [
        ("other", "16 Min Mobility Workout", True),
        ("other", "3 Minute Mobility Workout", True),
        ("other", "East Ayrshire Road Cycling", False),
        ("road_biking", "East Ayrshire Road Cycling", False),
        ("strength_training", "Strength maintenance", False),
        ("yoga", "Yoga", False),
    ],
)
def test_is_flexibility_activity_keys_on_name_not_other_type(
    activity_type: str,
    activity_name: str,
    expected: bool,
) -> None:
    activity = Activity(activity_type=activity_type, activity_name=activity_name)
    assert is_flexibility_activity(activity) is expected


def test_compute_flexibility_consistency_counts_streak_and_frequency() -> None:
    user_id = uuid.uuid4()
    as_of = date(2026, 7, 2)
    sessions = [
        FlexibilitySession(user_id, as_of - timedelta(days=offset), 16)
        for offset in (0, 1, 2, 5, 8, 20, 35)
    ]

    result = compute_flexibility_consistency(sessions, as_of_date=as_of)

    assert result.current_streak == 3
    assert result.sessions_this_week == 3
    assert result.sessions_4w == 6
    assert result.sessions_per_week_4w == 1.5


@dataclass
class FakeFlexibilityClient:
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
                "**Mobility read:** good consistency.\n\n"
                "- Heart rate stayed relaxed.\n"
                "- Keep the light routine tomorrow."
            ),
            raw_response={
                "id": "msg_post_flexibility_test",
                "model": "claude-test",
                "content": [{"type": "text", "text": "ok"}],
                "packetType": context_packet["packetType"],
            },
            model_name="claude-test",
        )


@pytest.mark.asyncio
async def test_generate_and_store_post_flexibility_analysis_is_lean_and_idempotent(
    db_conn: AsyncConnection,
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()

    async with session_factory() as session:
        player = Profile(
            id=user_id,
            display_name="Flexibility Test",
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
                calendar_date=date(2026, 7, 4),
                resting_heart_rate_bpm=45,
                raw_payload={},
            )
        )
        block = PlanBlock(
            user_id=user_id,
            name="Flexibility Test Block",
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
                workout_date=date(2026, 7, 4),
                title="Mobility",
                workout_type="mobility",
                version=1,
                is_active=True,
                structured_workout={"format": "mobility"},
            )
        )
        session.add(
            PlannedWorkout(
                user_id=user_id,
                plan_block_id=block.id,
                workout_date=date(2026, 7, 7),
                title="Template VO2",
                workout_type="vo2",
                status="skipped",
                version=1,
                is_active=True,
                structured_workout={"format": "bike"},
                source="holiday_pause",
            )
        )
        session.add(
            KnowledgeBase(
                user_id=user_id,
                section="holiday_windows",
                version=1,
                is_active=True,
                source="test",
                content={
                    "windows": [
                        {
                            "startDate": "2026-07-06",
                            "endDate": "2026-07-12",
                            "pausedAtUtc": "2026-07-01T09:00:00",
                            "resumedAtUtc": None,
                        }
                    ]
                },
            )
        )
        activity = Activity(
            user_id=user_id,
            garmin_activity_id=123456,
            activity_name="16 Min Mobility Workout",
            activity_type="other",
            start_utc=datetime(2026, 7, 4, 7, 30),
            duration_sec=960,
            avg_heart_rate_bpm=72,
            max_heart_rate_bpm=91,
            calories=44,
            raw_summary={"activityType": {"typeKey": "other"}},
        )
        old_ride = Activity(
            user_id=user_id,
            garmin_activity_id=222222,
            activity_name="East Ayrshire Road Cycling",
            activity_type="other",
            start_utc=datetime(2026, 7, 3, 7, 30),
            duration_sec=3600,
            raw_summary={"activityType": {"typeKey": "other"}},
        )
        session.add_all([activity, old_ride])
        await session.commit()

        service = PostFlexibilityAnalysisService(session)
        fake_client = FakeFlexibilityClient()
        pending = await service.pending_flexibility_activities(user_id, since=datetime(2026, 7, 3))
        assert [item.id for item in pending] == [activity.id]

        result = await service.generate_and_store(player, activity, client=fake_client)

        assert result.generated is True
        assert fake_client.calls == 1
        assert fake_client.last_prompt is not None
        assert "Context packet JSON" in fake_client.last_prompt

        packet = result.analysis.context_packet
        assert packet["prompt"]["version"] == PROMPT_VERSION
        assert packet["packetType"] == "post_flexibility_analysis"
        assert packet["subjectDate"] == "2026-07-04"
        assert packet["subjectWeekday"] == "Saturday"
        assert packet["activity"]["activityName"] == "16 Min Mobility Workout"
        assert packet["heartRateReview"]["avgAboveRestingBpm"] == 27
        assert packet["consistency"]["sessions4w"] == 1
        assert packet["plannedWorkouts"][0]["workoutType"] == "mobility"
        holiday_vo2 = next(
            workout for workout in packet["plannedWorkouts"] if workout["title"] == "Template VO2"
        )
        assert holiday_vo2["status"] == "skipped"
        assert holiday_vo2["insideHolidayWindow"] is True
        assert holiday_vo2["isLive"] is False
        assert packet["holidayContext"] == {
            "forwardHorizonDays": 14,
            "nextWeekIsHoliday": True,
            "windows": [
                {
                    "startDate": "2026-07-06",
                    "endDate": "2026-07-12",
                    "isActive": True,
                }
            ],
        }
        assert packet["mobilityBaseline"]["isBaselineHabit"] is True
        assert packet["mobilityBaseline"]["countsAsRecoveryLoad"] is False
        assert packet["consistency"]["interpretation"] == "established_daily_mobility_habit"
        assert packet["knowledgeBase"]["trainingSchedule"]["longRideDay"] == "Saturday"
        assert packet["knowledgeBase"]["analysisRules"]["dataQualityRules"]["rules"]
        assert packet["knowledgeBase"]["analysisRules"]["coachingProtocol"]
        assert packet["activityCheckIn"] is None
        assert packet["guardrails"]["neverFeedsRecoveryDecision"] is True
        assert "do_not_make_recovery_decisions" in packet["prompt"]["outputRules"]
        assert "give_one_light_mobility_only_next_step" in packet["prompt"]["outputRules"]
        packet_json = json.dumps(packet)
        assert "exceeds plan" not in packet_json.lower()
        assert "timeSeriesSummary" not in packet_json
        assert "powerZones" not in packet_json
        assert "avgPowerWatts" not in packet_json

        stored = await session.scalar(select(Analysis).where(Analysis.id == result.analysis.id))
        assert stored is not None
        assert stored.analysis_type == ANALYSIS_TYPE
        assert stored.activity_id == activity.id
        assert stored.output_markdown.startswith("**Mobility read:**")

        second = await service.generate_and_store(player, activity, client=fake_client)
        assert second.generated is False
        assert second.analysis.id == result.analysis.id
        assert fake_client.calls == 1
        assert (
            await service.pending_flexibility_activities(user_id, since=datetime(2026, 7, 1)) == []
        )


@pytest.mark.asyncio
async def test_newer_activity_checkin_makes_flexibility_analysis_pending(
    db_conn: AsyncConnection,
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()

    async with session_factory() as session:
        player = Profile(
            id=user_id,
            display_name="Flexibility Checkin",
            pin_hash="x" * 60,
            role=UserRole.admin,
            timezone="Europe/London",
            is_active=True,
        )
        activity = Activity(
            user_id=user_id,
            garmin_activity_id=987654,
            activity_name="3 Minute Mobility Workout",
            activity_type="other",
            start_utc=datetime(2026, 7, 2, 8, 30),
            duration_sec=180,
            avg_heart_rate_bpm=68,
            raw_summary={},
        )
        session.add(player)
        await session.flush()
        session.add(activity)
        await session.flush()

        service = PostFlexibilityAnalysisService(session)
        fake_client = FakeFlexibilityClient()
        first = await service.generate_and_store(player, activity, client=fake_client)
        assert first.analysis.context_packet["activityCheckIn"] is None

        session.add(
            ManualEntry(
                user_id=user_id,
                activity_id=activity.id,
                entry_date=date(2026, 7, 2),
                entry_at_utc=datetime(2026, 7, 2, 9, 5),
                subjective_score=8,
                rpe=2.0,
                feel="easy loosen-up",
            )
        )
        await session.commit()

        pending = await service.pending_flexibility_activities(user_id, since=datetime(2026, 7, 2))
        assert [item.id for item in pending] == [activity.id]

        second = await service.generate_and_store(player, activity, client=fake_client)
        assert second.generated is True
        assert second.analysis.id != first.analysis.id
        assert second.analysis.context_packet["activityCheckIn"]["feel"] == "easy loosen-up"
