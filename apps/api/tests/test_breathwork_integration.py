from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from src.models.coaching import Activity, DailyMetric, PlannedWorkout, Sleep
from src.models.profile import Profile, UserRole
from src.services.breathwork_brief import (
    BreathworkBriefService,
    BreathworkSession,
    compute_breathwork_rollup,
    is_breathwork_activity,
)
from src.services.morning_analysis import _morning_verdict, should_recommend_breathwork

TODAY = date(2026, 7, 2)


def _activity(activity_type: str) -> Activity:
    return Activity(
        user_id=uuid.uuid4(),
        garmin_activity_id=123,
        activity_name="Breathwork",
        activity_type=activity_type,
        start_utc=datetime(2026, 7, 2, 8, 0),
        duration_sec=180,
        raw_summary={},
    )


def test_breathwork_selector_uses_garmin_breathwork_type() -> None:
    assert is_breathwork_activity(_activity("breathwork")) is True
    assert is_breathwork_activity(_activity("walking")) is False
    assert is_breathwork_activity(_activity("other")) is False


def test_breathwork_rollup_counts_frequency_duration_and_trend() -> None:
    sessions = [
        BreathworkSession(
            activity_id=uuid.uuid4(),
            activity_name="Breathwork",
            activity_type="breathwork",
            session_date=TODAY - timedelta(days=offset),
            duration_min=3,
        )
        for offset in (1, 2, 5, 8, 15, 25, 40)
    ]

    result = compute_breathwork_rollup(sessions, as_of_date=TODAY)

    assert result.window_4w.session_count == 6
    assert result.window_4w.total_duration_min == 18
    assert result.window_12w.session_count == 7
    assert result.trend in {"stable", "increasing", "decreasing"}
    assert result.recent_sessions[0].session_date == TODAY - timedelta(days=1)


@pytest.mark.parametrize(
    ("signal", "expected"),
    [
        ({"status": "Red", "readinessLevel": "high", "hrvStatus": "balanced"}, True),
        (
            {
                "status": "Amber",
                "readinessLevel": "low",
                "readinessInterpretation": None,
                "hrvStatus": "balanced",
            },
            True,
        ),
        ({"status": "Amber", "readinessLevel": "high", "hrvStatus": "unbalanced"}, True),
        (
            {
                "status": "Green",
                "readinessLevel": "low",
                "readinessInterpretation": "load_driven",
                "hrvStatus": "balanced",
                "hrvBelowBaseline": False,
            },
            False,
        ),
        (
            {
                "status": "Green",
                "readinessLevel": "high",
                "hrvStatus": "balanced",
                "hrvBelowBaseline": False,
            },
            False,
        ),
    ],
)
def test_breathwork_recommendation_predicate(signal: dict[str, object], expected: bool) -> None:
    assert should_recommend_breathwork(signal) is expected


def test_breathwork_recommendation_is_additive_to_verdict_classification() -> None:
    daily_metric = DailyMetric(
        user_id=uuid.uuid4(),
        calendar_date=TODAY,
        hrv_weekly_avg_ms=38,
        hrv_baseline_low_ms=43,
        hrv_status="Unbalanced",
        raw_payload={},
    )
    sleep = Sleep(
        user_id=daily_metric.user_id,
        calendar_date=TODAY,
        score=74,
        raw_payload={},
        factors_json={},
    )
    workout = PlannedWorkout(
        user_id=daily_metric.user_id,
        workout_date=TODAY,
        version=1,
        title="Endurance",
        workout_type="bike_endurance",
        structured_workout={},
    )
    brief = compute_breathwork_rollup(
        [
            BreathworkSession(
                activity_id=uuid.uuid4(),
                activity_name="Breathwork",
                activity_type="breathwork",
                session_date=TODAY - timedelta(days=1),
                duration_min=3,
            )
        ],
        as_of_date=TODAY,
    )

    verdict = _morning_verdict(
        daily_metric=daily_metric,
        sleep=sleep,
        age_adjusted_sleep_score=78,
        manual_entries=[],
        planned_workouts=[workout],
        breathwork_brief=brief,
    )

    assert verdict["status"] == "Red"
    assert any("breathwork session" in item for item in verdict["planAdjustments"])


def test_green_high_readiness_morning_does_not_get_breathwork_recommendation() -> None:
    daily_metric = DailyMetric(
        user_id=uuid.uuid4(),
        calendar_date=TODAY,
        readiness_level="High",
        hrv_weekly_avg_ms=50,
        hrv_baseline_low_ms=43,
        hrv_status="Balanced",
        raw_payload={},
    )
    sleep = Sleep(
        user_id=daily_metric.user_id,
        calendar_date=TODAY,
        score=78,
        raw_payload={},
        factors_json={},
    )
    workout = PlannedWorkout(
        user_id=daily_metric.user_id,
        workout_date=TODAY,
        version=1,
        title="Endurance",
        workout_type="bike_endurance",
        structured_workout={},
    )

    verdict = _morning_verdict(
        daily_metric=daily_metric,
        sleep=sleep,
        age_adjusted_sleep_score=82,
        manual_entries=[],
        planned_workouts=[workout],
    )

    assert verdict["status"] == "Green"
    assert not any("breathwork session" in item for item in verdict["planAdjustments"])


@pytest.mark.asyncio
async def test_breathwork_brief_service_counts_only_breathwork_activities(
    db_conn: AsyncConnection,
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()

    async with session_factory() as session:
        player = Profile(
            id=user_id,
            display_name="Breathwork Test",
            pin_hash="x" * 60,
            role=UserRole.player,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(player)
        await session.flush()
        session.add_all(
            [
                Activity(
                    user_id=user_id,
                    garmin_activity_id=1001,
                    activity_name="Breathwork",
                    activity_type="breathwork",
                    start_utc=datetime(2026, 7, 1, 20, 0),
                    duration_sec=180,
                    raw_summary={},
                ),
                Activity(
                    user_id=user_id,
                    garmin_activity_id=1002,
                    activity_name="Walk",
                    activity_type="walking",
                    start_utc=datetime(2026, 7, 1, 9, 0),
                    duration_sec=1800,
                    raw_summary={},
                ),
            ]
        )
        await session.commit()

        result = await BreathworkBriefService(session).brief(player, as_of=TODAY)

        assert result.window_4w.session_count == 1
        assert result.window_4w.total_duration_min == 3
        assert result.recent_sessions[0].activity_type == "breathwork"
