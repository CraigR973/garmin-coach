from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from src.models.coaching import (
    Activity,
    Analysis,
    DailyMetric,
    ManualEntry,
    MetricBaseline,
    PlanBlock,
    PlannedWorkout,
    Sleep,
    TemperatureReading,
    WeatherDaily,
)
from src.models.profile import Profile, UserRole
from src.services.holiday_pause import HolidayPauseService, HolidayWindow
from src.services.morning_analysis import (
    ACWR_AMBER_CAP_THRESHOLD,
    PROMPT_VERSION,
    RECOVERY_TIME_AMBER_CAP_MIN,
    SYSTEM_PROMPT,
    ClaudeGenerationResult,
    MorningAnalysisError,
    MorningAnalysisService,
    _daily_metric_packet,
    _date_label,
    _eased_ride_detail,
    _manual_entry_packet,
    _morning_verdict,
    _rest_day_context,
    _sleep_packet,
    _thermal_action,
    _thermal_review,
    _training_and_activity_fields,
    _training_load_signal,
    _verdict_adjustment_packet,
    _yesterday_load_packet,
    build_morning_user_prompt,
    build_today_actions,
    subjective_score_label,
)
from src.services.personal_baselines import (
    BASELINE_TREND_WINDOW_DAYS,
    READINESS_TREND_DECLINE_POINTS,
    READINESS_TREND_MIN_SAMPLES_PER_HALF,
    SOFT_SLEEP_READINESS_ABSOLUTE_FLOOR,
    readiness_baseline_trend,
)


@dataclass
class FakeMorningClient:
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
                "**Sleep summary:** age-adjusted sleep stays in the cautious band.\n\n"
                "- **Verdict:** Amber, with sleep still below the green line."
            ),
            raw_response={
                "id": "msg_test",
                "model": "claude-test",
                "content": [{"type": "text", "text": "ok"}],
                "contextVerdict": context_packet["verdict"]["status"],
            },
            model_name="claude-test",
        )


class RaisingMorningClient:
    async def generate(
        self,
        *,
        context_packet: dict[str, Any],
        user_prompt: str,
    ) -> ClaudeGenerationResult:
        raise MorningAnalysisError("Claude response hit max_tokens before completing.")


def test_holiday_all_skipped_day_is_framed_as_rest_without_reviving_ride() -> None:
    subject_date = date(2026, 7, 12)
    user_id = uuid.uuid4()
    skipped_ride = PlannedWorkout(
        user_id=user_id,
        workout_date=subject_date,
        version=2,
        title="Endurance Z2",
        workout_type="bike_endurance",
        status="skipped",
        is_active=True,
        source="holiday_pause",
        structured_workout={},
    )
    holiday = HolidayWindow(
        start_date=subject_date,
        end_date=date(2026, 7, 19),
        paused_at_utc=datetime(2026, 7, 11, 12, 0),
    )

    rest_day = _rest_day_context([skipped_ride], [holiday], subject_date=subject_date)
    verdict = _morning_verdict(
        daily_metric=None,
        sleep=None,
        age_adjusted_sleep_score=78,
        manual_entries=[],
        planned_workouts=[skipped_ride],
        rest_day=rest_day,
    )

    assert rest_day == {
        "isRestDay": True,
        "reason": "holiday",
        "insideHolidayWindow": True,
        "allPlannedWorkoutsSkipped": True,
        "holidayWindows": [
            {
                "startDate": "2026-07-12",
                "endDate": "2026-07-19",
                "isActive": True,
            }
        ],
    }
    assert verdict["status"] == "Green"
    assert verdict["dayType"] == "rest"
    assert verdict["hasVo2WorkoutToday"] is False
    adjustments = " ".join(verdict["planAdjustments"]).lower()
    assert "rest day" in adjustments
    assert "proceed" not in adjustments
    assert "planned workout" not in adjustments

    skipped_only = _rest_day_context([skipped_ride], [], subject_date=subject_date)
    assert skipped_only["isRestDay"] is True
    assert skipped_only["reason"] == "all_skipped"


def test_normal_training_day_plan_guidance_is_unchanged() -> None:
    workout = PlannedWorkout(
        user_id=uuid.uuid4(),
        workout_date=date(2026, 7, 21),
        version=1,
        title="Endurance Z2",
        workout_type="bike_endurance",
        status="planned",
        is_active=True,
        structured_workout={},
    )
    rest_day = _rest_day_context([workout], [], subject_date=workout.workout_date)
    verdict = _morning_verdict(
        daily_metric=None,
        sleep=None,
        age_adjusted_sleep_score=78,
        manual_entries=[],
        planned_workouts=[workout],
        rest_day=rest_day,
    )

    assert rest_day["isRestDay"] is False
    assert verdict["dayType"] == "training"
    assert verdict["planAdjustments"] == [
        "Proceed with the planned workout if warm-up confirms readiness."
    ]


def test_subjective_score_boundary_stays_at_five() -> None:
    user_id = uuid.uuid4()
    base_kwargs = {
        "daily_metric": None,
        "sleep": None,
        "age_adjusted_sleep_score": 78,
        "planned_workouts": [],
    }

    amber = _morning_verdict(
        **base_kwargs,
        manual_entries=[
            ManualEntry(
                user_id=user_id,
                entry_date=date(2026, 7, 24),
                entry_at_utc=datetime(2026, 7, 24, 7, 0),
                subjective_score=4,
            )
        ],
    )
    green = _morning_verdict(
        **base_kwargs,
        manual_entries=[
            ManualEntry(
                user_id=user_id,
                entry_date=date(2026, 7, 24),
                entry_at_utc=datetime(2026, 7, 24, 7, 5),
                subjective_score=5,
            )
        ],
    )

    assert amber["status"] == "Amber"
    assert "Subjective score is below 5." in amber["reasons"]
    assert green["status"] == "Green"


