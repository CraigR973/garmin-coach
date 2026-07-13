from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from src.auth import get_current_user
from src.database import get_db
from src.main import app
from src.models.coaching import (
    Activity,
    Analysis,
    DailyMetric,
    KnowledgeBase,
    ManualEntry,
    PlanBlock,
    PlannedWorkout,
    Sleep,
    TemperatureReading,
    WeatherDaily,
)
from src.models.profile import Profile, UserRole
from src.routers import daily_loop as daily_loop_router
from src.services.daily_loop import (
    ANALYSIS_TYPE_POST_FLEXIBILITY,
    ANALYSIS_TYPE_POST_STRENGTH,
    ANALYSIS_TYPE_POST_WALK,
    ANALYSIS_TYPE_POST_WORKOUT,
    DailyLoopService,
)
from src.services.executable_coaching import ExecutableCoachingService
from src.services.workout_delivery import IntervalsCreateResult

_BIKE_STRUCTURED = {
    "format": "bike",
    "steps": [
        {"label": "Warm-up", "minutes": 15, "target": "easy spin"},
        {
            "label": "Main set",
            "repeats": 3,
            "pattern": "5x 30s on / 30s off",
            "target": "105-110% FTP 95rpm",
        },
        {"label": "Cool-down", "minutes": 10, "target": "easy spin"},
    ],
}


