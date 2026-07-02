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
    ActivityTimeSeries,
    Analysis,
    DailyMetric,
    KnowledgeBase,
    PlannedWorkout,
)
from src.models.profile import Profile, UserRole
from src.services.post_walk_analysis import (
    ANALYSIS_TYPE,
    PROMPT_VERSION,
    PostWalkAnalysisService,
    active_recovery_walk_context,
    is_deliberate_walk,
)
from src.services.post_workout_analysis import ClaudeGenerationResult
from src.services.walking_brief import WalkingSession, compute_walking_rollup

TODAY = date(2026, 7, 2)


def _activity(
    *,
    activity_type: str = "walking",
    duration_sec: float | None = 31 * 60,
    distance_m: float | None = None,
) -> Activity:
    return Activity(
        user_id=uuid.uuid4(),
        garmin_activity_id=123,
        activity_name="Morning Walk",
        activity_type=activity_type,
        start_utc=datetime(2026, 7, 2, 8, 0),
        duration_sec=duration_sec,
        distance_m=distance_m,
        raw_summary={},
    )


@pytest.mark.parametrize(
    ("duration_sec", "distance_m", "expected"),
    [
        (10 * 60, 900, False),
        (30 * 60, 1200, True),
        (12 * 60, 3000, True),
    ],
)
def test_is_deliberate_walk_uses_duration_or_distance_threshold(
    duration_sec: float,
    distance_m: float,
    expected: bool,
) -> None:
    assert (
        is_deliberate_walk(_activity(duration_sec=duration_sec, distance_m=distance_m)) is expected
    )


def test_is_deliberate_walk_rejects_non_walking_activity() -> None:
    assert is_deliberate_walk(_activity(activity_type="road_biking", distance_m=5000)) is False


def test_walking_rollup_counts_distance_duration_and_trend() -> None:
    sessions = [
        WalkingSession(
            activity_id=uuid.uuid4(),
            activity_name="Walk",
            activity_type="walking",
            session_date=TODAY - timedelta(days=offset),
            duration_min=30,
            distance_m=3000,
        )
        for offset in (1, 4, 10, 20, 40)
    ]
    result = compute_walking_rollup(sessions, as_of_date=TODAY)
    assert result.window_4w.session_count == 4
    assert result.window_4w.total_distance_m == 12000
    assert result.window_4w.total_duration_min == 120
    assert result.window_12w.session_count == 5
    assert result.trend in {"stable", "increasing", "decreasing"}


def test_active_recovery_context_is_advisory_and_deliberate_only() -> None:
    deliberate = _activity(duration_sec=35 * 60, distance_m=3200)
    deliberate.start_utc = datetime(2026, 7, 1, 8, 0)
    ambient = _activity(duration_sec=8 * 60, distance_m=650)
    ambient.start_utc = datetime(2026, 7, 2, 8, 0)

    context = active_recovery_walk_context([deliberate, ambient], as_of_date=TODAY)

    assert context == {
        "windowDays": 7,
        "deliberateWalkCount": 1,
        "totalDistanceM": 3200,
        "totalDurationMin": 35,
        "advisoryOnly": True,
    }


@dataclass
class FakeWalkClient:
    calls: int = 0

    async def generate(
        self,
        *,
        context_packet: dict[str, Any],
        user_prompt: str,
    ) -> ClaudeGenerationResult:
        self.calls += 1
        assert "Context packet JSON" in user_prompt
        return ClaudeGenerationResult(
            output_markdown="**Walk read:** easy aerobic work.",
            raw_response={"id": "msg_post_walk_test", "packetType": context_packet["packetType"]},
            model_name="claude-test",
        )


@pytest.mark.asyncio
async def test_generate_and_store_post_walk_analysis_is_hr_pace_based_and_idempotent(
    db_conn: AsyncConnection,
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()

    async with session_factory() as session:
        player = Profile(
            id=user_id,
            display_name="Walk Test",
            pin_hash="x" * 60,
            role=UserRole.admin,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(player)
        await session.flush()
        session.add(
            KnowledgeBase(
                user_id=user_id,
                section="profile",
                version=1,
                is_active=True,
                content={
                    "heartRateZones": {
                        "Z1": {"min": 0, "max": 102},
                        "Z2": {"min": 103, "max": 119},
                        "Z3": {"min": 120, "max": 136},
                        "Z4": {"min": 137, "max": 153},
                        "Z5": {"min": 154, "max": None},
                    }
                },
            )
        )
        session.add(
            DailyMetric(
                user_id=user_id,
                calendar_date=TODAY,
                resting_heart_rate_bpm=45,
                raw_payload={},
            )
        )
        session.add(
            PlannedWorkout(
                user_id=user_id,
                workout_date=TODAY,
                title="Rest",
                workout_type="rest",
                version=1,
                is_active=True,
                structured_workout={},
            )
        )
        activity = Activity(
            user_id=user_id,
            garmin_activity_id=456,
            activity_name="Morning Walk",
            activity_type="walking",
            start_utc=datetime(2026, 7, 2, 8, 0),
            duration_sec=40 * 60,
            moving_duration_sec=38 * 60,
            distance_m=3800,
            avg_heart_rate_bpm=108,
            max_heart_rate_bpm=124,
            calories=180,
            raw_summary={},
        )
        ambient = Activity(
            user_id=user_id,
            garmin_activity_id=457,
            activity_name="Short Walk",
            activity_type="walking",
            start_utc=datetime(2026, 7, 2, 12, 0),
            duration_sec=8 * 60,
            distance_m=600,
            raw_summary={},
        )
        session.add_all([activity, ambient])
        await session.flush()
        for index, (hr, speed) in enumerate(
            [(101, 1.5), (105, 1.45), (110, 1.4), (113, 1.35), (118, 1.3), (122, 1.25)]
        ):
            session.add(
                ActivityTimeSeries(
                    activity_id=activity.id,
                    sample_index=index,
                    elapsed_sec=index * 60,
                    heart_rate_bpm=hr,
                    speed_mps=speed,
                    distance_m=index * 500,
                    raw_metrics={},
                )
            )
        await session.commit()

        service = PostWalkAnalysisService(session)
        pending = await service.pending_walk_activities(user_id, since=datetime(2026, 7, 2))
        assert [item.id for item in pending] == [activity.id]

        fake_client = FakeWalkClient()
        result = await service.generate_and_store(player, activity, client=fake_client)

        assert result.generated is True
        assert fake_client.calls == 1
        packet = result.analysis.context_packet
        assert packet["packetType"] == "post_walk_analysis"
        assert packet["prompt"]["version"] == PROMPT_VERSION
        assert packet["activity"]["activityType"] == "walking"
        assert packet["paceReview"]["avgPaceMinPerKm"] == 10.53
        assert packet["heartRateReview"]["hrZoneDistribution"]
        assert packet["activeRecoveryContext"]["deliberateWalkCount"] == 1
        assert packet["guardrails"]["neverFeedsRecoveryDecision"] is True
        packet_json = json.dumps(packet)
        assert "ftpWatts" not in packet_json
        assert "powerZones" not in packet_json
        assert "avgPowerWatts" not in packet_json

        stored = await session.scalar(select(Analysis).where(Analysis.id == result.analysis.id))
        assert stored is not None
        assert stored.analysis_type == ANALYSIS_TYPE
        assert stored.activity_id == activity.id

        second = await service.generate_and_store(player, activity, client=fake_client)
        assert second.generated is False
        assert second.analysis.id == result.analysis.id
        assert fake_client.calls == 1
