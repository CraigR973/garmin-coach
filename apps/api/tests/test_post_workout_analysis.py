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
    ActivityTimeSeries,
    Analysis,
    ManualEntry,
    PlannedWorkout,
    WorkoutDeliveryProposal,
)
from src.models.profile import Profile, UserRole
from src.services.executable_coaching import adjust_ir_for_verdict
from src.services.post_workout_analysis import (
    PROMPT_VERSION,
    ClaudeGenerationResult,
    PostWorkoutAnalysisService,
    RideGradingTarget,
    _is_ride,
    _planned_ride_ir,
    _recovery_decision_packet,
    detect_ride_deviation,
)
from src.services.workout_delivery import (
    build_intervals_payload,
    build_structured_workout_ir,
    build_zwo_xml,
)

# A structured sweet-spot session: warm-up ramp, a work + recovery block, cool-down.
_SWEET_SPOT_STRUCTURED = {
    "format": "bike",
    "steps": [
        {"label": "Warm-up", "minutes": 10, "target": "50-65%"},
        {"label": "Sweet spot", "pattern": "20 minutes / 5 minutes", "target": "88-94%"},
        {"label": "Cool-down", "minutes": 5, "target": "50%"},
    ],
}

_VO2_STRUCTURED = {
    "format": "bike",
    "steps": [
        {"label": "Warm-up", "minutes": 5, "ramp": [55, 80]},
        {"label": "VO2", "minutes": 2, "target": "120%"},
        {"label": "Recovery", "minutes": 3, "target": "55%"},
        {"label": "Cool-down", "minutes": 5, "ramp": [70, 45]},
    ],
}


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


def _planned_workout(
    structured: dict[str, Any], *, workout_type: str = "cycling"
) -> PlannedWorkout:
    return PlannedWorkout(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        version=1,
        workout_date=date(2026, 1, 5),
        title="Session",
        workout_type=workout_type,
        intensity_target="88-94%",
        structured_workout=structured,
    )


def test_planned_ride_ir_selects_structured_bike_and_falls_back_otherwise() -> None:
    bike = _planned_workout(_SWEET_SPOT_STRUCTURED)
    ir = _planned_ride_ir([bike], 280)
    assert ir is not None
    assert ir["steps"]

    # Free/outdoor or non-bike days have no structured plan → no IR (Batch 44.4).
    mobility = _planned_workout({"format": "mobility", "steps": []}, workout_type="mobility")
    empty_bike = _planned_workout({"format": "bike", "steps": []})
    assert _planned_ride_ir([mobility], 280) is None
    assert _planned_ride_ir([empty_bike], 280) is None
    assert _planned_ride_ir([], 280) is None


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
async def test_generate_and_store_marks_matched_planned_ride_completed(
    db_conn: AsyncConnection,
) -> None:
    """Batch 60: the ride's read links to the day's bike session and flips it to
    ``completed`` so its Today-card row shows the read, not the ride controls."""
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()

    async with session_factory() as session:
        session.add(
            Profile(
                id=user_id,
                display_name="Completion Test",
                pin_hash="x" * 60,
                role=UserRole.admin,
                timezone="Europe/London",
                is_active=True,
            )
        )
        await session.flush()

        planned = PlannedWorkout(
            user_id=user_id,
            version=1,
            workout_date=date(2026, 1, 1),
            title="Tempo ride",
            workout_type="bike_tempo",
            status="planned",
            is_active=True,
        )
        session.add(planned)
        await session.flush()
        planned_id = planned.id

        activity = Activity(
            user_id=user_id,
            garmin_activity_id=222333,
            activity_name="Indoor tempo ride",
            activity_type="indoor_cycling",
            start_utc=datetime(2026, 1, 1, 11, 0),
            duration_sec=3600,
            avg_power_watts=210,
        )
        session.add(activity)
        await session.commit()

        player = await session.get(Profile, user_id)
        assert player is not None
        service = PostWorkoutAnalysisService(session)
        result = await service.generate_and_store(player, activity, client=FakePostWorkoutClient())

        assert result.analysis.planned_workout_id == planned_id
        refreshed = await session.scalar(
            select(PlannedWorkout).where(PlannedWorkout.id == planned_id)
        )
        assert refreshed is not None
        assert refreshed.status == "completed"