class _FakeIntervals:
    """Minimal intervals.icu stand-in for exercising the delivery rail in tests."""

    def __init__(self) -> None:
        self._counter = 0

    async def create_workout_event(self, payload: dict) -> IntervalsCreateResult:
        self._counter += 1
        event_id = f"evt_{self._counter}"
        return IntervalsCreateResult(event_id=event_id, raw_response={"id": event_id})

    async def update_workout_event(self, event_id: str, payload: dict) -> IntervalsCreateResult:
        return IntervalsCreateResult(event_id=event_id, raw_response={"id": event_id})

    async def delete_workout_event(self, event_id: str) -> None:
        return None


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
    flexibility_activity_id = uuid.uuid4()
    strength_activity_id = uuid.uuid4()

    async with session_factory() as session:
        player = Profile(
            id=user_id,
            display_name="Daily Loop Test",
            pin_hash="x" * 60,
            role=UserRole.player,
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
            Activity(
                id=flexibility_activity_id,
                user_id=user_id,
                garmin_activity_id=998878,
                activity_name="16 Min Mobility Workout",
                activity_type="other",
                start_utc=datetime(2026, 6, 20, 8, 0),
                duration_sec=960,
                avg_heart_rate_bpm=72,
                raw_summary={},
            )
        )
        session.add(
            Activity(
                id=strength_activity_id,
                user_id=user_id,
                garmin_activity_id=998880,
                activity_name="Strength maintenance",
                activity_type="strength_training",
                start_utc=datetime(2026, 6, 20, 7, 0),
                duration_sec=1800,
                avg_heart_rate_bpm=96,
                exclude_from_recovery=True,
                raw_summary={},
            )
        )
        session.add(
            Activity(
                user_id=user_id,
                garmin_activity_id=998879,
                activity_name="Breathwork",
                activity_type="breathwork",
                start_utc=datetime(2026, 6, 19, 20, 0),
                duration_sec=180,
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
                    "metricsVsBaselines": [
                        {
                            "metricKey": "hrv_7_day_avg_ms",
                            "label": "HRV (7-day)",
                            "currentValue": 51,
                            "baselineMedian": 49,
                            "lowerQuartile": 43,
                            "upperQuartile": 57,
                            "sampleCount": 14,
                            "excludedSampleCount": 70,
                            "reliabilityStartDate": "2026-06-11",
                        }
                    ],
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
        session.add(
            Analysis(
                user_id=user_id,
                activity_id=flexibility_activity_id,
                analysis_type="post_flexibility",
                subject_date=subject_date,
                generated_at_utc=datetime(2026, 6, 20, 8, 20),
                prompt_version="post-flexibility-v1",
                model_name="claude-sonnet-4-6",
                verdict="advisory",
                output_markdown="**Mobility read:** relaxed and consistent.",
                context_packet={
                    "activity": {
                        "activityName": "16 Min Mobility Workout",
                        "activityType": "other",
                    },
                    "heartRateReview": {"avgAboveRestingBpm": 24},
                    "consistency": {"currentStreak": 3, "sessions4w": 18},
                },
                raw_response={},
            )
        )
        session.add(
            Analysis(
                user_id=user_id,
                activity_id=strength_activity_id,
                analysis_type="post_strength",
                subject_date=subject_date,
                generated_at_utc=datetime(2026, 6, 20, 8, 25),
                prompt_version="post-strength-v1",
                model_name="claude-sonnet-4-6",
                verdict="advisory",
                output_markdown="**Strength read:** steady maintenance session.",
                context_packet={
                    "activity": {
                        "activityName": "Strength maintenance",
                        "activityType": "strength_training",
                    },
                    "heartRateReview": {"avgAboveRestingBpm": 51},
                    "consistency": {"sessions4w": 6, "trend": "stable"},
                },
                raw_response={},
            )
        )
        await session.commit()

    app.dependency_overrides[get_current_user] = lambda: player
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
    assert payload["data"]["morningAnalysis"]["verdict"] == "green"
    baselines = payload["data"]["morningAnalysis"]["metricsVsBaselines"]
    assert baselines[0]["metricKey"] == "hrv_7_day_avg_ms"
    assert baselines[0]["currentValue"] == 51
    assert baselines[0]["lowerQuartile"] == 43
    assert payload["data"]["dailyMetrics"]["readinessScore"] == 71
    assert payload["data"]["sleep"]["ageAdjustedScore"] == 74
    assert payload["data"]["postWorkoutAnalyses"][0]["activityName"] == "Tempo ride"
    assert "Recovery protocol" in payload["data"]["postWorkoutAnalyses"][0]["outputMarkdown"]
    assert (
        payload["data"]["postFlexibilityAnalyses"][0]["activityName"] == "16 Min Mobility Workout"
    )
    assert payload["data"]["postFlexibilityAnalyses"][0]["consistency"]["currentStreak"] == 3
    assert "Mobility read" in payload["data"]["postFlexibilityAnalyses"][0]["outputMarkdown"]
    assert payload["data"]["postStrengthAnalyses"][0]["activityName"] == "Strength maintenance"
    assert payload["data"]["postStrengthAnalyses"][0]["consistency"]["sessions4w"] == 6
    assert "Strength read" in payload["data"]["postStrengthAnalyses"][0]["outputMarkdown"]
    assert payload["data"]["breathworkBrief"]["window4w"]["sessionCount"] == 1
    assert payload["data"]["breathworkBrief"]["window4w"]["totalDurationMin"] == 3
    assert payload["data"]["sleepProjection"]["status"] == "fallback"
    assert payload["data"]["sleepProjection"]["headline"] == "Use the usual sleep protocol"
    assert payload["data"]["plannedWorkouts"][0]["title"] == "Strength maintenance"
    assert payload["data"]["dataQualityWarnings"][0]["status"] == "active"
    # Batch 48 loop state is serialized on every payload. dayPhase is wall-clock
    # dependent (evening → wind_down), so assert shape, not the exact stage; no
    # plan block is seeded here, so the block signals are null/false.
    loop_state = payload["data"]["loopState"]
    assert loop_state["dayPhase"] in {"rest_day", "pre_training", "post_training", "wind_down"}
    assert loop_state["nextAction"] in {"await_training", "review_session", "wind_down", "rest"}
    assert loop_state["blockPhase"] is None
    assert loop_state["atBlockBoundary"] is False


@pytest.mark.asyncio
async def test_get_daily_loop_hides_stale_hive_temperature(db_conn: AsyncConnection) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()
    subject_date = date(2026, 6, 21)

    async with session_factory() as session:
        player = Profile(
            id=user_id,
            display_name="Daily Loop Thermal Freshness",
            pin_hash="x" * 60,
            role=UserRole.player,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(player)
        await session.commit()

    async with session_factory() as session:
        session.add(
            TemperatureReading(
                user_id=user_id,
                source="hive",
                product_id="product-1",
                device_id="device-1",
                captured_at_utc=datetime(2026, 6, 16, 15, 10, 56, 874000),
                temperature_c=22.4,
                target_temperature_c=9.0,
                raw_payload={},
            )
        )
        session.add(
            WeatherDaily(
                user_id=user_id,
                calendar_date=subject_date,
                source="open_meteo",
                latitude=55.6045,
                longitude=-4.5249,
                overnight_low_c=10.1,
                overnight_wind_max_mph=12.0,
                overnight_wind_gust_mph=18.0,
                raw_payload={},
            )
        )
        await session.commit()

    app.dependency_overrides[get_current_user] = lambda: player
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
    thermal = payload["data"]["thermalState"]
    assert thermal["latestTemperatureC"] is None
    assert thermal["targetTemperatureC"] is None
    assert thermal["capturedAtUtc"] == "2026-06-16T15:10:56.874000Z"
    assert thermal["overnightLowC"] == 10.1


@pytest.mark.asyncio
async def test_get_daily_loop_surfaces_fan_intent(db_conn: AsyncConnection) -> None:
    """The fan autopilot's intent rides on thermalState.fans. With auto off the
    manual intent is reported deterministically (no wall-clock-dependent phase)."""
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()
    subject_date = date(2026, 6, 21)

    async with session_factory() as session:
        player = Profile(
            id=user_id,
            display_name="Daily Loop Fan",
            pin_hash="x" * 60,
            role=UserRole.player,
            timezone="Europe/London",
            is_active=True,
            fan_auto_enabled=False,
        )
        session.add(player)
        await session.commit()

    app.dependency_overrides[get_current_user] = lambda: player
    app.dependency_overrides[get_db] = _db_override(session_factory)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                f"/api/v1/daily-loop?subject_date={subject_date.isoformat()}"
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    fan = response.json()["data"]["thermalState"]["fans"][0]
    assert fan["autoEnabled"] is False
    assert fan["mode"] == "manual"
    assert fan["isOn"] is None
    assert fan["speed"] is None


@pytest.mark.asyncio
async def test_get_daily_loop_reports_the_block_boundary(db_conn: AsyncConnection) -> None:
    """The active plan block classifies the loop-state block phase; a
    consolidation week (wk13) flags the end-of-block boundary (Batch 48)."""
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()
    subject_date = date(2026, 6, 21)

    async with session_factory() as session:
        player = Profile(
            id=user_id,
            display_name="Daily Loop Block",
            pin_hash="x" * 60,
            role=UserRole.player,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(player)
        await session.flush()
        session.add(
            PlanBlock(
                user_id=user_id,
                name="Week 13 Consolidation",
                version=1,
                block_type=None,
                start_date=date(2026, 6, 15),
                end_date=date(2026, 6, 28),
            )
        )
        await session.commit()

    app.dependency_overrides[get_current_user] = lambda: player
    app.dependency_overrides[get_db] = _db_override(session_factory)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                f"/api/v1/daily-loop?subject_date={subject_date.isoformat()}"
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    loop_state = response.json()["data"]["loopState"]
    assert loop_state["blockPhase"] == "consolidation"
    assert loop_state["atBlockBoundary"] is True


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
            role=UserRole.player,
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

    app.dependency_overrides[get_current_user] = lambda: player
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


@pytest.mark.asyncio
async def test_manual_entry_returns_immediately_and_queues_brief_generation(
    db_conn: AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()
    subject_date = date(2026, 7, 12)

    async with session_factory() as session:
        player = Profile(
            id=user_id,
            display_name="Queued Brief",
            pin_hash="x" * 60,
            role=UserRole.player,
            timezone="UTC",
            is_active=True,
        )
        session.add(player)
        await session.commit()

    queued = AsyncMock()
    monkeypatch.setattr(daily_loop_router, "_generate_brief_after_checkin", queued)
    monkeypatch.setattr(daily_loop_router, "_local_today", lambda timezone_name: subject_date)

    app.dependency_overrides[get_current_user] = lambda: player
    app.dependency_overrides[get_db] = _db_override(session_factory)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.put(
                f"/api/v1/daily-loop/{subject_date.isoformat()}/manual-entry",
                json={"subjectiveScore": 7, "feel": "steady"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    assert response.json()["data"]["morningAnalysis"] is None
    queued.assert_awaited_once_with(user_id, subject_date)


@pytest.mark.asyncio
async def test_post_ride_checkin_upsert_persists_against_activity(
    db_conn: AsyncConnection,
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()
    activity_id = uuid.uuid4()
    subject_date = date(2026, 6, 20)

    async with session_factory() as session:
        player = Profile(
            id=user_id,
            display_name="Post Ride Mutation",
            pin_hash="x" * 60,
            role=UserRole.player,
            timezone="Europe/London",
            is_active=True,
        )
        activity = Activity(
            id=activity_id,
            user_id=user_id,
            garmin_activity_id=4444,
            activity_name="Tempo ride",
            activity_type="indoor_cycling",
            start_utc=datetime(2026, 6, 20, 11, 30),
            duration_sec=3600,
            raw_summary={},
        )
        analysis = Analysis(
            user_id=user_id,
            activity_id=activity_id,
            analysis_type="post_workout",
            subject_date=subject_date,
            generated_at_utc=datetime(2026, 6, 20, 12, 45),
            prompt_version="post-workout-test",
            model_name="claude-test",
            context_packet={
                "activity": {
                    "activityName": "Tempo ride",
                    "activityType": "indoor_cycling",
                },
                "recoveryDecision": {"status": "ready_for_review"},
                "timeSeriesSummary": {},
            },
            output_markdown="**Recovery protocol:** refuel.",
            raw_response={},
        )
        session.add(player)
        await session.flush()
        session.add_all([activity, analysis])
        await session.commit()

    app.dependency_overrides[get_current_user] = lambda: player
    app.dependency_overrides[get_db] = _db_override(session_factory)
    generate = AsyncMock(return_value=("ride", MagicMock()))
    try:
        with patch("src.routers.daily_loop.generate_post_activity_read", generate):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.put(
                    (
                        f"/api/v1/daily-loop/{subject_date.isoformat()}"
                        f"/activities/{activity_id}/post-ride-check-in"
                    ),
                    json={
                        "subjectiveScore": 6,
                        "rpe": 8,
                        "feel": "hard but fair",
                        "notes": "Left calf tight.",
                    },
                )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    payload = response.json()
    checkin = payload["data"]["postWorkoutAnalyses"][0]["postRideCheckIn"]
    assert checkin["activityId"] == str(activity_id)
    assert checkin["subjectiveScore"] == 6
    assert checkin["rpe"] == 8
    assert checkin["feel"] == "hard but fair"
    generate.assert_awaited_once()
    assert generate.await_args.kwargs["force"] is True

    async with session_factory() as session:
        entry = await session.scalar(
            select(ManualEntry).where(
                ManualEntry.user_id == user_id,
                ManualEntry.activity_id == activity_id,
            )
        )

    assert entry is not None
    assert entry.planned_workout_id is None
    assert entry.notes == "Left calf tight."


@pytest.mark.asyncio
async def test_get_daily_loop_exposes_delivery_state(db_conn: AsyncConnection) -> None:
    """The Today card reads each planned workout's delivery state (Batch 29.4):
    the live push-on-plan-set event plus the un-acted coach adjustment that flips
    the card into its Approve & upload state."""
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()
    subject_date = date(2026, 6, 24)
    workout_id = uuid.uuid4()

    async with session_factory() as session:
        player = Profile(
            id=user_id,
            display_name="Delivery State Test",
            pin_hash="x" * 60,
            role=UserRole.player,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(player)
        await session.flush()
        session.add(
            PlannedWorkout(
                id=workout_id,
                user_id=user_id,
                workout_date=subject_date,
                version=1,
                title="VO2 Max 30/30",
                workout_type="bike_vo2",
                status="planned",
                is_active=True,
                planned_duration_min=60,
                intensity_target="105-110% FTP",
                structured_workout=_BIKE_STRUCTURED,
                source="test",
            )
        )
        await session.commit()

    # Push-on-plan-set delivers the baseline; the morning then produces an Amber
    # adjustment (proposed, not yet approved) — exactly the coach-changed state.
    async with session_factory() as session:
        player = await session.get(Profile, user_id)
        assert player is not None
        service = ExecutableCoachingService(session, intervals_client=_FakeIntervals())
        await service.reconcile_deliveries(player, start_date=subject_date, end_date=subject_date)
        amber = Analysis(
            user_id=user_id,
            analysis_type="morning",
            subject_date=subject_date,
            generated_at_utc=datetime(2026, 6, 24, 6, 30),
            prompt_version="morning-v1",
            verdict="Amber",
            context_packet={"verdict": {"status": "Amber"}},
            output_markdown="Amber",
            raw_response={},
        )
        await service.regenerate_for_verdict(player, subject_date, analysis=amber)

    app.dependency_overrides[get_current_user] = lambda: player
    app.dependency_overrides[get_db] = _db_override(session_factory)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                f"/api/v1/daily-loop?subject_date={subject_date.isoformat()}"
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    delivery = response.json()["data"]["plannedWorkouts"][0]["delivery"]
    assert delivery is not None
    # The as-planned baseline is already live on Zwift (delivered without approval).
    assert delivery["liveStatus"] == "pushed"
    assert delivery["liveOrigin"] == "as_planned"
    assert delivery["intervalsEventId"] == "evt_1"
    # A coach adjustment is waiting → the card shows Approve & upload.
    assert delivery["changed"] is True
    assert delivery["adjustment"]["verdict"] == "Amber"


@pytest.mark.asyncio
async def test_get_daily_loop_excludes_skipped_workouts(db_conn: AsyncConnection) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()
    subject_date = date(2026, 6, 25)

    async with session_factory() as session:
        player = Profile(
            id=user_id,
            display_name="Skipped Workout Test",
            pin_hash="x" * 60,
            role=UserRole.player,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(player)
        await session.flush()
        session.add_all(
            [
                PlannedWorkout(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    workout_date=subject_date,
                    version=1,
                    title="Skipped ride",
                    workout_type="bike_endurance",
                    status="skipped",
                    is_active=True,
                    planned_duration_min=45,
                    intensity_target="Zone 2",
                    structured_workout=_BIKE_STRUCTURED,
                    source="test",
                ),
                PlannedWorkout(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    workout_date=subject_date,
                    version=2,
                    title="Strength maintenance",
                    workout_type="strength",
                    status="planned",
                    is_active=True,
                    planned_duration_min=30,
                    intensity_target="maintenance",
                    structured_workout={},
                    source="test",
                ),
            ]
        )
        await session.commit()

    app.dependency_overrides[get_current_user] = lambda: player
    app.dependency_overrides[get_db] = _db_override(session_factory)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                f"/api/v1/daily-loop?subject_date={subject_date.isoformat()}"
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    workouts = response.json()["data"]["plannedWorkouts"]
    assert [workout["title"] for workout in workouts] == ["Strength maintenance"]


@pytest.mark.asyncio
async def test_post_activity_analyses_collapse_partitions_and_orders(
    db_conn: AsyncConnection,
) -> None:
    """Batch 62.3: the single collapsed query partitions by type and preserves the
    per-type (start_utc desc, generated_at_utc desc) order the four separate
    queries produced."""
    user_id = uuid.uuid4()
    subject_date = date(2026, 6, 20)
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    async with session_factory() as session:
        session.add(
            Profile(
                id=user_id,
                display_name="Collapse Test",
                pin_hash="x" * 60,
                role=UserRole.admin,
                timezone="Europe/London",
                is_active=True,
            )
        )
        await session.commit()

    async with session_factory() as session:
        # Two rides the same day: the later ride must sort first (start_utc desc).
        early_ride = Activity(
            id=uuid.uuid4(),
            user_id=user_id,
            garmin_activity_id=101,
            activity_name="Morning ride",
            activity_type="indoor_cycling",
            start_utc=datetime(2026, 6, 20, 7, 0),
            raw_summary={},
        )
        late_ride = Activity(
            id=uuid.uuid4(),
            user_id=user_id,
            garmin_activity_id=102,
            activity_name="Evening ride",
            activity_type="indoor_cycling",
            start_utc=datetime(2026, 6, 20, 18, 0),
            raw_summary={},
        )
        walk = Activity(
            id=uuid.uuid4(),
            user_id=user_id,
            garmin_activity_id=103,
            activity_name="Walk",
            activity_type="walking",
            start_utc=datetime(2026, 6, 20, 12, 0),
            raw_summary={},
        )
        session.add_all([early_ride, late_ride, walk])
        for activity, analysis_type, gen in [
            (early_ride, ANALYSIS_TYPE_POST_WORKOUT, datetime(2026, 6, 20, 7, 30)),
            (late_ride, ANALYSIS_TYPE_POST_WORKOUT, datetime(2026, 6, 20, 18, 30)),
            (walk, ANALYSIS_TYPE_POST_WALK, datetime(2026, 6, 20, 12, 30)),
        ]:
            session.add(
                Analysis(
                    user_id=user_id,
                    activity_id=activity.id,
                    analysis_type=analysis_type,
                    subject_date=subject_date,
                    generated_at_utc=gen,
                    prompt_version="v1",
                    output_markdown="x",
                    raw_response={},
                )
            )
        await session.commit()

    async with session_factory() as session:
        grouped = await DailyLoopService(session)._post_activity_analyses(
            user_id,
            subject_date,
            (
                ANALYSIS_TYPE_POST_WORKOUT,
                ANALYSIS_TYPE_POST_FLEXIBILITY,
                ANALYSIS_TYPE_POST_STRENGTH,
                ANALYSIS_TYPE_POST_WALK,
            ),
        )

    # Every requested type is a key, even the empty ones.
    assert set(grouped) == {
        ANALYSIS_TYPE_POST_WORKOUT,
        ANALYSIS_TYPE_POST_FLEXIBILITY,
        ANALYSIS_TYPE_POST_STRENGTH,
        ANALYSIS_TYPE_POST_WALK,
    }
    assert grouped[ANALYSIS_TYPE_POST_FLEXIBILITY] == []
    assert grouped[ANALYSIS_TYPE_POST_STRENGTH] == []
    # Both rides land under post_workout, later ride first.
    workout = grouped[ANALYSIS_TYPE_POST_WORKOUT]
    assert [a.activity_id for a in workout] == [late_ride.id, early_ride.id]
    assert [a.activity_id for a in grouped[ANALYSIS_TYPE_POST_WALK]] == [walk.id]
