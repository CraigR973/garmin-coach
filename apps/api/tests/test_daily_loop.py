from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import date, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from src.auth import get_current_player
from src.database import get_db
from src.main import app
from src.models.coaching import (
    Activity,
    Analysis,
    DailyMetric,
    KnowledgeBase,
    ManualEntry,
    PlannedWorkout,
    Sleep,
)
from src.models.profile import PlayerRole, Profile


def _db_override(session_factory: async_sessionmaker[AsyncSession]):
    async def _override() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    return _override


@pytest.mark.asyncio
async def test_get_daily_loop_returns_today_snapshot(db_conn: AsyncConnection) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()
    subject_date = date(2026, 6, 20)
    workout_id = uuid.uuid4()
    activity_id = uuid.uuid4()

    async with session_factory() as session:
        player = Profile(
            id=user_id,
            display_name="Daily Loop Test",
            pin_hash="x" * 60,
            role=PlayerRole.player,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(player)
        await session.commit()

    async with session_factory() as session:
        session.add(
            KnowledgeBase(
                user_id=user_id,
                section="data_quality_rules",
                version=1,
                is_active=True,
                content={
                    "rules": [
                        {
                            "id": "exclude_wrist_hr_strength",
                            "summary": (
                                "Exclude wrist-HR strength sessions from recovery decisions."
                            ),
                            "reason": (
                                "Strength HR from the wrist is too noisy for "
                                "recovery interpretation."
                            ),
                        }
                    ]
                },
            )
        )
        session.add(
            DailyMetric(
                user_id=user_id,
                calendar_date=subject_date,
                readiness_score=71,
                hrv_last_night_avg_ms=49,
                body_battery_end=78,
                raw_payload={},
            )
        )
        session.add(
            Sleep(
                user_id=user_id,
                calendar_date=subject_date,
                score=70,
                age_adjusted_score=74,
                duration_sec=8 * 60 * 60,
                qualifier="Good",
                raw_payload={},
                factors_json={},
            )
        )
        session.add(
            PlannedWorkout(
                id=workout_id,
                user_id=user_id,
                workout_date=subject_date,
                version=2,
                title="Strength maintenance",
                workout_type="strength",
                status="planned",
                is_active=True,
                planned_duration_min=45,
                structured_workout={},
            )
        )
        session.add(
            Activity(
                id=activity_id,
                user_id=user_id,
                garmin_activity_id=998877,
                activity_name="Tempo ride",
                activity_type="indoor_cycling",
                start_utc=datetime(2026, 6, 20, 11, 0),
                avg_power_watts=220,
                aerobic_training_effect=4.1,
                raw_summary={},
            )
        )
        session.add(
            Analysis(
                user_id=user_id,
                analysis_type="morning",
                subject_date=subject_date,
                generated_at_utc=datetime(2026, 6, 20, 6, 35),
                prompt_version="morning-v1",
                model_name="claude-sonnet-4-6",
                verdict="Green",
                output_markdown="**Green light**",
                context_packet={
                    "verdict": {
                        "planAdjustments": ["Keep the scheduled strength work."],
                        "reasons": ["Sleep and HRV are in range."],
                        "readinessInterpretation": "load_driven",
                    },
                    "environment": {
                        "thermalReview": {"summary": "Indoor temperature stayed in range."}
                    },
                },
                raw_response={},
            )
        )
        session.add(
            Analysis(
                user_id=user_id,
                activity_id=activity_id,
                analysis_type="post_workout",
                subject_date=subject_date,
                generated_at_utc=datetime(2026, 6, 20, 12, 20),
                prompt_version="post-workout-v1",
                model_name="claude-sonnet-4-6",
                verdict="ready_for_review",
                output_markdown=(
                    "**Workout rating:** controlled.\n\n"
                    "- **Recovery protocol:** refuel and mobility.\n"
                    "- **Tomorrow impact:** keep endurance easy."
                ),
                context_packet={
                    "activity": {
                        "activityName": "Tempo ride",
                        "activityType": "indoor_cycling",
                    },
                    "recoveryDecision": {"excluded": False, "status": "ready_for_review"},
                    "timeSeriesSummary": {"power": {"avg": 220}},
                },
                raw_response={},
            )
        )
        await session.commit()

    app.dependency_overrides[get_current_player] = lambda: player
    app.dependency_overrides[get_db] = _db_override(session_factory)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                f"/api/v1/daily-loop?subject_date={subject_date.isoformat()}"
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["data"]["subjectDate"] == "2026-06-20"
    assert payload["data"]["morningAnalysis"]["verdict"] == "Green"
    assert payload["data"]["dailyMetrics"]["readinessScore"] == 71
    assert payload["data"]["sleep"]["ageAdjustedScore"] == 74
    assert payload["data"]["postWorkoutAnalyses"][0]["activityName"] == "Tempo ride"
    assert "Recovery protocol" in payload["data"]["postWorkoutAnalyses"][0]["outputMarkdown"]
    assert payload["data"]["plannedWorkouts"][0]["title"] == "Strength maintenance"
    assert payload["data"]["dataQualityWarnings"][0]["status"] == "active"


@pytest.mark.asyncio
async def test_manual_entry_and_adherence_upserts_persist(db_conn: AsyncConnection) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()
    subject_date = date(2026, 6, 20)
    workout_id = uuid.uuid4()

    async with session_factory() as session:
        player = Profile(
            id=user_id,
            display_name="Daily Loop Mutations",
            pin_hash="x" * 60,
            role=PlayerRole.player,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(player)
        await session.commit()

    async with session_factory() as session:
        session.add(
            PlannedWorkout(
                id=workout_id,
                user_id=user_id,
                workout_date=subject_date,
                version=3,
                title="VO2 session",
                workout_type="bike_vo2",
                status="planned",
                is_active=True,
                planned_duration_min=48,
                structured_workout={},
            )
        )
        await session.commit()

    app.dependency_overrides[get_current_player] = lambda: player
    app.dependency_overrides[get_db] = _db_override(session_factory)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            manual_response = await client.put(
                f"/api/v1/daily-loop/{subject_date.isoformat()}/manual-entry",
                json={
                    "bpSystolic": 108,
                    "bpDiastolic": 68,
                    "subjectiveScore": 7,
                    "rpe": 4,
                    "feel": "steady",
                    "supplementsJson": {"summary": "magnesium"},
                    "foodJson": {"summary": "oats"},
                    "notes": "Slept better than expected.",
                },
            )
            adherence_response = await client.put(
                f"/api/v1/daily-loop/{subject_date.isoformat()}/planned-workouts/{workout_id}/adherence",
                json={
                    "status": "modified",
                    "rpe": 8,
                    "feel": "hard but controlled",
                    "notes": "Dropped one rep.",
                    "actualWorkoutJson": {
                        "completedDurationMin": 42,
                        "intensity": "95-100% FTP",
                        "changeSummary": "Completed 5 reps instead of 6.",
                    },
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert manual_response.status_code == 200, manual_response.text
    assert adherence_response.status_code == 200, adherence_response.text

    async with session_factory() as session:
        entries = (
            (
                await session.execute(
                    select(ManualEntry)
                    .where(ManualEntry.user_id == user_id, ManualEntry.entry_date == subject_date)
                    .order_by(ManualEntry.entry_at_utc.asc())
                )
            )
            .scalars()
            .all()
        )

    assert len(entries) == 2
    manual_entry = next(entry for entry in entries if entry.planned_workout_id is None)
    adherence_entry = next(entry for entry in entries if entry.planned_workout_id is not None)

    assert manual_entry.subjective_score == 7
    assert manual_entry.food_json["summary"] == "oats"
    assert adherence_entry.planned_workout_id == workout_id
    assert adherence_entry.planned_workout_version == 3
    assert adherence_entry.adherence_status == "modified"
    assert adherence_entry.actual_workout_json["completedDurationMin"] == 42