@pytest.mark.asyncio
async def test_generate_and_store_leaves_unplanned_ride_unlinked(
    db_conn: AsyncConnection,
) -> None:
    """An unplanned ride (no bike session that day) links to no workout and flips
    nothing — it keeps the standalone After-your-ride section on Home."""
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()

    async with session_factory() as session:
        session.add(
            Profile(
                id=user_id,
                display_name="Unplanned Ride Test",
                pin_hash="x" * 60,
                role=UserRole.admin,
                timezone="Europe/London",
                is_active=True,
            )
        )
        await session.flush()

        # Only a strength session is planned that day — not a bike, so the ride
        # matches nothing.
        session.add(
            PlannedWorkout(
                user_id=user_id,
                version=1,
                workout_date=date(2026, 1, 1),
                title="Strength",
                workout_type="strength_maintenance",
                status="planned",
                is_active=True,
            )
        )
        activity = Activity(
            user_id=user_id,
            garmin_activity_id=444555,
            activity_name="Spontaneous ride",
            activity_type="cycling",
            start_utc=datetime(2026, 1, 1, 11, 0),
            duration_sec=1800,
        )
        session.add(activity)
        await session.commit()

        player = await session.get(Profile, user_id)
        assert player is not None
        service = PostWorkoutAnalysisService(session)
        result = await service.generate_and_store(player, activity, client=FakePostWorkoutClient())
        assert result.analysis.planned_workout_id is None


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
            raw_summary={
                "activitySplits": {
                    "lapDTOs": [
                        {"lapIndex": 1, "elapsedDuration": 600},
                        {"lapIndex": 2, "elapsedDuration": 1200},
                        {"lapIndex": 3, "elapsedDuration": 300},
                        {"lapIndex": 4, "elapsedDuration": 300},
                    ]
                }
            },
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


def _sample(
    activity_id: uuid.UUID,
    index: int,
    elapsed: float,
    power: float,
    hr: float,
) -> ActivityTimeSeries:
    return ActivityTimeSeries(
        activity_id=activity_id,
        sample_index=index,
        elapsed_sec=elapsed,
        power_watts=power,
        heart_rate_bpm=hr,
        raw_metrics={},
    )