@pytest.mark.asyncio
async def test_generate_and_store_morning_analysis_packet_and_output(
    db_conn: AsyncConnection,
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()
    subject_date = date(2026, 1, 1)

    async with session_factory() as session:
        player = Profile(
            id=user_id,
            display_name="Morning Analysis Test",
            role=UserRole.admin,
            timezone="Europe/London",
            latitude=55.6045,
            longitude=-4.5249,
            is_active=True,
        )
        session.add(player)
        await session.flush()
        session.add_all(
            [
                DailyMetric(
                    user_id=user_id,
                    calendar_date=subject_date,
                    recorded_at_utc=datetime(2026, 1, 1, 6, 20),
                    readiness_score=42,
                    readiness_level="Low",
                    recovery_time_min=720,
                    acute_load=650,
                    hrv_weekly_avg_ms=50,
                    hrv_status="Balanced",
                    hrv_baseline_low_ms=43,
                    hrv_baseline_high_ms=57,
                    resting_heart_rate_bpm=45,
                    body_battery_charged=78,
                    raw_payload={"leftRightBalance": "should not leak into packet"},
                ),
                Sleep(
                    user_id=user_id,
                    calendar_date=subject_date,
                    sleep_start_utc=datetime(2026, 1, 1, 0, 17),
                    sleep_end_utc=datetime(2026, 1, 1, 7, 31),
                    score=71,
                    duration_sec=386 * 60,  # 6h26 asleep; 00:17->07:31 is 7h14 in bed
                    rem_sleep_sec=80 * 60,
                    average_spo2_pct=96.0,
                    average_respiration=13.4,
                    resting_heart_rate_bpm=45,
                    avg_overnight_hrv_ms=51,
                    hrv_status="Balanced",
                    raw_payload={},
                    factors_json={},
                ),
                ManualEntry(
                    user_id=user_id,
                    entry_date=subject_date,
                    entry_at_utc=datetime(2026, 1, 1, 6, 15),
                    subjective_score=6,
                    feel="good",
                    supplements_json={},
                    food_json={},
                ),
                PlannedWorkout(
                    user_id=user_id,
                    workout_date=subject_date,
                    version=1,
                    title="VO2 Max 30/30",
                    workout_type="bike_vo2",
                    status="planned",
                    is_active=True,
                    planned_duration_min=60,
                    intensity_target="105-110% FTP",
                    structured_workout={"format": "bike"},
                    source="test",
                ),
                MetricBaseline(
                    user_id=user_id,
                    metric_key="age_adjusted_sleep_score",
                    metric_label="Age-adjusted sleep score",
                    source="test",
                    window_start_date=date(2025, 10, 1),
                    window_end_date=date(2025, 12, 31),
                    sample_count=84,
                    excluded_sample_count=0,
                    mean_value=73,
                    median_value=74,
                    lower_quartile_value=68,
                    upper_quartile_value=80,
                    raw_payload={},
                ),
                WeatherDaily(
                    user_id=user_id,
                    calendar_date=subject_date,
                    source="open_meteo",
                    latitude=55.6045,
                    longitude=-4.5249,
                    overnight_low_c=4.2,
                    overnight_wind_max_mph=18.0,
                    overnight_wind_gust_mph=34.0,
                    raw_payload={},
                ),
                TemperatureReading(
                    user_id=user_id,
                    source="hive",
                    product_id="thermostat",
                    captured_at_utc=datetime(2025, 12, 31, 23, 0),
                    temperature_c=20.2,
                    raw_payload={},
                ),
            ]
        )
        await session.commit()

        fake_client = FakeMorningClient()
        service = MorningAnalysisService(session)
        result = await service.generate_and_store(player, subject_date, client=fake_client)

        assert result.generated is True
        assert fake_client.calls == 1
        assert fake_client.last_prompt is not None
        assert "Context packet JSON" in fake_client.last_prompt

        packet = result.analysis.context_packet
        assert packet["prompt"]["version"] == PROMPT_VERSION
        assert packet["sleep"]["ageAdjustedScore"] == 71
        # Batch 91: local wall-clock bed/wake alongside the *Utc fields. Jan 1 is
        # GMT so the local clock equals the UTC clock (proves the wiring; the BST
        # offset is covered in the pure _sleep_packet test).
        assert packet["sleep"]["sleepStartUtc"] == "2026-01-01T00:17:00Z"
        assert packet["sleep"]["sleepStartLocal"] == "00:17"
        assert packet["sleep"]["sleepEndLocal"] == "07:31"
        # Batch 142: in-bed (bed->wake window) and asleep surfaced as distinct,
        # explicitly-labelled figures so the read never conflates them.
        assert packet["sleep"]["timeInBedMin"] == 434  # 00:17 -> 07:31 window
        assert packet["sleep"]["timeAsleepMin"] == 386
        assert packet["sleep"]["durationMin"] == 386
        # Authoritative header date and the check-in spoken as Mark's word.
        assert packet["subjectDateLabel"] == "Thursday 1 January 2026"
        assert packet["manualEntries"][0]["subjectiveLabel"] == "OK"
        assert packet["verdict"]["subjectiveLabel"] == "OK"
        assert packet["verdict"]["status"] == "Amber"
        assert packet["verdict"]["readinessInterpretation"] is None
        assert packet["verdict"]["readinessBaselineTrend"]["status"] == "insufficient_data"
        assert packet["verdict"]["hasVo2WorkoutToday"] is True
        assert packet["trainingWeekSoFar"]["window"] == {
            "kind": "calendar_week_to_date",
            "startDate": "2025-12-29",
            "endDate": "2026-01-01",
        }
        assert packet["trainingWeekSoFar"]["days"][-1]["planned"][0]["title"] == "VO2 Max 30/30"
        assert packet["trainingWeekSoFar"]["days"][-1]["executed"] == []
        assert packet["environment"]["thermalReview"]["flags"] == [
            "precool_target_missed",
            "wind_disruption_watch",
        ]
        assert packet["environment"]["thermalReview"]["windowSource"] == "sleep"
        assert packet["metricsVsBaselines"][0]["deltaVsBaseline"] == -3.0
        assert any(
            rule["id"] == "no_lr_balance"
            for rule in packet["knowledgeBase"]["dataQualityGuardrails"]
        )
        assert "leftRightBalance" not in json.dumps(packet)

        stored = await session.scalar(select(Analysis).where(Analysis.id == result.analysis.id))
        assert stored is not None
        assert stored.prompt_version == PROMPT_VERSION
        assert stored.model_name == "claude-test"
        assert stored.verdict == "Amber"
        assert stored.output_markdown.startswith("**Sleep summary:**")

        second = await service.generate_and_store(player, subject_date, client=fake_client)
        assert second.generated is False
        assert second.analysis.id == result.analysis.id
        assert fake_client.calls == 1

        # A prompt bump makes the stored read stale even without force=True.
        second.analysis.prompt_version = "morning-analysis-v14-2026-07-24"
        await session.commit()
        refreshed = await service.generate_and_store(player, subject_date, client=fake_client)
        assert refreshed.generated is True
        assert refreshed.analysis.id != result.analysis.id
        assert refreshed.analysis.prompt_version == PROMPT_VERSION
        assert fake_client.calls == 2


@pytest.mark.asyncio
async def test_morning_packet_turns_two_unexplained_reds_into_swap_action(
    db_conn: AsyncConnection,
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()
    subject_date = date(2026, 7, 29)

    async with session_factory() as session:
        player = Profile(
            id=user_id,
            display_name="Chronic Action Test",
            role=UserRole.admin,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(player)
        await session.flush()
        for offset in range(21):
            day = subject_date - timedelta(days=20 - offset)
            session.add(
                Sleep(
                    user_id=user_id,
                    calendar_date=day,
                    score=85,
                    duration_sec=7 * 3600,
                    rem_sleep_sec=90 * 60,
                    deep_sleep_sec=70 * 60,
                    light_sleep_sec=240 * 60,
                    awake_sleep_sec=20 * 60,
                    raw_payload={},
                    factors_json={},
                )
            )
            session.add(
                DailyMetric(
                    user_id=user_id,
                    calendar_date=day,
                    recorded_at_utc=datetime.combine(day, datetime.min.time()),
                    readiness_score=75,
                    readiness_level="High",
                    hrv_weekly_avg_ms=52,
                    hrv_status="Balanced",
                    hrv_baseline_low_ms=43,
                    hrv_baseline_high_ms=57,
                    resting_heart_rate_bpm=45,
                    raw_payload={},
                )
            )
        for day in (subject_date - timedelta(days=6), subject_date - timedelta(days=1)):
            session.add(
                Analysis(
                    user_id=user_id,
                    analysis_type="morning",
                    subject_date=day,
                    generated_at_utc=datetime.combine(day, datetime.min.time()),
                    prompt_version="historical-test",
                    verdict="Red",
                    context_packet={"verdict": {"status": "Red"}},
                    output_markdown="Red.",
                    raw_response={},
                )
            )
        session.add_all(
            [
                ManualEntry(
                    user_id=user_id,
                    entry_date=subject_date,
                    entry_at_utc=datetime(2026, 7, 29, 6, 30),
                    subjective_score=7,
                ),
                PlannedWorkout(
                    user_id=user_id,
                    workout_date=subject_date,
                    version=1,
                    title="VO2 Max 30/30",
                    workout_type="bike_vo2",
                    status="planned",
                    is_active=True,
                    planned_duration_min=60,
                    structured_workout={"format": "bike"},
                    source="test",
                ),
                PlannedWorkout(
                    user_id=user_id,
                    workout_date=subject_date + timedelta(days=2),
                    version=1,
                    title="Endurance Z2",
                    workout_type="bike_endurance",
                    status="planned",
                    is_active=True,
                    planned_duration_min=75,
                    structured_workout={"format": "bike"},
                    source="test",
                ),
            ]
        )
        await session.commit()

        packet = await MorningAnalysisService(session).assemble_context_packet(player, subject_date)

    action = packet["verdict"]["chronicAction"]
    assert action["triggered"] is True
    assert action["kind"] == "rearrange_proposal"
    assert action["triggerSources"] == ["red_morning_cluster"]
    assert action["redMorningCount"] == 2
    assert action["verdictImpact"] == "none"
    swap = packet["verdict"]["swapSuggestion"]
    assert swap["hardDate"] == subject_date.isoformat()
    assert swap["moveToDate"] == (subject_date + timedelta(days=2)).isoformat()
    assert packet["verdict"]["todayActions"][0]["kind"] == "apply_swap"
    assert all(
        item["title"] != "Approve today's deload ride" for item in packet["verdict"]["todayActions"]
    )
    assert "qualify_reds_before_structural_action" in packet["prompt"]["outputRules"]


@pytest.mark.asyncio
async def test_morning_packet_excludes_marks_two_explained_reds(
    db_conn: AsyncConnection,
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()
    subject_date = date(2026, 8, 1)
    friday = subject_date - timedelta(days=1)

    async with session_factory() as session:
        player = Profile(
            id=user_id,
            display_name="Explained Reds Test",
            role=UserRole.admin,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(player)
        await session.flush()
        session.add(_rhr_baseline(user_id))
        for offset in range(21):
            day = subject_date - timedelta(days=20 - offset)
            is_friday = day == friday
            is_saturday = day == subject_date
            session.add(
                Sleep(
                    user_id=user_id,
                    calendar_date=day,
                    score=51 if is_saturday else 68 if is_friday else 85,
                    duration_sec=7 * 3600,
                    rem_sleep_sec=90 * 60,
                    deep_sleep_sec=70 * 60,
                    light_sleep_sec=240 * 60,
                    awake_sleep_sec=20 * 60,
                    raw_payload={},
                    factors_json={},
                )
            )
            session.add(
                DailyMetric(
                    user_id=user_id,
                    calendar_date=day,
                    recorded_at_utc=datetime.combine(day, datetime.min.time()),
                    readiness_score=27 if is_saturday else 20 if is_friday else 75,
                    readiness_level="Low" if is_saturday else "Poor" if is_friday else "High",
                    recovery_time_min=1370 if is_saturday else 2584 if is_friday else 0,
                    acute_load=0 if is_saturday else 198 if is_friday else 50,
                    hrv_weekly_avg_ms=35 if is_saturday else 52,
                    hrv_status="Low" if is_saturday else "Balanced",
                    hrv_baseline_low_ms=43,
                    hrv_baseline_high_ms=57,
                    resting_heart_rate_bpm=48 if is_saturday else 43 if is_friday else 45,
                    raw_payload={},
                )
            )
        session.add_all(
            [
                Analysis(
                    user_id=user_id,
                    analysis_type="morning",
                    subject_date=friday,
                    generated_at_utc=datetime(2026, 7, 31, 8, 0),
                    prompt_version="historical-test",
                    verdict="Red",
                    context_packet={"verdict": {"status": "Red"}},
                    output_markdown="Red.",
                    raw_response={},
                ),
                ManualEntry(
                    user_id=user_id,
                    entry_date=friday,
                    entry_at_utc=datetime(2026, 7, 31, 7, 30),
                    subjective_score=4,
                    notes=(
                        "Presumably due to a harder day's training yesterday and cumulative "
                        "3 day training load."
                    ),
                ),
                ManualEntry(
                    user_id=user_id,
                    entry_date=subject_date,
                    entry_at_utc=datetime(2026, 8, 1, 8, 44),
                    subjective_score=3,
                    feel="Have a bit of a hangover today",
                    notes="Was out last night drinking, around 13 UK units.",
                ),
            ]
        )
        await session.commit()

        packet = await MorningAnalysisService(session).assemble_context_packet(player, subject_date)

    action = packet["verdict"]["chronicAction"]
    assert action["redMorningObservedCount"] == 2
    assert action["redMorningCount"] == 0
    assert action["triggered"] is False
    assert [item["classification"] for item in action["redMorningQualifications"]] == [
        "explained_by_check_in",
        "explained_by_check_in",
    ]
    assert {item["reason"] for item in action["recordedTrainingContext"]} >= {
        "training_load",
        "alcohol",
    }


@pytest.mark.asyncio
async def test_morning_packet_suppresses_sustained_deload_for_recovery_block(
    db_conn: AsyncConnection,
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()
    subject_date = date(2026, 8, 1)

    async with session_factory() as session:
        player = Profile(
            id=user_id,
            display_name="Recovery Block Test",
            role=UserRole.admin,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(player)
        await session.flush()
        recovery_block = PlanBlock(
            user_id=user_id,
            name="PN2 W03 RECOVERY",
            version=1,
            sequence_index=3,
            block_type="recovery",
            start_date=date(2026, 8, 3),
            end_date=date(2026, 8, 9),
            goals_json={},
            raw_plan={},
        )
        session.add(recovery_block)
        await session.flush()
        session.add(
            MetricBaseline(
                user_id=user_id,
                metric_key="readiness_score",
                metric_label="Training readiness",
                source="test",
                window_start_date=date(2026, 5, 1),
                window_end_date=date(2026, 7, 31),
                sample_count=84,
                excluded_sample_count=0,
                mean_value=77,
                median_value=78,
                lower_quartile_value=70,
                upper_quartile_value=84,
                raw_payload={},
            )
        )
        for offset in range(21):
            day = subject_date - timedelta(days=20 - offset)
            session.add_all(
                [
                    Sleep(
                        user_id=user_id,
                        calendar_date=day,
                        score=85,
                        duration_sec=7 * 3600,
                        rem_sleep_sec=90 * 60,
                        deep_sleep_sec=70 * 60,
                        light_sleep_sec=240 * 60,
                        awake_sleep_sec=20 * 60,
                        raw_payload={},
                        factors_json={},
                    ),
                    DailyMetric(
                        user_id=user_id,
                        calendar_date=day,
                        recorded_at_utc=datetime.combine(day, datetime.min.time()),
                        readiness_score=50,
                        readiness_level="Low",
                        hrv_weekly_avg_ms=52,
                        hrv_status="Balanced",
                        hrv_baseline_low_ms=43,
                        hrv_baseline_high_ms=57,
                        resting_heart_rate_bpm=45,
                        raw_payload={},
                    ),
                ]
            )
        session.add(
            PlannedWorkout(
                user_id=user_id,
                plan_block_id=recovery_block.id,
                workout_date=date(2026, 8, 3),
                version=1,
                title="Recovery Z2",
                workout_type="bike_recovery",
                status="planned",
                is_active=True,
                planned_duration_min=45,
                structured_workout={"format": "bike"},
                source="test",
            )
        )
        await session.commit()

        packet = await MorningAnalysisService(session).assemble_context_packet(player, subject_date)

    action = packet["verdict"]["chronicAction"]
    assert action["triggerSources"] == ["sustained_recovery_marker"]
    assert action["suppressedByPlan"] is True
    assert action["triggered"] is False
    assert action["scheduledRecoveryBlocks"] == [
        {
            "name": "PN2 W03 RECOVERY",
            "blockType": "recovery",
            "startDate": "2026-08-03",
            "endDate": "2026-08-09",
        }
    ]
    assert all(
        item["title"] != "Approve today's deload ride" for item in packet["verdict"]["todayActions"]
    )


@pytest.mark.asyncio
async def test_morning_packet_loads_holiday_window_and_suppresses_skipped_ride(
    db_conn: AsyncConnection,
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()
    subject_date = date(2026, 7, 12)

    async with session_factory() as session:
        player = Profile(
            id=user_id,
            display_name="Holiday Morning Test",
            role=UserRole.admin,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(player)
        await session.flush()
        session.add(
            PlannedWorkout(
                user_id=user_id,
                workout_date=subject_date,
                version=2,
                title="Holiday endurance ride",
                workout_type="bike_endurance",
                status="planned",
                is_active=True,
                planned_duration_min=90,
                structured_workout={},
                source="test",
            )
        )
        await session.commit()

        pause = await HolidayPauseService(session).pause(
            player,
            subject_date,
            date(2026, 7, 19),
        )
        assert pause.skipped_count == 1

        packet = await MorningAnalysisService(session).assemble_context_packet(
            player,
            subject_date,
        )

        assert packet["restDay"]["isRestDay"] is True
        assert packet["restDay"]["reason"] == "holiday"
        assert packet["restDay"]["insideHolidayWindow"] is True
        assert packet["plannedWorkouts"][0]["status"] == "skipped"
        assert packet["verdict"]["dayType"] == "rest"
        assert "swapSuggestion" not in packet["verdict"]
        assert packet["verdict"]["weeklyMix"]["shortfall"] is None
        assert packet["verdict"]["chronicAction"]["recordedTrainingContext"] == [
            {
                "startDate": "2026-07-12",
                "endDate": "2026-07-19",
                "reason": "holiday",
                "source": "holiday_plan",
            }
        ]
        adjustments = " ".join(packet["verdict"]["planAdjustments"]).lower()
        assert "rest day" in adjustments
        assert "proceed with the planned workout" not in adjustments
        assert "endurance" not in adjustments

        # Batch 113 (#186): holiday = away for thermal purposes too — no bedroom
        # review or pre-cool action while the room isn't being slept in.
        assert packet["environment"]["thermalReview"] is None
        assert "include_thermal_environment_review" not in packet["prompt"]["outputRules"]
        assert all(action["kind"] != "thermal" for action in packet["verdict"]["todayActions"])


@pytest.mark.asyncio
async def test_generate_and_store_does_not_persist_truncated_morning_analysis(
    db_conn: AsyncConnection,
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()
    subject_date = date(2026, 1, 2)

    async with session_factory() as session:
        player = Profile(
            id=user_id,
            display_name="Morning Analysis Truncation Test",
            role=UserRole.admin,
            timezone="Europe/London",
            latitude=55.6045,
            longitude=-4.5249,
            is_active=True,
        )
        session.add(player)
        await session.commit()

        service = MorningAnalysisService(session)
        with pytest.raises(MorningAnalysisError, match="max_tokens"):
            await service.generate_and_store(player, subject_date, client=RaisingMorningClient())

        count = await session.scalar(
            select(func.count())
            .select_from(Analysis)
            .where(
                Analysis.user_id == user_id,
                Analysis.analysis_type == "morning",
                Analysis.subject_date == subject_date,
            )
        )
        assert count == 0


@pytest.mark.asyncio
async def test_amber_morning_leads_with_week_swap_and_keeps_softening(
    db_conn: AsyncConnection,
) -> None:
    """Batch 66 (#139): a cautious morning with a hard session today plus a later
    easy bike day leads with a concrete week swap; softening stays as fallback."""
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()
    subject_date = date(2026, 1, 1)  # Thursday
    saturday = date(2026, 1, 3)

    async with session_factory() as session:
        player = Profile(
            id=user_id,
            display_name="Swap First Test",
            role=UserRole.admin,
            timezone="Europe/London",
            latitude=55.6045,
            longitude=-4.5249,
            is_active=True,
        )
        session.add(player)
        await session.flush()
        session.add_all(
            [
                DailyMetric(
                    user_id=user_id,
                    calendar_date=subject_date,
                    recorded_at_utc=datetime(2026, 1, 1, 6, 20),
                    readiness_score=42,
                    readiness_level="Low",
                    hrv_weekly_avg_ms=50,
                    hrv_status="Balanced",
                    hrv_baseline_low_ms=43,
                    hrv_baseline_high_ms=57,
                    resting_heart_rate_bpm=45,
                    raw_payload={},
                ),
                Sleep(
                    user_id=user_id,
                    calendar_date=subject_date,
                    score=71,
                    raw_payload={},
                    factors_json={},
                ),
                PlannedWorkout(
                    user_id=user_id,
                    workout_date=subject_date,
                    version=1,
                    title="VO2 Max 30/30",
                    workout_type="bike_vo2",
                    status="planned",
                    is_active=True,
                    planned_duration_min=60,
                    intensity_target="105-110% FTP",
                    structured_workout={"format": "bike"},
                    source="test",
                ),
                PlannedWorkout(
                    user_id=user_id,
                    workout_date=saturday,
                    version=1,
                    title="Z2 + Neuromuscular",
                    workout_type="bike_endurance",
                    status="planned",
                    is_active=True,
                    planned_duration_min=90,
                    intensity_target="Endurance",
                    structured_workout={"format": "bike"},
                    source="test",
                ),
            ]
        )
        await session.commit()

        packet = await MorningAnalysisService(session).assemble_context_packet(player, subject_date)

    assert packet["subjectWeekday"] == "Thursday"
    verdict = packet["verdict"]
    assert verdict["status"] == "Amber"

    swap = verdict["swapSuggestion"]
    assert swap["hardTitle"] == "VO2 Max 30/30"
    assert swap["moveToDate"] == saturday.isoformat()
    assert swap["moveToWeekday"] == "Saturday"
    assert swap["bringForwardTitle"] == "Z2 + Neuromuscular"

    # Batch 86 (#159): the same cautious morning surfaces the deterministic Today
    # action block — the swap leads, then the eased-ride approval carrying the real
    # today-bike id so the frontend can approve through the existing rail.
    actions = verdict["todayActions"]
    assert [action["kind"] for action in actions][:2] == ["apply_swap", "approve_ride"]
    assert actions[0]["targetDate"] == saturday.isoformat()
    assert actions[0]["plannedWorkoutId"] == swap["hardWorkoutId"]
    approve = next(action for action in actions if action["kind"] == "approve_ride")
    assert approve["plannedWorkoutId"] == swap["hardWorkoutId"]

    adjustments = verdict["planAdjustments"]
    # The swap leads; softening stays available as the explicit fallback.
    assert "move it to saturday" in adjustments[0].lower()
    assert any("cut duration" in item.lower() for item in adjustments[1:])

    # Batch 70 (#143): the same cautious morning reports the week's mix and, because
    # today's dropped VO2 can move to Saturday, frames it as re-patched — not lost.
    mix = verdict["weeklyMix"]
    assert mix["shortfall"]["bucket"] == "vo2"
    assert mix["shortfall"]["repatched"] is True
    assert mix["shortfall"]["moveToWeekday"] == "Saturday"
    vo2_bucket = next(bucket for bucket in mix["buckets"] if bucket["bucket"] == "vo2")
    assert vo2_bucket["target"] == 1 and vo2_bucket["atRisk"] is True
    assert any("short this week" in item.lower() for item in adjustments)

    # The KB records the swap-first coaching preference (66.1).
    protocol = next(
        section
        for section in packet["knowledgeBase"]["sections"]
        if section["section"] == "coaching_protocol"
    )
    assert protocol["content"]["lowReadinessResponse"]["preference"] == "swap_first"


@pytest.mark.asyncio
async def test_green_morning_has_no_swap_suggestion(db_conn: AsyncConnection) -> None:
    """A Green morning proceeds as planned — no swap suggestion is attached."""
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()
    subject_date = date(2026, 1, 1)
    saturday = date(2026, 1, 3)

    async with session_factory() as session:
        player = Profile(
            id=user_id,
            display_name="Green No Swap Test",
            role=UserRole.admin,
            timezone="Europe/London",
            latitude=55.6045,
            longitude=-4.5249,
            is_active=True,
        )
        session.add(player)
        await session.flush()
        session.add_all(
            [
                DailyMetric(
                    user_id=user_id,
                    calendar_date=subject_date,
                    recorded_at_utc=datetime(2026, 1, 1, 6, 20),
                    readiness_score=80,
                    readiness_level="High",
                    hrv_weekly_avg_ms=52,
                    hrv_status="Balanced",
                    hrv_baseline_low_ms=43,
                    hrv_baseline_high_ms=57,
                    resting_heart_rate_bpm=44,
                    raw_payload={},
                ),
                Sleep(
                    user_id=user_id,
                    calendar_date=subject_date,
                    score=82,
                    raw_payload={},
                    factors_json={},
                ),
                PlannedWorkout(
                    user_id=user_id,
                    workout_date=subject_date,
                    version=1,
                    title="VO2 Max 30/30",
                    workout_type="bike_vo2",
                    status="planned",
                    is_active=True,
                    planned_duration_min=60,
                    intensity_target="105-110% FTP",
                    structured_workout={"format": "bike"},
                    source="test",
                ),
                PlannedWorkout(
                    user_id=user_id,
                    workout_date=saturday,
                    version=1,
                    title="Z2 + Neuromuscular",
                    workout_type="bike_endurance",
                    status="planned",
                    is_active=True,
                    planned_duration_min=90,
                    intensity_target="Endurance",
                    structured_workout={"format": "bike"},
                    source="test",
                ),
            ]
        )
        await session.commit()

        packet = await MorningAnalysisService(session).assemble_context_packet(player, subject_date)

    assert packet["verdict"]["status"] == "Green"
    assert "swapSuggestion" not in packet["verdict"]
    # Batch 70 (#143): the week's mix is still reported on a Green morning (the week
    # view uses it), but nothing is being eased, so there is no shortfall.
    mix = packet["verdict"]["weeklyMix"]
    assert mix["shortfall"] is None
    vo2_bucket = next(bucket for bucket in mix["buckets"] if bucket["bucket"] == "vo2")
    assert vo2_bucket["target"] == 1 and vo2_bucket["atRisk"] is False


@pytest.mark.asyncio
async def test_morning_packet_overlays_live_vo2max_onto_athlete_profile(
    db_conn: AsyncConnection,
) -> None:
    """Batch 177 (#257): a live daily VO2max reading within the lookback window
    overlays the static seeded profile number (54) in athleteProfile."""
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()
    subject_date = date(2026, 1, 5)

    async with session_factory() as session:
        player = Profile(
            id=user_id,
            display_name="Morning VO2max Packet",
            role=UserRole.admin,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(player)
        await session.flush()
        # The reading is from a month earlier, well inside the 90-day lookback.
        session.add(
            DailyMetric(
                user_id=user_id,
                calendar_date=date(2025, 12, 5),
                vo2max=55.0,
                raw_payload={},
            )
        )
        await session.commit()

        packet = await MorningAnalysisService(session).assemble_context_packet(player, subject_date)

    assert packet["profile"]["athleteProfile"]["vo2max"] == 55.0
    assert packet["profile"]["vo2maxAsOfDate"] == "2025-12-05"


@pytest.mark.asyncio
async def test_morning_packet_falls_back_to_static_vo2max_with_no_reading_on_file(
    db_conn: AsyncConnection,
) -> None:
    """Batch 177 (#257): with no live VO2max reading in the window, the packet
    falls back to the static seeded profile number rather than surfacing None."""
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()
    subject_date = date(2026, 1, 5)

    async with session_factory() as session:
        player = Profile(
            id=user_id,
            display_name="No Morning VO2max Packet",
            role=UserRole.admin,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(player)
        await session.flush()
        await session.commit()

        packet = await MorningAnalysisService(session).assemble_context_packet(player, subject_date)

    assert packet["profile"]["athleteProfile"]["vo2max"] == 54
    assert packet["profile"]["vo2maxAsOfDate"] is None


@pytest.mark.asyncio
async def test_cautious_morning_says_no_vo2_this_week_when_it_cannot_be_repatched(
    db_conn: AsyncConnection,
) -> None:
    """Batch 70 (#143): a readiness-dropped VO2 with no sound later slot is not
    silently lost — the verdict states plainly it won't be made up this week."""
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()
    subject_date = date(2026, 1, 2)  # Friday — VO2 today, no later bike day this week

    async with session_factory() as session:
        player = Profile(
            id=user_id,
            display_name="No VO2 This Week Test",
            role=UserRole.admin,
            timezone="Europe/London",
            latitude=55.6045,
            longitude=-4.5249,
            is_active=True,
        )
        session.add(player)
        await session.flush()
        session.add_all(
            [
                DailyMetric(
                    user_id=user_id,
                    calendar_date=subject_date,
                    recorded_at_utc=datetime(2026, 1, 2, 6, 20),
                    readiness_score=42,
                    readiness_level="Low",
                    hrv_weekly_avg_ms=50,
                    hrv_status="Balanced",
                    hrv_baseline_low_ms=43,
                    hrv_baseline_high_ms=57,
                    resting_heart_rate_bpm=45,
                    raw_payload={},
                ),
                Sleep(
                    user_id=user_id,
                    calendar_date=subject_date,
                    score=71,
                    raw_payload={},
                    factors_json={},
                ),
                PlannedWorkout(
                    user_id=user_id,
                    workout_date=subject_date,
                    version=1,
                    title="VO2 Max 30/30",
                    workout_type="bike_vo2",
                    status="planned",
                    is_active=True,
                    planned_duration_min=60,
                    intensity_target="105-110% FTP",
                    structured_workout={"format": "bike"},
                    source="test",
                ),
            ]
        )
        await session.commit()

        packet = await MorningAnalysisService(session).assemble_context_packet(player, subject_date)

    verdict = packet["verdict"]
    assert verdict["status"] in {"Amber", "Red"}
    assert "swapSuggestion" not in verdict  # no sound later slot to swap into
    shortfall = verdict["weeklyMix"]["shortfall"]
    assert shortfall["bucket"] == "vo2"
    assert shortfall["repatched"] is False
    assert any("no vo2 session this week" in item.lower() for item in verdict["planAdjustments"])


def test_red_verdict_never_keeps_vo2() -> None:
    daily_metric = DailyMetric(
        user_id=uuid.uuid4(),
        calendar_date=date(2026, 1, 2),
        hrv_weekly_avg_ms=38,
        hrv_baseline_low_ms=43,
        hrv_status="Unbalanced",
        raw_payload={},
    )
    sleep = Sleep(
        user_id=daily_metric.user_id,
        calendar_date=date(2026, 1, 2),
        score=54,
        raw_payload={},
        factors_json={},
    )
    workout = PlannedWorkout(
        user_id=daily_metric.user_id,
        workout_date=date(2026, 1, 2),
        version=1,
        title="VO2 Max",
        workout_type="bike_vo2",
        structured_workout={},
    )

    verdict = _morning_verdict(
        daily_metric=daily_metric,
        sleep=sleep,
        age_adjusted_sleep_score=58,
        manual_entries=[],
        planned_workouts=[workout],
    )

    assert verdict["status"] == "Red"
    assert "red_never_vo2" in verdict["safetyRulesApplied"]
    assert any("Replace VO2" in item for item in verdict["planAdjustments"])


def test_cheery_checkin_never_upgrades_a_red() -> None:
    """Batch 85: subjective is downgrade-only — a top check-in score never lifts a
    Red (poor overnight sleep/recovery) to Green when the brief regenerates on his
    check-in. The Red floor owns the verdict; the subjective read cannot override it."""
    user_id = uuid.uuid4()
    daily_metric = DailyMetric(
        user_id=user_id,
        calendar_date=date(2026, 7, 11),
        hrv_weekly_avg_ms=38,
        hrv_baseline_low_ms=43,
        hrv_status="Unbalanced",
        raw_payload={},
    )
    sleep = Sleep(
        user_id=user_id,
        calendar_date=date(2026, 7, 11),
        score=54,
        raw_payload={},
        factors_json={},
    )
    cheery = ManualEntry(
        user_id=user_id,
        entry_date=date(2026, 7, 11),
        subjective_score=10,
        feel="great, full of energy!",
    )

    verdict = _morning_verdict(
        daily_metric=daily_metric,
        sleep=sleep,
        age_adjusted_sleep_score=58,  # < 60 → the Red floor
        manual_entries=[cheery],
        planned_workouts=[],
    )

    assert verdict["status"] == "Red"


def test_prompt_answers_a_question_in_checkin_notes() -> None:
    """Batch 85: the read answers a question Mark leaves in his check-in notes,
    grounded in the packet. The instruction lives in the (version-bumped) system
    prompt, and his note text reaches the user prompt."""
    assert PROMPT_VERSION.startswith("morning-analysis-v27")
    assert "Your question" in SYSTEM_PROMPT
    assert "answer it" in SYSTEM_PROMPT.lower()
    assert "restDay.isRestDay" in SYSTEM_PROMPT
    assert "status is\nskipped" in SYSTEM_PROMPT

    packet = {
        "manualEntries": [
            {"notes": "Why am I so tired even though I slept 8 hours?", "subjectiveScore": 4}
        ],
        "verdict": {"status": "Amber"},
    }
    prompt = build_morning_user_prompt(packet)
    assert "Why am I so tired" in prompt


def test_prompt_grounds_week_history_in_execution_not_nominal_schedule() -> None:
    assert "usual routine only" in SYSTEM_PROMPT
    assert "trainingWeekSoFar" in SYSTEM_PROMPT
    assert "executed Garmin activities are the only completion truth" in SYSTEM_PROMPT
    assert "credit a moved-away" in SYSTEM_PROMPT
    assert "Respect the trainingSchedule rest days" not in SYSTEM_PROMPT


def test_prompt_treats_the_training_load_cap_as_deterministic() -> None:
    assert ">=1.5 triggers the deterministic high-load cap" in SYSTEM_PROMPT
    assert "verdict.trainingLoadCap already records and" in SYSTEM_PROMPT
    assert "model-controlled override" in SYSTEM_PROMPT


def test_prompt_keeps_batch_170_verdict_rules_deterministic() -> None:
    assert "verdict.sleepCreditCeiling" in SYSTEM_PROMPT
    assert "verdict.cumulativeEscalation" in SYSTEM_PROMPT
    assert "Missing HRV and absent" in SYSTEM_PROMPT
    assert "never describe absent data as proof" in SYSTEM_PROMPT


def test_prompt_treats_readiness_baseline_decline_as_warning_only() -> None:
    assert "readinessBaselineTrend is a deterministic warning-only alarm" in SYSTEM_PROMPT
    assert "It does not set the colour itself" in SYSTEM_PROMPT
    assert "readinessEffectiveFloor" in SYSTEM_PROMPT


def test_sleep_packet_localizes_bed_wake_across_dst_and_keeps_utc() -> None:
    """Batch 91: bed/wake are stored naive-UTC; the packet must add the user's
    local wall-clock time beside the *Utc fields. A BST night gains +1h (00:17Z →
    01:17) while a GMT night is unchanged (07:31Z → 07:31)."""
    bst = _sleep_packet(
        Sleep(
            calendar_date=date(2026, 7, 12),
            sleep_start_utc=datetime(2026, 7, 12, 0, 17),
            sleep_end_utc=datetime(2026, 7, 12, 7, 32),
        ),
        None,
        "Europe/London",
    )
    assert bst is not None
    assert bst["sleepStartUtc"] == "2026-07-12T00:17:00Z"
    assert bst["sleepEndUtc"] == "2026-07-12T07:32:00Z"
    assert bst["sleepStartLocal"] == "01:17"
    assert bst["sleepEndLocal"] == "08:32"

    gmt = _sleep_packet(
        Sleep(
            calendar_date=date(2026, 1, 15),
            sleep_start_utc=datetime(2026, 1, 15, 0, 17),
            sleep_end_utc=datetime(2026, 1, 15, 7, 31),
        ),
        None,
        "Europe/London",
    )
    assert gmt is not None
    assert gmt["sleepStartLocal"] == "00:17"
    assert gmt["sleepEndLocal"] == "07:31"


def test_sleep_packet_local_clock_tolerates_missing_times_and_bad_zone() -> None:
    """Missing bed/wake stay None; an unknown timezone falls back to UTC rather than
    raising, so a stray profile timezone never breaks the morning read."""
    partial = _sleep_packet(
        Sleep(calendar_date=date(2026, 7, 12), sleep_start_utc=datetime(2026, 7, 12, 0, 17)),
        None,
        "Not/AZone",
    )
    assert partial is not None
    assert partial["sleepStartLocal"] == "00:17"  # UTC fallback
    assert partial["sleepEndLocal"] is None
    # Batch 142: no wake time and no component totals -> in-bed and asleep stay None
    # rather than collapsing to a misleading 0.
    assert partial["timeInBedMin"] is None
    assert partial["timeAsleepMin"] is None


def test_sleep_packet_labels_time_in_bed_and_asleep_separately() -> None:
    """Batch 142 regression (his 2026-07-19 night): durationMin is Garmin
    sleepTimeSeconds — time *asleep*, already excluding awake — so the packet must
    also carry timeInBedMin (the bed->wake window) and an explicitly-named
    timeAsleepMin. Bed 00:37 -> wake 08:05 is 7h28 in bed (448 min); 6h26 asleep
    (386 min) with a 62-min awake window sits inside it. Surfacing both, labelled,
    is what stops the read re-subtracting awake to invent a "5h5 actual sleep"."""
    packet = _sleep_packet(
        Sleep(
            calendar_date=date(2026, 7, 19),
            sleep_start_utc=datetime(2026, 7, 19, 0, 37),
            sleep_end_utc=datetime(2026, 7, 19, 8, 5),
            duration_sec=6 * 3600 + 26 * 60,  # 6h26 asleep (sleepTimeSeconds)
            awake_sleep_sec=62 * 60,
        ),
        None,
        "Europe/London",
    )
    assert packet is not None
    assert packet["timeInBedMin"] == 448  # 7h28 bed->wake window
    assert packet["timeAsleepMin"] == 386  # 6h26 asleep
    assert packet["durationMin"] == 386  # unchanged: still the asleep figure
    assert packet["awakeSleepMin"] == 62
    # in bed = asleep + awake (+ any unmeasurable); never asleep - awake
    assert packet["timeInBedMin"] == packet["timeAsleepMin"] + packet["awakeSleepMin"]


def test_sleep_packet_time_in_bed_falls_back_to_component_sum_without_window() -> None:
    """Batch 142: when a bed/wake timestamp is missing the in-bed total falls back
    to asleep + awake + brief unmeasurable, so the model still gets a labelled
    figure while time asleep is unaffected."""
    packet = _sleep_packet(
        Sleep(
            calendar_date=date(2026, 7, 19),
            sleep_start_utc=datetime(2026, 7, 19, 0, 37),
            sleep_end_utc=None,  # watch dropped the wake timestamp
            duration_sec=6 * 3600 + 26 * 60,  # 386 min asleep
            awake_sleep_sec=62 * 60,  # 62 min awake
            unmeasurable_sleep_sec=6 * 60,  # 6 min unmeasurable
        ),
        None,
        "Europe/London",
    )
    assert packet is not None
    assert packet["timeInBedMin"] == 454  # 386 + 62 + 6, summed
    assert packet["timeAsleepMin"] == 386


def test_date_label_is_authoritative_and_portable() -> None:
    """Batch 91: a ready-to-print header date (no platform-specific %-d) so the read
    never re-derives '13 July' for the 12th."""
    assert _date_label(date(2026, 7, 12)) == "Sunday 12 July 2026"
    assert _date_label(date(2026, 1, 1)) == "Thursday 1 January 2026"


def test_subjective_score_label_speaks_marks_checkin_word() -> None:
    """Batch 91: map the one-tap score to the word Mark tapped (CheckInPage
    OVERALL_OPTIONS); off-scale legacy values fall to the nearest band; None stays
    None so an absent check-in is simply not referenced."""
    assert subjective_score_label(2) == "Rough"
    assert subjective_score_label(4) == "Meh"
    assert subjective_score_label(6) == "OK"
    assert subjective_score_label(8) == "Good"
    assert subjective_score_label(10) == "Great"
    assert subjective_score_label(5) == "Meh"  # off-scale → nearest band
    assert subjective_score_label(7) == "OK"
    assert subjective_score_label(0) == "Rough"
    assert subjective_score_label(None) is None


def test_manual_entry_packet_carries_both_score_and_word() -> None:
    """Batch 91: the raw score stays for the deterministic verdict, and the word is
    added so the read speaks 'you felt OK', never 'subjective feel 6'."""
    packet = _manual_entry_packet(
        ManualEntry(
            entry_date=date(2026, 7, 12),
            entry_at_utc=datetime(2026, 7, 12, 6, 15),
            subjective_score=6,
        )
    )
    assert packet["subjectiveScore"] == 6
    assert packet["subjectiveLabel"] == "OK"


def test_system_prompt_bans_utc_and_raw_score_and_uses_local_fields() -> None:
    """Batch 91 regression: the read is instructed to use local clock times and the
    check-in word, and never to print a *Utc timestamp or the raw subjectiveScore
    number — the testable guard that no such term leaks into a rendered read."""
    assert "sleepStartLocal" in SYSTEM_PROMPT
    assert "subjectDateLabel" in SYSTEM_PROMPT
    assert "subjectiveLabel" in SYSTEM_PROMPT
    assert "precool_credited" in SYSTEM_PROMPT
    # normalize wrapped whitespace so the assertions are line-break agnostic
    normalized = " ".join(SYSTEM_PROMPT.lower().split())
    assert "never print a `*utc` timestamp" in normalized
    assert "never surface the raw subjectivescore number" in normalized


def test_system_prompt_states_time_in_bed_and_asleep_without_re_subtracting_awake() -> None:
    """Batch 142: the read must state time-in-bed from timeInBedMin and time-asleep
    from timeAsleepMin, and never subtract awake from the asleep total — the
    testable guard against the 2026-07-19 "5h5 actual sleep" mislabelling."""
    assert "timeInBedMin" in SYSTEM_PROMPT
    assert "timeAsleepMin" in SYSTEM_PROMPT
    normalized = " ".join(SYSTEM_PROMPT.lower().split())
    assert "time in bed from sleep.timeinbedmin" in normalized
    assert "time asleep from sleep.timeasleepmin" in normalized
    assert "never subtract awake time from it" in normalized


def _temperature(at: datetime, value: float) -> TemperatureReading:
    return TemperatureReading(
        user_id=uuid.uuid4(),
        source="hive",
        product_id="thermostat",
        captured_at_utc=at,
        temperature_c=value,
        raw_payload={},
    )


def test_thermal_review_uses_sleep_peak_and_credits_precool() -> None:
    sleep = Sleep(
        user_id=uuid.uuid4(),
        calendar_date=date(2026, 7, 12),
        sleep_start_utc=datetime(2026, 7, 12, 0, 17),
        sleep_end_utc=datetime(2026, 7, 12, 7, 31),
        raw_payload={},
        factors_json={},
    )
    rows = [
        _temperature(datetime(2026, 7, 11, 20, 30), 24.05),
        _temperature(datetime(2026, 7, 11, 23, 45), 18.64),
        _temperature(datetime(2026, 7, 12, 0, 15), 18.8),
        _temperature(datetime(2026, 7, 12, 1, 0), 19.2),
        _temperature(datetime(2026, 7, 12, 4, 0), 20.2),
        _temperature(datetime(2026, 7, 12, 7, 15), 19.7),
    ]

    review = _thermal_review(rows, None, {}, sleep=sleep)

    assert review["windowSource"] == "sleep"
    assert review["sampleCount"] == 3
    assert review["indoorPeakC"] == 20.2
    assert review["indoorLowC"] == 19.2
    assert review["preCoolLowC"] == 18.64
    assert review["sleepOnsetC"] == 18.8
    assert review["preCoolDropC"] == pytest.approx(5.41)
    assert "precool_credited" in review["flags"]
    assert "precool_target_missed" not in review["flags"]


def test_thermal_review_falls_back_to_shared_night_window_without_sleep() -> None:
    rows = [
        _temperature(datetime(2026, 7, 11, 20, 30), 19.0),
        _temperature(datetime(2026, 7, 12, 3, 0), 20.1),
    ]

    review = _thermal_review(rows, None, {}, sleep=None)

    assert review["windowSource"] == "night_fallback"
    assert review["sampleCount"] == 2
    assert review["indoorPeakC"] == 20.1
    assert review["preCoolLowC"] is None
    assert "precool_target_missed" not in review["flags"]


def _rhr_baseline(user_id: uuid.UUID) -> MetricBaseline:
    return MetricBaseline(
        user_id=user_id,
        metric_key="resting_heart_rate_bpm",
        metric_label="Resting heart rate",
        source="test",
        window_start_date=date(2026, 4, 1),
        window_end_date=date(2026, 6, 30),
        sample_count=84,
        excluded_sample_count=0,
        mean_value=44,
        median_value=44,
        lower_quartile_value=43,
        upper_quartile_value=45,
        raw_payload={},
    )


def _readiness_baseline(user_id: uuid.UUID, *, median: float = 53.5) -> MetricBaseline:
    return MetricBaseline(
        user_id=user_id,
        metric_key="readiness_score",
        metric_label="Training readiness",
        source="test",
        window_start_date=date(2026, 4, 13),
        window_end_date=date(2026, 7, 5),
        sample_count=84,
        excluded_sample_count=0,
        mean_value=45,
        median_value=median,
        lower_quartile_value=26,
        upper_quartile_value=65,
        raw_payload={},
    )


def _positive_morning_checkin(
    user_id: uuid.UUID,
    *,
    score: int = 6,
) -> ManualEntry:
    return ManualEntry(
        user_id=user_id,
        entry_date=date(2026, 7, 29),
        entry_at_utc=datetime(2026, 7, 29, 7, 0),
        subjective_score=score,
    )


def test_soft_sleep_can_stay_green_when_personal_recovery_signals_are_strong() -> None:
    user_id = uuid.uuid4()
    daily_metric = DailyMetric(
        user_id=user_id,
        calendar_date=date(2026, 7, 5),
        readiness_score=76,
        readiness_level="Moderate",
        hrv_weekly_avg_ms=48,
        hrv_baseline_low_ms=43,
        hrv_status="Balanced",
        resting_heart_rate_bpm=44,
        raw_payload={},
    )

    verdict = _morning_verdict(
        daily_metric=daily_metric,
        sleep=None,
        age_adjusted_sleep_score=72,
        manual_entries=[_positive_morning_checkin(user_id)],
        planned_workouts=[],
        baselines={"resting_heart_rate_bpm": _rhr_baseline(user_id)},
    )

    assert verdict["status"] == "Green"
    assert verdict["softSleepRecoveryOverride"] is True
    assert verdict["restingHeartRateWithinBaseline"] is True


def test_soft_sleep_override_does_not_cross_red_floor() -> None:
    user_id = uuid.uuid4()
    daily_metric = DailyMetric(
        user_id=user_id,
        calendar_date=date(2026, 7, 5),
        readiness_score=76,
        readiness_level="Moderate",
        hrv_weekly_avg_ms=48,
        hrv_baseline_low_ms=43,
        hrv_status="Balanced",
        resting_heart_rate_bpm=44,
        raw_payload={},
    )

    verdict = _morning_verdict(
        daily_metric=daily_metric,
        sleep=None,
        age_adjusted_sleep_score=57,
        manual_entries=[_positive_morning_checkin(user_id)],
        planned_workouts=[],
        baselines={"resting_heart_rate_bpm": _rhr_baseline(user_id)},
    )

    assert verdict["status"] == "Red"
    assert verdict["softSleepRecoveryOverride"] is False


def test_soft_sleep_override_requires_resting_hr_inside_personal_band() -> None:
    user_id = uuid.uuid4()
    daily_metric = DailyMetric(
        user_id=user_id,
        calendar_date=date(2026, 7, 5),
        readiness_score=76,
        readiness_level="Moderate",
        hrv_weekly_avg_ms=48,
        hrv_baseline_low_ms=43,
        hrv_status="Balanced",
        resting_heart_rate_bpm=48,
        raw_payload={},
    )

    verdict = _morning_verdict(
        daily_metric=daily_metric,
        sleep=None,
        age_adjusted_sleep_score=72,
        manual_entries=[_positive_morning_checkin(user_id)],
        planned_workouts=[],
        baselines={"resting_heart_rate_bpm": _rhr_baseline(user_id)},
    )

    assert verdict["status"] == "Amber"
    assert verdict["softSleepRecoveryOverride"] is False


def test_soft_sleep_override_preserves_healthy_personal_baseline_behaviour() -> None:
    # Mark's real 2026-07-05: soft sleep (72) + Moderate readiness 66 (below the old
    # generic >=70 gate) but above the anchored floor (60), with clean HRV and
    # resting HR in band -> stays Green under the #133 personal-floor rule.
    user_id = uuid.uuid4()
    daily_metric = DailyMetric(
        user_id=user_id,
        calendar_date=date(2026, 7, 5),
        readiness_score=66,
        readiness_level="Moderate",
        hrv_weekly_avg_ms=48,
        hrv_baseline_low_ms=43,
        hrv_status="Balanced",
        resting_heart_rate_bpm=43,
        raw_payload={},
    )

    verdict = _morning_verdict(
        daily_metric=daily_metric,
        sleep=None,
        age_adjusted_sleep_score=72,
        manual_entries=[_positive_morning_checkin(user_id)],
        planned_workouts=[],
        baselines={
            "resting_heart_rate_bpm": _rhr_baseline(user_id),
            "readiness_score": _readiness_baseline(user_id),
        },
    )

    assert verdict["status"] == "Green"
    assert verdict["softSleepRecoveryOverride"] is True
    assert verdict["readinessBaselineCenter"] == 53.5
    assert verdict["readinessAbsoluteFloor"] == SOFT_SLEEP_READINESS_ABSOLUTE_FLOOR
    assert verdict["readinessEffectiveFloor"] == SOFT_SLEEP_READINESS_ABSOLUTE_FLOOR


def test_soft_sleep_override_cannot_follow_a_drifted_baseline_below_absolute_floor() -> None:
    """Audit Probe 4: readiness 52 stays Amber even after its median sinks to 50."""
    user_id = uuid.uuid4()
    daily_metric = DailyMetric(
        user_id=user_id,
        calendar_date=date(2026, 7, 5),
        readiness_score=52,
        readiness_level="Moderate",
        hrv_weekly_avg_ms=48,
        hrv_baseline_low_ms=43,
        hrv_status="Balanced",
        resting_heart_rate_bpm=43,
        raw_payload={},
    )

    verdict = _morning_verdict(
        daily_metric=daily_metric,
        sleep=None,
        age_adjusted_sleep_score=72,
        manual_entries=[_positive_morning_checkin(user_id)],
        planned_workouts=[],
        baselines={
            "resting_heart_rate_bpm": _rhr_baseline(user_id),
            "readiness_score": _readiness_baseline(user_id, median=50),
        },
    )

    assert verdict["status"] == "Amber"
    assert verdict["softSleepRecoveryOverride"] is False
    assert verdict["readinessBaselineCenter"] == 50
    assert verdict["readinessEffectiveFloor"] == SOFT_SLEEP_READINESS_ABSOLUTE_FLOOR


def _batch_170_metric(
    user_id: uuid.UUID,
    *,
    readiness_level: str = "Moderate",
    readiness_score: int | None = 76,
    hrv_weekly_avg_ms: int | None = 48,
    resting_heart_rate_bpm: int | None = 44,
) -> DailyMetric:
    return DailyMetric(
        user_id=user_id,
        calendar_date=date(2026, 7, 29),
        readiness_score=readiness_score,
        readiness_level=readiness_level,
        hrv_weekly_avg_ms=hrv_weekly_avg_ms,
        hrv_baseline_low_ms=43,
        hrv_status="Balanced",
        resting_heart_rate_bpm=resting_heart_rate_bpm,
        raw_payload={},
    )


def _batch_170_sleep(user_id: uuid.UUID, *, score: int) -> Sleep:
    return Sleep(
        user_id=user_id,
        calendar_date=date(2026, 7, 29),
        score=score,
        raw_payload={},
        factors_json={},
    )


def _batch_170_audit_case(case: str) -> dict[str, Any]:
    user_id = uuid.uuid4()
    daily_metric = _batch_170_metric(user_id)
    sleep: Sleep | None = None
    adjusted_score = 72
    manual_entries = [_positive_morning_checkin(user_id)]
    baselines: dict[str, MetricBaseline] = {
        "resting_heart_rate_bpm": _rhr_baseline(user_id),
        "readiness_score": _readiness_baseline(user_id),
    }
    yesterday_load: dict[str, str] | None = None
    training_load: dict[str, int] | None = None

    if case == "credited_green_without_corroboration":
        daily_metric = None
        sleep = _batch_170_sleep(user_id, score=62)
        adjusted_score = 74
        baselines = {}
    elif case == "poor_readiness_stack":
        daily_metric = _batch_170_metric(
            user_id,
            readiness_level="Poor",
            readiness_score=16,
        )
        adjusted_score = 62
        manual_entries = [_positive_morning_checkin(user_id, score=3)]
        yesterday_load = {"status": "hard"}
        training_load = {"recoveryTimeMin": 1400}
    elif case == "missing_hrv":
        daily_metric = _batch_170_metric(user_id, hrv_weekly_avg_ms=None)
    elif case == "missing_subjective":
        manual_entries = []
    elif case == "acute_red":
        adjusted_score = 58
    elif case == "clean_soft_sleep":
        pass
    else:  # pragma: no cover - protects the test fixture itself
        raise AssertionError(f"Unknown Batch 170 audit case: {case}")

    return _morning_verdict(
        daily_metric=daily_metric,
        sleep=sleep,
        age_adjusted_sleep_score=adjusted_score,
        manual_entries=manual_entries,
        planned_workouts=[],
        baselines=baselines,
        yesterday_load=yesterday_load,
        training_load=training_load,
    )


@pytest.mark.parametrize(
    ("case", "pre_batch_status", "expected_status"),
    [
        ("credited_green_without_corroboration", "Green", "Amber"),
        ("poor_readiness_stack", "Amber", "Red"),
        ("missing_hrv", "Green", "Amber"),
        ("missing_subjective", "Green", "Amber"),
        ("acute_red", "Red", "Red"),
        ("clean_soft_sleep", "Green", "Green"),
    ],
)
def test_batch_170_audit_matrix_only_hardens_the_light(
    case: str,
    pre_batch_status: str,
    expected_status: str,
) -> None:
    verdict = _batch_170_audit_case(case)
    caution_rank = {"Green": 0, "Amber": 1, "Red": 2}

    assert verdict["status"] == expected_status
    assert caution_rank[verdict["status"]] >= caution_rank[pre_batch_status]


def test_sleep_credit_crossing_requires_complete_exception_evidence() -> None:
    user_id = uuid.uuid4()
    sleep = _batch_170_sleep(user_id, score=62)
    no_corroboration = _morning_verdict(
        daily_metric=None,
        sleep=sleep,
        age_adjusted_sleep_score=74,
        manual_entries=[_positive_morning_checkin(user_id)],
        planned_workouts=[],
    )
    corroborated = _morning_verdict(
        daily_metric=_batch_170_metric(user_id),
        sleep=sleep,
        age_adjusted_sleep_score=74,
        manual_entries=[_positive_morning_checkin(user_id)],
        planned_workouts=[],
        baselines={
            "resting_heart_rate_bpm": _rhr_baseline(user_id),
            "readiness_score": _readiness_baseline(user_id),
        },
    )

    assert no_corroboration["status"] == "Amber"
    assert no_corroboration["sleepCreditCeiling"] == {
        "rawSleepScore": 62,
        "ageAdjustedSleepScore": 74,
        "crossedGreenThreshold": True,
        "corroboratedByObjectiveRecovery": False,
        "positiveSubjectiveEvidence": True,
        "exceptionEvidenceComplete": False,
        "allowedGreen": False,
        "applied": True,
        "reason": (
            "Age-adjusted sleep reaches the Green line, but the raw Garmin sleep score "
            "is below 74 without complete measured recovery and check-in evidence."
        ),
    }
    assert "sleep_credit_green_ceiling" in no_corroboration["safetyRulesApplied"]
    assert corroborated["status"] == "Green"
    assert corroborated["sleepCreditCeiling"]["exceptionEvidenceComplete"] is True
    assert corroborated["sleepCreditCeiling"]["applied"] is False


def test_sleep_credit_can_still_lift_within_the_amber_band() -> None:
    user_id = uuid.uuid4()
    verdict = _morning_verdict(
        daily_metric=None,
        sleep=_batch_170_sleep(user_id, score=53),
        age_adjusted_sleep_score=65,
        manual_entries=[],
        planned_workouts=[],
    )

    assert verdict["status"] == "Amber"
    assert verdict["sleepCreditCeiling"]["crossedGreenThreshold"] is False
    assert verdict["sleepCreditCeiling"]["applied"] is False


@pytest.mark.parametrize(
    ("missing_signal", "expected_field"),
    [
        ("hrv", "positiveHrvEvidence"),
        ("readiness", None),
        ("subjective", "positiveSubjectiveEvidence"),
    ],
)
def test_missing_recovery_evidence_cannot_unlock_soft_sleep_green(
    missing_signal: str,
    expected_field: str | None,
) -> None:
    user_id = uuid.uuid4()
    daily_metric = _batch_170_metric(
        user_id,
        hrv_weekly_avg_ms=None if missing_signal == "hrv" else 48,
        readiness_score=None if missing_signal == "readiness" else 76,
    )
    verdict = _morning_verdict(
        daily_metric=daily_metric,
        sleep=None,
        age_adjusted_sleep_score=72,
        manual_entries=(
            [] if missing_signal == "subjective" else [_positive_morning_checkin(user_id)]
        ),
        planned_workouts=[],
        baselines={
            "resting_heart_rate_bpm": _rhr_baseline(user_id),
            "readiness_score": _readiness_baseline(user_id),
        },
    )

    assert verdict["status"] == "Amber"
    assert verdict["softSleepRecoveryOverride"] is False
    if expected_field is not None:
        assert verdict[expected_field] is False


def test_missing_hrv_and_checkin_stay_neutral_on_a_raw_green_night() -> None:
    user_id = uuid.uuid4()
    verdict = _morning_verdict(
        daily_metric=None,
        sleep=_batch_170_sleep(user_id, score=80),
        age_adjusted_sleep_score=80,
        manual_entries=[],
        planned_workouts=[],
    )

    assert verdict["status"] == "Green"
    assert verdict["positiveHrvEvidence"] is False
    assert verdict["positiveSubjectiveEvidence"] is False
    assert verdict["reasons"] == [
        (
            "Sleep clears the green rule; missing HRV/check-in data is neutral "
            "and did not provide positive evidence."
        )
    ]


@pytest.mark.parametrize(
    ("second_negative", "expected_signal"),
    [
        ("soft_sleep", "soft_sleep"),
        ("low_subjective", "low_subjective"),
        ("hard_yesterday", "hard_yesterday"),
        ("elevated_rhr", "elevated_resting_heart_rate"),
    ],
)
def test_poor_readiness_plus_each_second_negative_escalates_to_red(
    second_negative: str,
    expected_signal: str,
) -> None:
    user_id = uuid.uuid4()
    daily_metric = _batch_170_metric(
        user_id,
        readiness_level="Poor",
        readiness_score=16,
        resting_heart_rate_bpm=48 if second_negative == "elevated_rhr" else 44,
    )
    verdict = _morning_verdict(
        daily_metric=daily_metric,
        sleep=None,
        age_adjusted_sleep_score=72 if second_negative == "soft_sleep" else 80,
        manual_entries=[
            _positive_morning_checkin(
                user_id,
                score=3 if second_negative == "low_subjective" else 6,
            )
        ],
        planned_workouts=[],
        baselines={"resting_heart_rate_bpm": _rhr_baseline(user_id)},
        yesterday_load={"status": "hard"} if second_negative == "hard_yesterday" else None,
    )

    assert verdict["status"] == "Red"
    assert verdict["cumulativeEscalation"]["triggered"] is True
    assert verdict["cumulativeEscalation"]["applied"] is True
    assert expected_signal in verdict["cumulativeEscalation"]["negativeSignals"]
    assert "poor_readiness_cumulative_red" in verdict["safetyRulesApplied"]


def test_poor_readiness_does_not_treat_missing_rhr_baseline_as_elevated() -> None:
    user_id = uuid.uuid4()
    verdict = _morning_verdict(
        daily_metric=_batch_170_metric(
            user_id,
            readiness_level="Poor",
            readiness_score=16,
            resting_heart_rate_bpm=48,
        ),
        sleep=None,
        age_adjusted_sleep_score=80,
        manual_entries=[_positive_morning_checkin(user_id)],
        planned_workouts=[],
        baselines={},
    )

    assert verdict["status"] == "Amber"
    assert verdict["restingHeartRateElevated"] is False
    assert verdict["cumulativeEscalation"]["negativeSignals"] == []


def test_readiness_baseline_trend_alarms_on_sustained_84_day_decline() -> None:
    as_of = date(2026, 7, 29)
    window_start = as_of - timedelta(days=BASELINE_TREND_WINDOW_DAYS - 1)
    observations = [
        (window_start + timedelta(days=offset), 68 if offset < 42 else 58)
        for offset in range(BASELINE_TREND_WINDOW_DAYS)
    ]

    trend = readiness_baseline_trend(observations, as_of=as_of)

    assert trend["status"] == "declining"
    assert trend["triggered"] is True
    assert trend["verdictImpact"] == "warning_only"
    assert trend["firstHalfMedian"] == 68
    assert trend["secondHalfMedian"] == 58
    assert trend["delta"] == -10
    assert trend["firstHalfSampleCount"] == 42
    assert trend["secondHalfSampleCount"] == 42
    assert trend["minimumSamplesPerHalf"] == READINESS_TREND_MIN_SAMPLES_PER_HALF
    assert trend["declineThresholdPoints"] == READINESS_TREND_DECLINE_POINTS
    assert "Readiness baseline trend warning" in trend["reason"]


def test_readiness_baseline_trend_ignores_noise_and_requires_coverage() -> None:
    as_of = date(2026, 7, 29)
    window_start = as_of - timedelta(days=BASELINE_TREND_WINDOW_DAYS - 1)
    stable = [
        (window_start + timedelta(days=offset), 68 if offset < 42 else 64)
        for offset in range(BASELINE_TREND_WINDOW_DAYS)
    ]
    sparse = stable[:20] + stable[42:62]

    stable_trend = readiness_baseline_trend(stable, as_of=as_of)
    sparse_trend = readiness_baseline_trend(sparse, as_of=as_of)

    assert stable_trend["status"] == "stable"
    assert stable_trend["delta"] == -4
    assert stable_trend["triggered"] is False
    assert stable_trend["reason"] is None
    assert sparse_trend["status"] == "insufficient_data"
    assert sparse_trend["firstHalfMedian"] is None
    assert sparse_trend["secondHalfMedian"] is None


@pytest.mark.parametrize(
    ("age_adjusted_sleep_score", "readiness_level", "expected_status"),
    [
        (58, "High", "Red"),
        (80, "Poor", "Amber"),
        (80, "High", "Green"),
    ],
)
def test_readiness_baseline_alarm_never_softens_the_verdict(
    age_adjusted_sleep_score: int,
    readiness_level: str,
    expected_status: str,
) -> None:
    daily_metric = DailyMetric(
        user_id=uuid.uuid4(),
        calendar_date=date(2026, 7, 29),
        readiness_score=75,
        readiness_level=readiness_level,
        hrv_weekly_avg_ms=50,
        hrv_baseline_low_ms=43,
        hrv_status="Balanced",
        raw_payload={},
    )
    kwargs = {
        "daily_metric": daily_metric,
        "sleep": None,
        "age_adjusted_sleep_score": age_adjusted_sleep_score,
        "manual_entries": [],
        "planned_workouts": [],
    }
    warning = {
        "metricKey": "readiness_score",
        "status": "declining",
        "triggered": True,
        "verdictImpact": "warning_only",
        "reason": "Readiness baseline trend warning: sustained decline.",
    }

    without_warning = _morning_verdict(**kwargs)
    with_warning = _morning_verdict(**kwargs, readiness_baseline_trend=warning)

    assert without_warning["status"] == expected_status
    assert with_warning["status"] == expected_status
    assert with_warning["readinessBaselineTrend"] == warning
    assert warning["reason"] in with_warning["reasons"]


def test_soft_sleep_override_rejects_readiness_below_personal_median() -> None:
    # Moderate readiness that is below Mark's own typical (median 60) -> no override,
    # so the soft-sleep night stays Amber.
    user_id = uuid.uuid4()
    daily_metric = DailyMetric(
        user_id=user_id,
        calendar_date=date(2026, 7, 5),
        readiness_score=52,
        readiness_level="Moderate",
        hrv_weekly_avg_ms=48,
        hrv_baseline_low_ms=43,
        hrv_status="Balanced",
        resting_heart_rate_bpm=43,
        raw_payload={},
    )

    verdict = _morning_verdict(
        daily_metric=daily_metric,
        sleep=None,
        age_adjusted_sleep_score=72,
        manual_entries=[_positive_morning_checkin(user_id)],
        planned_workouts=[],
        baselines={
            "resting_heart_rate_bpm": _rhr_baseline(user_id),
            "readiness_score": _readiness_baseline(user_id, median=60),
        },
    )

    assert verdict["status"] == "Amber"
    assert verdict["softSleepRecoveryOverride"] is False


def test_low_readiness_is_not_load_driven_without_recovery_evidence() -> None:
    daily_metric = DailyMetric(
        user_id=uuid.uuid4(),
        calendar_date=date(2026, 1, 3),
        readiness_level="Low",
        hrv_weekly_avg_ms=50,
        hrv_baseline_low_ms=43,
        hrv_status="Balanced",
        raw_payload={},
    )

    verdict = _morning_verdict(
        daily_metric=daily_metric,
        sleep=None,
        age_adjusted_sleep_score=76,
        manual_entries=[],
        planned_workouts=[],
    )

    assert verdict["status"] == "Amber"
    assert verdict["readinessInterpretation"] is None


def test_poor_readiness_is_not_rescued_by_age_adjusted_sleep_score() -> None:
    daily_metric = DailyMetric(
        user_id=uuid.uuid4(),
        calendar_date=date(2026, 6, 1),
        readiness_score=16,
        readiness_level="Poor",
        hrv_weekly_avg_ms=50,
        hrv_baseline_low_ms=43,
        hrv_status="Balanced",
        raw_payload={},
    )

    verdict = _morning_verdict(
        daily_metric=daily_metric,
        sleep=None,
        age_adjusted_sleep_score=78,
        manual_entries=[],
        planned_workouts=[],
    )

    assert verdict["status"] == "Amber"
    assert verdict["readinessInterpretation"] is None


def _daily_aggregate_raw(calendar_date: date, end_local: str) -> dict[str, object]:
    start_local = f"{calendar_date.isoformat()}T00:00:00.0"
    return {
        "stress": {
            "avgStressLevel": 61,
            "startTimestampLocal": start_local,
            "endTimestampLocal": end_local,
        },
        "body_battery": {
            "drained": 78,
            "bodyBatteryValuesArray": [[0, 9]],
            "startTimestampLocal": start_local,
            "endTimestampLocal": end_local,
        },
    }


def test_yesterday_load_packet_carries_hard_session_and_analysis_summary() -> None:
    user_id = uuid.uuid4()
    activity_id = uuid.uuid4()
    activity = Activity(
        id=activity_id,
        user_id=user_id,
        garmin_activity_id=123,
        activity_name="VO2 Max 30/15",
        activity_type="indoor_cycling",
        start_utc=datetime(2026, 7, 4, 9, 0),
        duration_sec=3600,
        training_load=165,
        aerobic_training_effect=3.7,
        anaerobic_training_effect=2.2,
        intensity_factor=0.9,
        raw_summary={},
    )
    analysis = Analysis(
        user_id=user_id,
        activity_id=activity_id,
        analysis_type="post_workout",
        subject_date=date(2026, 7, 4),
        generated_at_utc=datetime(2026, 7, 4, 12, 0),
        prompt_version="test",
        output_markdown="**Recovery:** This was a hard session and it left fatigue.",
        raw_response={},
    )

    packet = _yesterday_load_packet([activity], [analysis])

    assert packet["status"] == "hard"
    assert packet["statusScope"] == "exercise_only"
    assert packet["totalTrainingLoad"] == 165
    assert packet["hardestActivity"]["name"] == "VO2 Max 30/15"
    assert packet["postSessionAnalyses"][0]["analysisType"] == "post_workout"
    assert "hard session" in packet["postSessionAnalyses"][0]["summary"]
    assert packet["wholeDayCost"] == {
        "calendarDate": None,
        "allDayStressAvg": None,
        "bodyBatteryDrained": None,
        "bodyBatteryEnd": None,
        "coverage": {
            "status": "unknown",
            "stressStatus": "unknown",
            "bodyBatteryStatus": "unknown",
            "asOfLocal": None,
        },
        "classificationImpact": "none",
    }


@pytest.mark.asyncio
async def test_yesterday_load_includes_whole_day_cost_without_exercise(
    db_conn: AsyncConnection,
) -> None:
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()
    subject_date = date(2026, 7, 29)

    async with session_factory() as session:
        session.add(
            Profile(
                id=user_id,
                display_name="Whole-day cost test",
                role=UserRole.admin,
                timezone="Europe/London",
                is_active=True,
            )
        )
        await session.flush()
        session.add(
            DailyMetric(
                user_id=user_id,
                calendar_date=subject_date - timedelta(days=1),
                stress_avg=61,
                body_battery_drained=78,
                body_battery_end=9,
                raw_payload=_daily_aggregate_raw(
                    subject_date - timedelta(days=1),
                    "2026-07-29T00:00:00.0",
                ),
            )
        )
        await session.commit()

        packet = await MorningAnalysisService(session)._yesterday_load(
            user_id,
            subject_date,
            "Europe/London",
        )

    assert packet["activityCount"] == 0
    assert packet["status"] == "none"
    assert packet["statusScope"] == "exercise_only"
    assert packet["totalTrainingLoad"] == 0
    assert packet["wholeDayCost"] == {
        "calendarDate": "2026-07-28",
        "allDayStressAvg": 61,
        "bodyBatteryDrained": 78,
        "bodyBatteryEnd": 9,
        "coverage": {
            "status": "complete",
            "stressStatus": "complete",
            "bodyBatteryStatus": "complete",
            "asOfLocal": "2026-07-29T00:00:00",
        },
        "classificationImpact": "none",
    }
    assert "`yesterdayLoad.wholeDayCost` independently" in SYSTEM_PROMPT


def test_yesterday_load_omits_partial_day_aggregates() -> None:
    calendar_date = date(2026, 7, 31)
    metric = DailyMetric(
        user_id=uuid.uuid4(),
        calendar_date=calendar_date,
        stress_avg=12,
        body_battery_drained=1,
        body_battery_end=92,
        raw_payload=_daily_aggregate_raw(calendar_date, "2026-07-31T08:44:00.0"),
    )

    packet = _yesterday_load_packet([], [], metric)["wholeDayCost"]

    assert packet["allDayStressAvg"] is None
    assert packet["bodyBatteryDrained"] is None
    assert packet["bodyBatteryEnd"] is None
    assert packet["coverage"] == {
        "status": "incomplete",
        "stressStatus": "incomplete",
        "bodyBatteryStatus": "incomplete",
        "asOfLocal": "2026-07-31T08:44:00",
    }


def test_partial_or_completed_day_cost_never_changes_deterministic_verdict() -> None:
    calendar_date = date(2026, 7, 31)
    common = {
        "user_id": uuid.uuid4(),
        "calendar_date": calendar_date,
        "readiness_score": 72,
        "readiness_level": "High",
        "hrv_weekly_avg_ms": 51,
        "hrv_baseline_low_ms": 43,
        "hrv_status": "Balanced",
        "resting_heart_rate_bpm": 44,
    }
    partial = DailyMetric(
        **common,
        stress_avg=12,
        body_battery_drained=1,
        body_battery_end=92,
        raw_payload=_daily_aggregate_raw(calendar_date, "2026-07-31T08:44:00.0"),
    )
    complete = DailyMetric(
        **common,
        stress_avg=28,
        body_battery_drained=70,
        body_battery_end=16,
        raw_payload=_daily_aggregate_raw(calendar_date, "2026-08-01T00:00:00.0"),
    )

    kwargs = {
        "sleep": None,
        "age_adjusted_sleep_score": 82,
        "manual_entries": [],
        "planned_workouts": [],
    }

    assert _morning_verdict(daily_metric=partial, **kwargs) == _morning_verdict(
        daily_metric=complete,
        **kwargs,
    )


_RAW_PAYLOAD_WITH_LOAD = {
    "training_status": {
        "mostRecentTrainingStatus": {
            "latestTrainingStatusData": {
                "3508557070": {
                    "trainingStatus": 7,
                    "acuteTrainingLoadDTO": {
                        "dailyTrainingLoadAcute": 1074,
                        "dailyTrainingLoadChronic": 710,
                    },
                }
            }
        },
        "mostRecentTrainingLoadBalance": {
            "metricsTrainingLoadBalanceDTOMap": {
                "3508557070": {"trainingBalanceFeedbackPhrase": "BALANCED"}
            }
        },
    },
    "stats": {
        "totalSteps": 8423,
        "moderateIntensityMinutes": 30,
        "vigorousIntensityMinutes": 45,
    },
}


def test_training_and_activity_fields_surfaces_already_captured_payload() -> None:
    fields = _training_and_activity_fields(_RAW_PAYLOAD_WITH_LOAD)

    assert fields["chronicTrainingLoad"] == 710
    assert fields["acuteChronicLoadRatio"] == 1.51  # 1074 / 710
    assert fields["trainingLoadBalance"] == "BALANCED"
    assert fields["steps"] == 8423
    assert fields["intensityMinutes"] == 75  # 30 moderate + 45 vigorous


def test_training_and_activity_fields_degrades_to_none_when_absent() -> None:
    fields = _training_and_activity_fields({})

    assert fields == {
        "chronicTrainingLoad": None,
        "acuteChronicLoadRatio": None,
        "trainingLoadBalance": None,
        "steps": None,
        "intensityMinutes": None,
    }


def test_daily_metric_packet_includes_load_context() -> None:
    row = DailyMetric(
        user_id=uuid.uuid4(),
        calendar_date=date(2026, 6, 18),
        readiness_score=71,
        acute_load=1074,
        raw_payload=_RAW_PAYLOAD_WITH_LOAD,
    )

    packet = _daily_metric_packet(row)

    assert packet is not None
    # existing fields still present
    assert packet["readinessScore"] == 71
    assert packet["acuteLoad"] == 1074
    # new surfaced fields
    assert packet["acuteChronicLoadRatio"] == 1.51
    assert packet["intensityMinutes"] == 75
    assert packet["trainingLoadBalance"] == "BALANCED"


def test_daily_metric_packet_safe_without_raw_payload() -> None:
    # A transient row before flush has raw_payload=None; must not raise.
    row = DailyMetric(user_id=uuid.uuid4(), calendar_date=date(2026, 6, 18))

    packet = _daily_metric_packet(row)

    assert packet is not None
    assert packet["acuteChronicLoadRatio"] is None
    assert packet["intensityMinutes"] is None


def test_training_load_signal_uses_packet_acwr_and_recovery_time() -> None:
    packet = _daily_metric_packet(
        DailyMetric(
            user_id=uuid.uuid4(),
            calendar_date=date(2026, 7, 24),
            recovery_time_min=2880,
            raw_payload=_RAW_PAYLOAD_WITH_LOAD,
        )
    )

    assert _training_load_signal(packet) == {
        "acuteChronicLoadRatio": 1.51,
        "recoveryTimeMin": 2880,
    }


@pytest.mark.parametrize(
    ("training_load", "expected_status", "expected_source"),
    [
        (
            {
                "acuteChronicLoadRatio": ACWR_AMBER_CAP_THRESHOLD,
                "recoveryTimeMin": 0,
            },
            "Amber",
            "acute_chronic_load_ratio",
        ),
        (
            {
                "acuteChronicLoadRatio": ACWR_AMBER_CAP_THRESHOLD - 0.01,
                "recoveryTimeMin": RECOVERY_TIME_AMBER_CAP_MIN + 1,
            },
            "Amber",
            "recovery_time",
        ),
        (
            {
                "acuteChronicLoadRatio": ACWR_AMBER_CAP_THRESHOLD - 0.01,
                "recoveryTimeMin": RECOVERY_TIME_AMBER_CAP_MIN,
            },
            "Green",
            None,
        ),
    ],
)
def test_training_load_thresholds_cap_only_above_the_set_boundaries(
    training_load: dict[str, float | int],
    expected_status: str,
    expected_source: str | None,
) -> None:
    daily_metric = DailyMetric(
        user_id=uuid.uuid4(),
        calendar_date=date(2026, 7, 24),
        readiness_level="High",
        hrv_weekly_avg_ms=50,
        hrv_baseline_low_ms=43,
        hrv_status="Balanced",
        raw_payload={},
    )

    verdict = _morning_verdict(
        daily_metric=daily_metric,
        sleep=None,
        age_adjusted_sleep_score=80,
        manual_entries=[],
        planned_workouts=[],
        training_load=training_load,
    )

    assert verdict["status"] == expected_status
    assert verdict["trainingLoadCap"]["triggered"] is (expected_source is not None)
    assert verdict["trainingLoadCap"]["applied"] is (expected_source is not None)
    assert verdict["trainingLoadCap"]["sources"] == (
        [expected_source] if expected_source is not None else []
    )


def test_july_24_load_driven_shape_is_capped_at_amber() -> None:
    """Hold Batch 170 evidence positive so the Batch 167 load cap stays isolated."""
    daily_metric = DailyMetric(
        user_id=uuid.uuid4(),
        calendar_date=date(2026, 7, 24),
        readiness_level="Low",
        recovery_time_min=2880,
        hrv_weekly_avg_ms=50,
        hrv_baseline_low_ms=43,
        hrv_status="Balanced",
        raw_payload={},
    )
    kwargs = {
        "daily_metric": daily_metric,
        "sleep": None,
        "age_adjusted_sleep_score": 80,
        "manual_entries": [_positive_morning_checkin(daily_metric.user_id)],
        "planned_workouts": [],
        "yesterday_load": {"status": "hard"},
    }

    before_cap = _morning_verdict(**kwargs)
    after_cap = _morning_verdict(
        **kwargs,
        training_load={
            "acuteChronicLoadRatio": None,
            "recoveryTimeMin": daily_metric.recovery_time_min,
        },
    )

    assert before_cap["status"] == "Green"
    assert before_cap["readinessInterpretation"] == "load_driven"
    assert after_cap["status"] == "Amber"
    assert after_cap["readinessInterpretation"] == "load_driven"
    assert after_cap["trainingLoadCap"]["applied"] is True
    assert after_cap["trainingLoadCap"]["sources"] == ["recovery_time"]
    assert "training_load_amber_cap" in after_cap["safetyRulesApplied"]


@pytest.mark.parametrize(
    ("age_adjusted_sleep_score", "readiness_level", "hrv_status", "expected_without_load"),
    [
        (58, "High", "Balanced", "Red"),
        (80, "Poor", "Balanced", "Amber"),
        (80, "High", "Balanced", "Green"),
    ],
)
def test_training_load_cap_never_makes_the_existing_light_greener(
    age_adjusted_sleep_score: int,
    readiness_level: str,
    hrv_status: str,
    expected_without_load: str,
) -> None:
    daily_metric = DailyMetric(
        user_id=uuid.uuid4(),
        calendar_date=date(2026, 7, 24),
        readiness_level=readiness_level,
        hrv_weekly_avg_ms=50,
        hrv_baseline_low_ms=43,
        hrv_status=hrv_status,
        raw_payload={},
    )
    kwargs = {
        "daily_metric": daily_metric,
        "sleep": None,
        "age_adjusted_sleep_score": age_adjusted_sleep_score,
        "manual_entries": [],
        "planned_workouts": [],
    }

    without_load = _morning_verdict(**kwargs)
    with_load = _morning_verdict(
        **kwargs,
        training_load={
            "acuteChronicLoadRatio": ACWR_AMBER_CAP_THRESHOLD,
            "recoveryTimeMin": 0,
        },
    )
    caution_rank = {"Green": 0, "Amber": 1, "Red": 2}

    assert without_load["status"] == expected_without_load
    assert caution_rank[with_load["status"]] >= caution_rank[without_load["status"]]
    expected_with_load = "Amber" if expected_without_load == "Green" else expected_without_load
    assert with_load["status"] == expected_with_load


# --- Batch 86 (#159): deterministic "Today" action block ---------------------


def _bike_workout(**overrides: Any) -> PlannedWorkout:
    defaults: dict[str, Any] = {
        "id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "workout_date": date(2026, 7, 11),
        "version": 1,
        "title": "Sweet Spot 3x12",
        "workout_type": "bike_sweet_spot",
        "structured_workout": {},
    }
    defaults.update(overrides)
    return PlannedWorkout(**defaults)


def _swap_packet() -> dict[str, Any]:
    return {
        "hardWorkoutId": str(uuid.uuid4()),
        "hardTitle": "VO2 5x4",
        "hardCategory": "cycle",
        "moveToDate": "2026-07-18",
        "moveToWeekday": "Saturday",
        "bringForwardTitle": "Zone 2 endurance",
    }


def test_build_today_actions_leads_with_swap_then_ride() -> None:
    ride = _bike_workout()
    swap = _swap_packet()
    actions = build_today_actions(
        verdict={"status": "Amber", "swapSuggestion": swap},
        planned_workouts=[ride],
        thermal_review={"flags": []},
        recommend_breathwork=False,
    )

    assert [action["kind"] for action in actions] == ["apply_swap", "approve_ride"]
    assert actions[0]["plannedWorkoutId"] == swap["hardWorkoutId"]
    assert actions[0]["targetDate"] == "2026-07-18"
    assert "Saturday" in actions[0]["title"]
    assert actions[1]["plannedWorkoutId"] == str(ride.id)
    assert actions[1]["detail"]  # a scannable hint is always present


def test_build_today_actions_red_ride_detail_and_no_swap() -> None:
    ride = _bike_workout(workout_type="bike_endurance")
    actions = build_today_actions(
        verdict={"status": "Red"},
        planned_workouts=[ride],
        thermal_review={"flags": []},
        recommend_breathwork=False,
    )

    assert [action["kind"] for action in actions] == ["approve_ride"]
    assert "recovery" in actions[0]["detail"].lower()


def test_build_today_actions_green_clean_degrades_to_empty() -> None:
    actions = build_today_actions(
        verdict={"status": "Green"},
        planned_workouts=[_bike_workout()],
        thermal_review={"flags": []},
        recommend_breathwork=False,
    )

    assert actions == []


def test_build_today_actions_surfaces_green_chronic_deload_proposal() -> None:
    ride = _bike_workout()
    actions = build_today_actions(
        verdict={
            "status": "Green",
            "chronicAction": {
                "triggered": True,
                "kind": "deload_proposal",
                "verdictImpact": "none",
            },
        },
        planned_workouts=[ride],
        thermal_review={"flags": []},
        recommend_breathwork=False,
    )

    assert [action["kind"] for action in actions] == ["approve_ride"]
    assert actions[0]["title"] == "Approve today's deload ride"
    assert actions[0]["plannedWorkoutId"] == str(ride.id)
    assert "Sustained recovery strain" in actions[0]["detail"]


_ENDURANCE_STRUCTURED = {
    "format": "bike",
    "steps": [
        {"label": "Warm-up", "minutes": 10, "target": "easy spin"},
        {"label": "Endurance", "minutes": 90, "target": "64-70% FTP 85rpm"},
        {"label": "Cool-down", "minutes": 10, "target": "easy spin"},
    ],
}
_HARD_VO2_STRUCTURED = {
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


def test_verdict_adjustment_packet_holds_zone_two_and_cuts_duration() -> None:
    """Batch 173.3: an already-Zone-2 ride is only shortened — the packet says the
    intensity is held (not dropped to 54/60), and the eased-ride hint quotes it."""
    ride = _bike_workout(
        workout_type="bike_endurance",
        intensity_target="64-70% FTP",
        structured_workout=_ENDURANCE_STRUCTURED,
    )
    packet = _verdict_adjustment_packet("Amber", [ride])
    assert packet is not None
    assert packet["intensityHeldAtEndurance"] is True
    assert packet["plannedWorkPowerPct"] == 67
    assert packet["adjustedWorkPowerPct"] == 67  # held at Zone 2
    assert packet["adjustedDurationMin"] < packet["plannedDurationMin"]
    assert packet["classificationImpact"] == "none"
    assert packet["plannedWorkoutId"] == str(ride.id)

    detail = _eased_ride_detail("Amber", packet)
    assert "Zone 2" in detail
    assert f"{packet['adjustedWorkPowerPct']}% FTP" in detail
    assert f"{packet['adjustedDurationMin']} min" in detail


def test_verdict_adjustment_packet_eases_hard_ride_and_removes_hit() -> None:
    ride = _bike_workout(
        workout_type="bike_vo2",
        intensity_target="105-110% FTP",
        structured_workout=_HARD_VO2_STRUCTURED,
    )
    packet = _verdict_adjustment_packet("Amber", [ride])
    assert packet is not None
    assert packet["intensityHeldAtEndurance"] is False
    assert packet["adjustedWorkPowerPct"] < packet["plannedWorkPowerPct"]
    assert packet["adjustedWorkPowerPct"] <= 98  # HIT capped away
    assert packet["removedHit"] is True

    detail = _eased_ride_detail("Amber", packet)
    assert "no HIT/VO2" in detail
    assert f"{packet['adjustedWorkPowerPct']}% FTP" in detail


def test_verdict_adjustment_packet_is_none_when_not_cautious() -> None:
    ride = _bike_workout(
        workout_type="bike_endurance",
        intensity_target="64-70% FTP",
        structured_workout=_ENDURANCE_STRUCTURED,
    )
    assert _verdict_adjustment_packet("Green", [ride]) is None
    assert _verdict_adjustment_packet("Amber", []) is None  # no ride today


def test_build_today_actions_quotes_the_deterministic_adjustment() -> None:
    """The eased-ride action detail quotes verdict.verdictAdjustment, so the home
    card and the narrative show one set of numbers (Batch 173.2/173.3)."""
    ride = _bike_workout(
        workout_type="bike_endurance",
        intensity_target="64-70% FTP",
        structured_workout=_ENDURANCE_STRUCTURED,
    )
    packet = _verdict_adjustment_packet("Amber", [ride])
    actions = build_today_actions(
        verdict={"status": "Amber", "verdictAdjustment": packet},
        planned_workouts=[ride],
        thermal_review={"flags": []},
        recommend_breathwork=False,
    )
    approve = next(a for a in actions if a["kind"] == "approve_ride")
    assert "Zone 2" in approve["detail"]
    assert packet is not None
    assert f"{packet['adjustedWorkPowerPct']}% FTP" in approve["detail"]


def test_build_today_actions_sleep_and_thermal_nudges() -> None:
    actions = build_today_actions(
        verdict={"status": "Green"},
        planned_workouts=[],
        thermal_review={
            "flags": ["thermal_disruption_likely"],
            "indoorPeakC": 20.4,
            "targetPreCoolC": 17.0,
        },
        recommend_breathwork=True,
    )

    assert [action["kind"] for action in actions] == ["sleep", "thermal"]
    sleep = actions[0]
    assert sleep["href"] == "/sleep"
    assert sleep["plannedWorkoutId"] is None
    thermal = actions[1]
    assert thermal["href"] == "/environment"
    assert "20.4" in thermal["detail"]


def test_build_today_actions_skips_completed_ride_and_truncates() -> None:
    completed = _bike_workout(status="completed")
    active = _bike_workout(workout_type="bike_tempo")
    verdict = {"status": "Amber", "swapSuggestion": _swap_packet()}
    thermal = {"flags": ["precool_target_missed"], "indoorPeakC": 19.8, "targetPreCoolC": 17.0}

    actions = build_today_actions(
        verdict=verdict,
        planned_workouts=[completed, active],
        thermal_review=thermal,
        recommend_breathwork=True,
    )

    # The completed session is never offered for approval; the active bike is.
    assert [action["kind"] for action in actions] == [
        "apply_swap",
        "approve_ride",
        "sleep",
        "thermal",
    ]
    approve = next(action for action in actions if action["kind"] == "approve_ride")
    assert approve["plannedWorkoutId"] == str(active.id)

    # max_actions truncates in priority order.
    capped = build_today_actions(
        verdict=verdict,
        planned_workouts=[completed, active],
        thermal_review=thermal,
        recommend_breathwork=True,
        max_actions=2,
    )
    assert [action["kind"] for action in capped] == ["apply_swap", "approve_ride"]


def test_thermal_action_ignores_a_cool_room() -> None:
    assert _thermal_action({"flags": ["wind_disruption_watch"]}) is None
    assert _thermal_action({"flags": []}) is None
    assert _thermal_action({}) is None