@pytest.mark.asyncio
async def test_context_packet_grades_work_intervals_for_structured_ride(
    db_conn: AsyncConnection,
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()

    async with session_factory() as session:
        player = Profile(
            id=user_id,
            display_name="Interval Packet",
            pin_hash="x" * 60,
            role=UserRole.admin,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(player)
        await session.flush()

        activity = Activity(
            user_id=user_id,
            garmin_activity_id=770001,
            activity_name="Sweet spot session",
            activity_type="indoor_cycling",
            start_utc=datetime(2026, 1, 5, 11, 0),
            duration_sec=2400,
            avg_power_watts=205,
            raw_summary={},
        )
        session.add(activity)
        await session.flush()

        session.add(
            PlannedWorkout(
                user_id=user_id,
                workout_date=date(2026, 1, 5),
                version=1,
                title="Sweet spot",
                workout_type="cycling",
                status="planned",
                is_active=True,
                intensity_target="88-94%",
                structured_workout=_SWEET_SPOT_STRUCTURED,
                source="test",
            )
        )
        # IR windows: warm-up [0,600) work [600,1800) recovery [1800,2100) cool-down [2100,2400).
        session.add_all(
            [
                _sample(activity.id, 0, 100, 150, 110),
                _sample(activity.id, 1, 700, 255, 150),
                _sample(activity.id, 2, 1200, 255, 150),
                _sample(activity.id, 3, 1700, 255, 150),
                _sample(activity.id, 4, 1900, 130, 120),
                _sample(activity.id, 5, 2200, 120, 110),
                _sample(activity.id, 6, 2399, 120, 110),
            ]
        )
        await session.commit()

        packet = await PostWorkoutAnalysisService(session).assemble_context_packet(player, activity)

        assert packet["subjectWeekday"] == "Monday"
        assert packet["knowledgeBase"]["analysisRules"]["dataQualityRules"]["rules"]
        assert packet["knowledgeBase"]["analysisRules"]["coachingProtocol"]
        ir = packet["plannedWorkoutIr"]
        assert ir is not None
        assert ir["steps"]
        assert packet["gradingTarget"]["source"] == "planned_workout"
        assert packet["gradingTarget"]["proposalId"] is None

        intervals = packet["intervals"]
        assert [item["role"] for item in intervals] == ["warmup", "work", "recovery", "cooldown"]
        work = intervals[1]
        assert work["avgPowerWatts"] == 255.0
        assert work["adherence"] == "on"  # 255 W ≈ 91% of the seeded 280 W FTP
        for ungraded in (intervals[0], intervals[2], intervals[3]):
            assert ungraded["adherence"] is None

        execution = packet["execution"]
        assert execution["hasPlan"] is True
        assert execution["workIntervalCount"] == 1
        assert "wholeRideContextNote" in execution
        assert execution["boundarySource"] == "planned_durations"

        # The whole-ride average is kept as CONTEXT, not removed.
        assert packet["activity"]["avgPowerWatts"] == 205
        assert "power" in packet["timeSeriesSummary"]
        assert "grade_execution_on_work_intervals_vs_ftp_targets" in packet["prompt"]["outputRules"]


@pytest.mark.asyncio
async def test_context_packet_prefers_delivered_proposal_ir_for_grading(
    db_conn: AsyncConnection,
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()

    async with session_factory() as session:
        player = Profile(
            id=user_id,
            display_name="Delivered IR Packet",
            pin_hash="x" * 60,
            role=UserRole.admin,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(player)
        await session.flush()

        activity = Activity(
            user_id=user_id,
            garmin_activity_id=770004,
            activity_name="Accepted recovery substitution",
            activity_type="indoor_cycling",
            start_utc=datetime(2026, 1, 8, 11, 0),
            duration_sec=900,
            avg_power_watts=154,
            raw_summary={},
        )
        planned = PlannedWorkout(
            user_id=user_id,
            workout_date=date(2026, 1, 8),
            version=1,
            title="VO2 builder",
            workout_type="bike_vo2",
            status="planned",
            is_active=True,
            intensity_target="120% FTP",
            structured_workout=_VO2_STRUCTURED,
            source="test",
        )
        session.add_all([activity, planned])
        await session.flush()

        planned_ir = build_structured_workout_ir(planned, ftp_watts=280)
        delivered_ir = adjust_ir_for_verdict(planned_ir, "Red")
        session.add(
            WorkoutDeliveryProposal(
                user_id=user_id,
                planned_workout_id=planned.id,
                planned_workout_version=planned.version,
                workout_date=planned.workout_date,
                provider="intervals_icu",
                status="pushed",
                proposed_at_utc=datetime(2026, 1, 8, 8, 0),
                approved_at_utc=datetime(2026, 1, 8, 8, 5),
                approved_by_profile_id=user_id,
                pushed_at_utc=datetime(2026, 1, 8, 8, 6),
                intervals_event_id="evt_recovery",
                structured_workout_ir=delivered_ir,
                intervals_payload=build_intervals_payload(delivered_ir),
                zwo_xml=build_zwo_xml(delivered_ir),
            )
        )
        session.add(
            ManualEntry(
                user_id=user_id,
                planned_workout_id=planned.id,
                planned_workout_version=planned.version,
                entry_date=date(2026, 1, 8),
                entry_at_utc=datetime(2026, 1, 8, 12, 0),
                adherence_status="modified",
                actual_workout_json={
                    "changeSummary": "Accepted the recovery substitution instead of VO2.",
                    "intensity": "easy Z2",
                },
            )
        )
        # Delivered IR windows: warm-up [0,150), capped VO2 [150,210), recovery
        # [210,300), cool-down [300,450). The planned VO2 target would mark
        # 154 W as under; the delivered Red substitution caps that work at 60%,
        # so it is on target with the existing interval tolerance.
        session.add_all(
            [
                _sample(activity.id, 0, 30, 154, 110),
                _sample(activity.id, 1, 170, 154, 120),
                _sample(activity.id, 2, 230, 154, 118),
                _sample(activity.id, 3, 330, 140, 112),
            ]
        )
        await session.commit()

        packet = await PostWorkoutAnalysisService(session).assemble_context_packet(player, activity)

        assert packet["gradingTarget"]["source"] == "delivered_proposal"
        assert packet["gradingTarget"]["origin"] == "red_substitution"
        assert packet["gradingTarget"]["adjustment"]["changed"] is True
        assert packet["plannedWorkoutIr"]["name"].startswith("Recovery substitution:")
        work = next(item for item in packet["intervals"] if item["role"] == "work")
        assert work["targetPctFtpLow"] == 60
        assert work["targetPctFtpHigh"] == 60
        assert work["adherence"] == "on"
        assert packet["workoutAdherence"]["adherenceStatus"] == "modified"
        assert (
            "recovery substitution"
            in packet["workoutAdherence"]["actualWorkoutJson"]["changeSummary"]
        )
        assert "grade_against_delivered_proposal_ir_when_present" in packet["prompt"]["outputRules"]
        # Batch 80: an approved coach-adjustment is a sanctioned change, not a
        # self-chosen override, so it carries no deviation verdict even though the
        # ride grades against the eased (not the original VO2) target.
        assert packet["rideDeviation"]["diverged"] is False
        assert packet["rideDeviation"]["wasApprovedAdjustment"] is True
        assert packet["rideDeviation"]["kind"] == "approved_adjustment"


@pytest.mark.asyncio
async def test_context_packet_falls_back_to_whole_ride_without_plan(
    db_conn: AsyncConnection,
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()

    async with session_factory() as session:
        player = Profile(
            id=user_id,
            display_name="Free Ride Packet",
            pin_hash="x" * 60,
            role=UserRole.admin,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(player)
        await session.flush()

        activity = Activity(
            user_id=user_id,
            garmin_activity_id=770002,
            activity_name="Outdoor blast",
            activity_type="road_biking",
            start_utc=datetime(2026, 1, 6, 11, 0),
            duration_sec=1800,
            avg_power_watts=210,
            raw_summary={},
        )
        session.add(activity)
        await session.flush()
        # No planned workout on this date → free/outdoor ride.
        session.add_all(
            [
                _sample(activity.id, 0, 0, 200, 140),
                _sample(activity.id, 1, 600, 240, 150),
                _sample(activity.id, 2, 1200, 190, 145),
            ]
        )
        await session.commit()

        service = PostWorkoutAnalysisService(session)
        packet = await service.assemble_context_packet(player, activity)

        assert packet["plannedWorkoutIr"] is None
        assert packet["intervals"] == []
        assert packet["execution"]["hasPlan"] is False
        # A free ride's average is the real read, so it is not disclaimed as context.
        assert "wholeRideContextNote" not in packet["execution"]
        # The whole-ride zone histogram is still the read for a free ride.
        assert packet["timeSeriesSummary"]["powerZones"]
        # Batch 80: no bike was planned, so a spontaneous ride is not a plan override.
        assert packet["rideDeviation"]["diverged"] is False
        assert packet["rideDeviation"]["kind"] == "free_ride"

        result = await service.generate_and_store(player, activity, client=FakePostWorkoutClient())
        assert result.generated is True
        assert result.analysis.output_markdown.startswith("**Workout rating:**")


@pytest.mark.asyncio
async def test_prompt_version_bump_marks_older_analysis_for_regeneration(
    db_conn: AsyncConnection,
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()

    async with session_factory() as session:
        player = Profile(
            id=user_id,
            display_name="Prompt Bump",
            pin_hash="x" * 60,
            role=UserRole.admin,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(player)
        await session.flush()

        activity = Activity(
            user_id=user_id,
            garmin_activity_id=770003,
            activity_name="Old-prompt ride",
            activity_type="indoor_cycling",
            start_utc=datetime(2026, 1, 7, 11, 0),
            duration_sec=1800,
            avg_power_watts=200,
            raw_summary={},
        )
        session.add(activity)
        await session.flush()
        # An analysis generated by the PREVIOUS prompt version, otherwise up to date.
        session.add(
            Analysis(
                user_id=user_id,
                activity_id=activity.id,
                analysis_type="post_workout",
                subject_date=date(2026, 1, 7),
                generated_at_utc=datetime(2026, 1, 7, 12, 0),
                prompt_version="post-workout-analysis-v1-2026-06-20",
                model_name="claude-old",
                context_packet={"postRideCheckIn": None},
                output_markdown="stale read",
                raw_response={},
            )
        )
        await session.commit()

        service = PostWorkoutAnalysisService(session)
        pending = await service.pending_ride_activities(user_id, since=datetime(2026, 1, 1))
        assert [item.id for item in pending] == [activity.id]

        result = await service.generate_and_store(player, activity, client=FakePostWorkoutClient())
        assert result.generated is True
        assert result.analysis.prompt_version == PROMPT_VERSION

        assert await service.pending_ride_activities(user_id, since=datetime(2026, 1, 1)) == []


# ---------------------------------------------------------------------------
# Batch 80 — deviation verdict (Mark's Q1a): was overriding the plan the right call?
# ---------------------------------------------------------------------------


def _bike_workout(
    *,
    status: str = "planned",
    workout_type: str = "bike_vo2",
    title: str = "VO2 builder",
) -> PlannedWorkout:
    return PlannedWorkout(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        version=1,
        workout_date=date(2026, 1, 8),
        title=title,
        workout_type=workout_type,
        status=status,
        is_active=True,
        intensity_target="120% FTP",
        planned_duration_min=47,
        structured_workout=_VO2_STRUCTURED,
    )


def _ride(*, avg_power: int = 150, avg_hr: int = 120, duration_sec: int = 1800) -> Activity:
    return Activity(
        user_id=uuid.uuid4(),
        garmin_activity_id=99,
        activity_name="Self-chosen ride",
        activity_type="indoor_cycling",
        start_utc=datetime(2026, 1, 8, 11, 0),
        duration_sec=duration_sec,
        avg_power_watts=avg_power,
        avg_heart_rate_bpm=avg_hr,
    )


def _grade(
    *,
    has_plan: bool = True,
    work: int = 1,
    on: int = 0,
    over: int = 0,
    under: int = 1,
) -> dict[str, Any]:
    """Mirror ``summarize_execution``'s shape for the deterministic detector."""
    return {
        "hasPlan": has_plan,
        "workIntervalCount": work,
        "onTargetCount": on,
        "overCount": over,
        "underCount": under,
        "summary": f"{work} work interval(s): {on} on target, {over} over, {under} under.",
        "wholeRideAvgPowerWatts": 150,
    }


def _morning(verdict: str) -> dict[str, Any]:
    return {
        "verdict": verdict,
        "readinessInterpretation": "context readiness note",
        "reasons": [],
        "planAdjustments": [],
    }


def test_detect_deviation_easier_than_planned_on_low_readiness() -> None:
    """Test case 1: a self-chosen easy ride on a hard-planned low-readiness day is a
    deviation, anchored on the objective grade + the Red morning."""
    planned = _bike_workout()
    grading = RideGradingTarget(
        ir={"name": "VO2 builder"}, source="planned_workout", planned_workout=planned, proposal=None
    )
    result = detect_ride_deviation(
        grading_target=grading,
        execution=_grade(work=1, on=0, over=0, under=1),
        planned_workouts=[planned],
        workout_adherence=None,
        activity=_ride(),
        morning_verdict=_morning("Red"),
    )

    assert result["diverged"] is True
    assert result["kind"] == "easier_than_planned"
    assert result["wasApprovedAdjustment"] is False
    assert result["plannedSessionSkipped"] is False
    assert "under target" in result["reason"]
    assert result["morningReadiness"]["verdict"] == "Red"
    assert result["planned"]["workoutType"] == "bike_vo2"
    assert result["signals"]["underCount"] == 1


def test_detect_deviation_harder_than_planned() -> None:
    planned = _bike_workout(workout_type="bike_recovery", title="Recovery spin")
    grading = RideGradingTarget(
        ir={"name": "Recovery"}, source="planned_workout", planned_workout=planned, proposal=None
    )
    result = detect_ride_deviation(
        grading_target=grading,
        execution=_grade(work=2, on=0, over=2, under=0),
        planned_workouts=[planned],
        workout_adherence=None,
        activity=_ride(avg_power=240),
        morning_verdict=_morning("Green"),
    )

    assert result["diverged"] is True
    assert result["kind"] == "harder_than_planned"
    assert "over target" in result["reason"]


def test_detect_deviation_on_plan_attempt_is_not_flagged() -> None:
    """Test case 3: an on-plan ride (some work on target = a real attempt) gets no
    deviation verdict, even if a single interval faded under."""
    planned = _bike_workout()
    grading = RideGradingTarget(
        ir={"name": "VO2 builder"}, source="planned_workout", planned_workout=planned, proposal=None
    )
    result = detect_ride_deviation(
        grading_target=grading,
        execution=_grade(work=3, on=2, over=0, under=1),
        planned_workouts=[planned],
        workout_adherence=None,
        activity=_ride(avg_power=250),
        morning_verdict=_morning("Green"),
    )

    assert result["diverged"] is False
    assert result["kind"] == "on_plan"


def test_detect_deviation_skipped_key_session_flags_regardless_of_grade() -> None:
    """Test case 2: an unjustified skip of a key session is a deviation even before
    the (all-under) objective grade — the good/bad-call judgement is the prompt's,
    anchored on the Green morning this packet carries."""
    skipped = _bike_workout(status="skipped")
    grading = RideGradingTarget(
        ir={"name": "VO2 builder"}, source="planned_workout", planned_workout=skipped, proposal=None
    )
    result = detect_ride_deviation(
        grading_target=grading,
        execution=_grade(work=1, on=0, over=0, under=1),
        planned_workouts=[skipped],
        workout_adherence=None,
        activity=_ride(),
        morning_verdict=_morning("Green"),
    )

    assert result["diverged"] is True
    assert result["kind"] == "skipped_and_rode"
    assert result["plannedSessionSkipped"] is True
    assert "Skipped" in result["reason"]
    assert result["morningReadiness"]["verdict"] == "Green"


def test_detect_deviation_approved_adjustment_is_not_a_deviation() -> None:
    """An approved coach-adjustment (Batch 68/69) is a sanctioned change, never a
    self-chosen override — detected via the IR adjustment flag or the adherence
    marker, even when the ride grades all-under against the eased target."""
    planned = _bike_workout()
    via_ir = RideGradingTarget(
        ir={"adjustment": {"changed": True}, "origin": "red_substitution", "name": "Recovery sub"},
        source="delivered_proposal",
        planned_workout=planned,
        proposal=None,
    )
    result_ir = detect_ride_deviation(
        grading_target=via_ir,
        execution=_grade(work=1, on=0, over=0, under=1),
        planned_workouts=[planned],
        workout_adherence=None,
        activity=_ride(),
        morning_verdict=_morning("Red"),
    )
    assert result_ir["diverged"] is False
    assert result_ir["wasApprovedAdjustment"] is True
    assert result_ir["kind"] == "approved_adjustment"

    via_adherence = RideGradingTarget(
        ir={"name": "Recovery sub"},
        source="delivered_proposal",
        planned_workout=planned,
        proposal=None,
    )
    adherence = ManualEntry(
        user_id=uuid.uuid4(),
        entry_date=date(2026, 1, 8),
        entry_at_utc=datetime(2026, 1, 8, 12, 0),
        adherence_status="modified",
        actual_workout_json={"source": "accepted_adjustment", "changeSummary": "Eased ride."},
    )
    result_adh = detect_ride_deviation(
        grading_target=via_adherence,
        execution=_grade(work=1, on=0, over=0, under=1),
        planned_workouts=[planned],
        workout_adherence=adherence,
        activity=_ride(),
        morning_verdict=_morning("Amber"),
    )
    assert result_adh["diverged"] is False
    assert result_adh["wasApprovedAdjustment"] is True


def test_detect_deviation_free_ride_with_no_plan_is_not_flagged() -> None:
    """A day with no bike plan is a free ride, not a plan override — nothing to
    diverge from, so no deviation verdict (keeps spontaneous rides unflagged)."""
    grading = RideGradingTarget(ir=None, source="none", planned_workout=None, proposal=None)
    result = detect_ride_deviation(
        grading_target=grading,
        execution=_grade(has_plan=False, work=0, on=0, over=0, under=0),
        planned_workouts=[],
        workout_adherence=None,
        activity=_ride(),
        morning_verdict=None,
    )

    assert result["diverged"] is False
    assert result["kind"] == "free_ride"
    assert result["morningReadiness"] is None


def test_detect_deviation_ungradable_plan_is_not_a_false_positive() -> None:
    """A planned ride with no power trace to grade (work=0, nothing on/over/under)
    must not be mistaken for an all-under easier ride."""
    planned = _bike_workout()
    grading = RideGradingTarget(
        ir={"name": "VO2 builder"}, source="planned_workout", planned_workout=planned, proposal=None
    )
    result = detect_ride_deviation(
        grading_target=grading,
        execution=_grade(has_plan=True, work=0, on=0, over=0, under=0),
        planned_workouts=[planned],
        workout_adherence=None,
        activity=_ride(),
        morning_verdict=_morning("Green"),
    )

    assert result["diverged"] is False
    assert result["kind"] == "on_plan"


@pytest.mark.asyncio
async def test_context_packet_flags_self_chosen_easy_ride_on_hard_low_readiness_day(
    db_conn: AsyncConnection,
) -> None:
    """End-to-end: a planned hard VO2, a Red morning, and a self-chosen easy ride →
    the packet carries a diverged read anchored on the Red readiness."""
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()

    async with session_factory() as session:
        player = Profile(
            id=user_id,
            display_name="Deviation Easy",
            pin_hash="x" * 60,
            role=UserRole.admin,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(player)
        await session.flush()

        session.add(
            Analysis(
                user_id=user_id,
                analysis_type="morning",
                subject_date=date(2026, 1, 8),
                generated_at_utc=datetime(2026, 1, 8, 6, 30),
                prompt_version="morning-analysis-test",
                model_name="claude-test",
                verdict="Red",
                context_packet={"verdict": {"readinessInterpretation": "Poor readiness."}},
                output_markdown="cautious",
                raw_response={},
            )
        )
        session.add(
            PlannedWorkout(
                user_id=user_id,
                workout_date=date(2026, 1, 8),
                version=1,
                title="VO2 builder",
                workout_type="bike_vo2",
                status="planned",
                is_active=True,
                intensity_target="120% FTP",
                structured_workout=_VO2_STRUCTURED,
                source="test",
            )
        )
        activity = Activity(
            user_id=user_id,
            garmin_activity_id=880001,
            activity_name="Easy spin instead",
            activity_type="indoor_cycling",
            start_utc=datetime(2026, 1, 8, 11, 0),
            duration_sec=900,
            avg_power_watts=130,
            raw_summary={},
        )
        session.add(activity)
        await session.flush()
        # VO2 IR windows: warm-up [0,300) VO2 [300,420) recovery [420,600) cool [600,900).
        # An easy ~130 W in the VO2 window is well under the 120% work target.
        session.add_all(
            [
                _sample(activity.id, 0, 100, 120, 105),
                _sample(activity.id, 1, 360, 130, 118),
                _sample(activity.id, 2, 500, 120, 110),
                _sample(activity.id, 3, 700, 110, 105),
            ]
        )
        await session.commit()

        packet = await PostWorkoutAnalysisService(session).assemble_context_packet(player, activity)

        deviation = packet["rideDeviation"]
        assert deviation["diverged"] is True
        assert deviation["kind"] == "easier_than_planned"
        assert deviation["morningReadiness"]["verdict"] == "Red"
        assert packet["execution"]["underCount"] >= 1
        assert (
            "render_deviation_verdict_when_ride_diverged_from_plan"
            in packet["prompt"]["outputRules"]
        )


@pytest.mark.asyncio
async def test_context_packet_flags_skipped_key_session_and_rode(
    db_conn: AsyncConnection,
) -> None:
    """A skipped key session plus a self-chosen ride → diverged skip read, anchored
    on the Green morning (the prompt renders the 'set you back' call)."""
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()

    async with session_factory() as session:
        player = Profile(
            id=user_id,
            display_name="Deviation Skip",
            pin_hash="x" * 60,
            role=UserRole.admin,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(player)
        await session.flush()

        session.add(
            Analysis(
                user_id=user_id,
                analysis_type="morning",
                subject_date=date(2026, 1, 8),
                generated_at_utc=datetime(2026, 1, 8, 6, 30),
                prompt_version="morning-analysis-test",
                model_name="claude-test",
                verdict="Green",
                context_packet={"verdict": {"readinessInterpretation": "Good readiness."}},
                output_markdown="go",
                raw_response={},
            )
        )
        session.add(
            PlannedWorkout(
                user_id=user_id,
                workout_date=date(2026, 1, 8),
                version=1,
                title="VO2 builder",
                workout_type="bike_vo2",
                status="skipped",
                is_active=True,
                intensity_target="120% FTP",
                structured_workout=_VO2_STRUCTURED,
                source="test",
            )
        )
        activity = Activity(
            user_id=user_id,
            garmin_activity_id=880002,
            activity_name="Easy ride instead of VO2",
            activity_type="indoor_cycling",
            start_utc=datetime(2026, 1, 8, 11, 0),
            duration_sec=900,
            avg_power_watts=120,
            raw_summary={},
        )
        session.add(activity)
        await session.flush()
        session.add_all(
            [
                _sample(activity.id, 0, 100, 120, 105),
                _sample(activity.id, 1, 360, 125, 116),
                _sample(activity.id, 2, 500, 118, 110),
            ]
        )
        await session.commit()

        packet = await PostWorkoutAnalysisService(session).assemble_context_packet(player, activity)

        deviation = packet["rideDeviation"]
        assert deviation["diverged"] is True
        assert deviation["kind"] == "skipped_and_rode"
        assert deviation["plannedSessionSkipped"] is True
        assert deviation["morningReadiness"]["verdict"] == "Green"


@pytest.mark.asyncio
async def test_context_packet_on_plan_ride_has_no_deviation_verdict(
    db_conn: AsyncConnection,
) -> None:
    """Test case 3 end-to-end: an on-target sweet-spot ride is not flagged, so the
    read has no deviation verdict."""
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()

    async with session_factory() as session:
        player = Profile(
            id=user_id,
            display_name="On Plan Ride",
            pin_hash="x" * 60,
            role=UserRole.admin,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(player)
        await session.flush()

        activity = Activity(
            user_id=user_id,
            garmin_activity_id=880003,
            activity_name="Sweet spot as planned",
            activity_type="indoor_cycling",
            start_utc=datetime(2026, 1, 5, 11, 0),
            duration_sec=2400,
            avg_power_watts=205,
            raw_summary={},
        )
        session.add(activity)
        await session.flush()

        session.add(
            PlannedWorkout(
                user_id=user_id,
                workout_date=date(2026, 1, 5),
                version=1,
                title="Sweet spot",
                workout_type="cycling",
                status="planned",
                is_active=True,
                intensity_target="88-94%",
                structured_workout=_SWEET_SPOT_STRUCTURED,
                source="test",
            )
        )
        # Work window [600,1800) held at ~255 W ≈ 91% of the seeded 280 W FTP = on target.
        session.add_all(
            [
                _sample(activity.id, 0, 100, 150, 110),
                _sample(activity.id, 1, 700, 255, 150),
                _sample(activity.id, 2, 1200, 255, 150),
                _sample(activity.id, 3, 1700, 255, 150),
                _sample(activity.id, 4, 1900, 130, 120),
                _sample(activity.id, 5, 2200, 120, 110),
            ]
        )
        await session.commit()

        packet = await PostWorkoutAnalysisService(session).assemble_context_packet(player, activity)

        assert packet["execution"]["onTargetCount"] == 1
        assert packet["rideDeviation"]["diverged"] is False
        assert packet["rideDeviation"]["kind"] == "on_plan"
