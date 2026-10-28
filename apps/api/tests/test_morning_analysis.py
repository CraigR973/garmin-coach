from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Any
from unittest.mock import Mock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from src.models.coaching import (
    DAILY_METRIC_PHASE_MORNING,
    DAILY_METRIC_PHASE_SETTLED,
    Activity,
    Analysis,
    CheckInReading,
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
from src.services import morning_analysis as morning_analysis_module
from src.services.coach_sections import (
    daily_metric_packet as _daily_metric_packet,
)
from src.services.coach_sections import (
    thermal_review as _thermal_review,
)
from src.services.coach_sections import (
    training_and_activity_fields as _training_and_activity_fields,
)
from src.services.daily_metric_coverage import DayAggregates
from src.services.graded_morning import brief_is_written, brief_written_at
from src.services.holiday_pause import HolidayPauseService, HolidayWindow
from src.services.morning_analysis import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    ClaudeGenerationResult,
    MorningAnalysisError,
    MorningAnalysisService,
    _age_comparison,
    _date_label,
    _eased_ride_detail,
    _manual_entry_packet,
    _metrics_vs_baselines,
    _rest_day_context,
    _sleep_packet,
    _thermal_action,
    _training_load_signal,
    _yesterday_load_packet,
    build_morning_user_prompt,
    build_today_actions,
    subjective_score_label,
)
from src.services.morning_verdict import (
    GRADED_PICK_LINE,
    _red_plan_lines,
    _red_ride_adjustment,
    graded_plan_adjustments,
    verdict_context,
)
from src.services.notes_reader import notes_hash
from src.services.personal_baselines import (
    BASELINE_TREND_WINDOW_DAYS,
    READINESS_TREND_DECLINE_POINTS,
    READINESS_TREND_MIN_SAMPLES_PER_HALF,
    readiness_baseline_trend,
)
from src.services.verdict_grading import GradingInputs, grade
from tests.test_morning_verdict import _graded_packet
from tests.test_morning_verdict import _metric as _verdict_metric
from tests.test_morning_verdict import _sleep as _verdict_sleep


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
    context = verdict_context(
        daily_metric=None,
        sleep=None,
        age_adjusted_sleep_score=78,
        manual_entries=[],
        planned_workouts=[skipped_ride],
        rest_day=rest_day,
    )
    verdict = _graded_packet(context, [skipped_ride])

    assert rest_day == {
        "isRestDay": True,
        "reason": "holiday",
        "insideHolidayWindow": True,
        "allPlannedWorkoutsSkipped": True,
        # Batch 313: whether a plan week covers the day, for the planned-rest rule.
        "insidePlanWeek": False,
        "holidayWindows": [
            {
                "startDate": "2026-07-12",
                "endDate": "2026-07-19",
                "isActive": True,
            }
        ],
    }
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
    context = verdict_context(
        daily_metric=_verdict_metric(),
        sleep=_verdict_sleep(),
        age_adjusted_sleep_score=82,
        manual_entries=[],
        planned_workouts=[workout],
        rest_day=rest_day,
    )
    verdict = _graded_packet(context, [workout])

    assert rest_day["isRestDay"] is False
    assert verdict["status"] == "Green"
    assert verdict["dayType"] == "training"
    assert verdict["planAdjustments"] == [
        "Proceed with the planned workout if warm-up confirms readiness."
    ]


def test_the_context_reads_his_latest_scored_check_in_by_its_word() -> None:
    """Batch 308: the check-in is context (his word); the graded verdict rates it."""
    user_id = uuid.uuid4()
    base_kwargs: dict[str, Any] = {
        "daily_metric": None,
        "sleep": None,
        "age_adjusted_sleep_score": 78,
        "planned_workouts": [],
    }

    meh = verdict_context(
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
    ok = verdict_context(
        **base_kwargs,
        manual_entries=[
            ManualEntry(
                user_id=user_id,
                entry_date=date(2026, 7, 24),
                entry_at_utc=datetime(2026, 7, 24, 7, 5),
                subjective_score=6,
            )
        ],
    )

    assert (meh["subjectiveScore"], meh["subjectiveLabel"]) == (4, "Meh")
    assert (ok["subjectiveScore"], ok["subjectiveLabel"]) == (6, "OK")


@pytest.mark.asyncio
async def test_generate_and_store_morning_analysis_packet_and_output(
    db_conn: AsyncConnection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_mock = Mock()
    monkeypatch.setattr(morning_analysis_module, "log", log_mock)
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
                    sleep_setup_json={
                        "beddingWeight": "thin_cover",
                        "windowCount": 2,
                        "windowApertureCm": 10,
                        "blindPosition": "away_from_windowsill",
                        "preCoolStartLocal": "18:30",
                    },
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
                    overnight_wind_direction_deg=225.0,
                    overnight_relative_humidity_mean_pct=82.0,
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
        assert [section["id"] for section in packet["prompt"]["requiredOutputSections"]] == [
            "sleep_and_recovery",
            "metrics_vs_baselines",
            "thermal_environment",
            "experiment_update",
            "todays_call",
        ]
        assert "`## Experiment update`" in fake_client.last_prompt
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
        assert packet["manualEntries"][0]["sleepSetup"] == {
            "beddingWeight": "thin_cover",
            "windowCount": 2,
            "windowApertureCm": 10,
            "blindPosition": "away_from_windowsill",
            "preCoolStartLocal": "18:30",
        }
        assert packet["environment"]["weather"]["overnightWindDirectionDeg"] == 225.0
        assert packet["environment"]["weather"]["overnightRelativeHumidityMeanPct"] == 82.0
        assert packet["verdict"]["subjectiveLabel"] == "OK"
        assert packet["verdict"]["status"] == "Amber"
        # Batch 296: the graded verdict sets the colour; since Batch 308 its packet is an
        # allow-list, and the ladder's working (readinessInterpretation among it) is gone.
        assert packet["verdict"]["engine"] == "graded"
        assert "readinessInterpretation" not in packet["verdict"]
        assert packet["verdict"]["readinessBaselineTrend"]["status"] == "insufficient_data"
        assert packet["verdict"]["hasVo2WorkoutToday"] is True
        assert len(packet["experimentLoop"]["experiments"]) == 4
        assert packet["experimentLoop"]["rules"] == {
            "autoConclude": False,
            "unknownApplicationMeansNotApplied": False,
            "derivableSleepOutcomesNeedUserObservation": False,
        }
        assert all(
            item["conclusion"] == "human_gated_terminal"
            for item in packet["experimentLoop"]["experiments"]
        )
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
        log_mock.warning.assert_called_once_with(
            "morning_analysis_missing_required_sections",
            user_id=str(user_id),
            subject_date="2026-01-01",
            prompt_version=PROMPT_VERSION,
            missing_sections=[
                "sleep_and_recovery",
                "metrics_vs_baselines",
                "thermal_environment",
                "experiment_update",
                "todays_call",
            ],
        )

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
                    workout_date=subject_date + timedelta(days=3),
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
    assert swap["moveToDate"] == (subject_date + timedelta(days=3)).isoformat()
    assert packet["verdict"]["todayActions"][0]["kind"] == "apply_swap"
    assert all(
        item["title"] != "Approve today's deload ride" for item in packet["verdict"]["todayActions"]
    )
    assert "qualify_reds_before_structural_action" in packet["prompt"]["outputRules"]


@pytest.mark.asyncio
async def test_morning_packet_real_0731_0801_reds_now_both_count(
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
                friday_entry := ManualEntry(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    entry_date=friday,
                    entry_at_utc=datetime(2026, 7, 31, 7, 30),
                    subjective_score=4,
                    notes=(
                        "Presumably due to a harder day's training yesterday and cumulative "
                        "3 day training load."
                    ),
                ),
                saturday_entry := ManualEntry(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    entry_date=subject_date,
                    entry_at_utc=datetime(2026, 8, 1, 8, 44),
                    subjective_score=3,
                    feel="Have a bit of a hangover today",
                    notes="Was out last night drinking, around 13 UK units.",
                ),
            ]
        )
        await session.flush()
        # Batch 297: the causes come from the notes reader's stored readings.
        session.add_all(
            [
                _stored_reading(
                    friday_entry,
                    training_load=("now", "harder day's training yesterday"),
                ),
                _stored_reading(
                    saturday_entry,
                    alcohol=("last_night", "out last night drinking, around 13 UK units"),
                ),
            ]
        )
        await session.commit()

        packet = await MorningAnalysisService(session).assemble_context_packet(player, subject_date)

    action = packet["verdict"]["chronicAction"]
    assert action["redMorningObservedCount"] == 2
    assert action["redMorningCount"] == 2
    assert action["triggered"] is True
    assert action["kind"] == "rearrange_proposal"
    assert [item["classification"] for item in action["redMorningQualifications"]] == [
        "endogenous_training_signal",
        "acute_cause_with_systemic_strain",
    ]
    assert {item["reason"] for item in action["recordedTrainingContext"]} >= {
        "training_load",
        "alcohol",
    }
    # Batch 212: every check-in-derived row quotes the phrase that produced it, so
    # a tag Mark queries can be explained (or recognised as wrong) from the packet.
    check_in_rows = [
        item for item in action["recordedTrainingContext"] if item["source"] == "morning_check_in"
    ]
    assert check_in_rows, "expected at least one check-in-derived context row"
    for item in check_in_rows:
        assert item["matchedText"], f"{item['reason']} row carries no matched phrase"
        assert item["basis"] == "his words in the check-in note, as the notes reader quoted them"


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
async def test_a_failed_brief_leaves_the_graded_morning_stored_and_a_retry_fills_it(
    db_conn: AsyncConnection,
) -> None:
    """Batch 302. Until this batch the test pinned the opposite — a truncated
    generation persisted no morning row at all — which is how an Anthropic outage
    took the colour with the prose. The row is stored when the morning is graded;
    a failed call leaves it without prose, and the retry writes into it."""
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

        mornings = select(Analysis).where(
            Analysis.user_id == user_id,
            Analysis.analysis_type == "morning",
            Analysis.subject_date == subject_date,
        )
        [stored] = (await session.execute(mornings)).scalars().all()
        assert stored.output_markdown == ""
        assert stored.model_name is None
        assert stored.raw_response == {}
        assert stored.verdict == stored.context_packet["verdict"]["status"]
        assert brief_is_written(stored) is False

        # The retry pays for one brief and writes it into the same row, from the
        # packet the morning was graded on.
        fake_client = FakeMorningClient()
        retried = await service.generate_and_store(player, subject_date, client=fake_client)
        assert retried.generated is True
        assert retried.analysis.id == stored.id
        assert fake_client.calls == 1
        assert brief_is_written(retried.analysis) is True
        assert retried.analysis.raw_response["contextVerdict"] == stored.verdict
        assert brief_written_at(retried.analysis.raw_response) is not None
        assert len((await session.execute(mornings)).scalars().all()) == 1


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
                    # The fallback copy is derived from the same executable IR as
                    # delivery, so this fixture must describe a deliverable ride.
                    structured_workout=_HARD_VO2_STRUCTURED,
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
    # Batch 306: low readiness confirming a fair night is a tired morning, so after the
    # swap Home offers the pick (easy Zone 2 or tempo) rather than one eased ride.
    actions = verdict["todayActions"]
    assert [action["kind"] for action in actions][:2] == ["apply_swap", "pick_ride"]
    assert actions[0]["targetDate"] == saturday.isoformat()
    assert actions[0]["plannedWorkoutId"] == swap["hardWorkoutId"]
    pick = next(action for action in actions if action["kind"] == "pick_ride")
    assert pick["plannedWorkoutId"] == swap["hardWorkoutId"]
    assert [choice["variant"] for choice in pick["choices"]] == ["zone2", "tempo"]

    adjustments = verdict["planAdjustments"]
    # The swap leads; the pick is the fallback.
    assert "move vo2 max 30/30 from thursday to saturday" in adjustments[0].lower()
    assert GRADED_PICK_LINE.format(title=swap["hardTitle"]) in adjustments[1:]

    # Batch 70 (#143): the same cautious morning reports the week's mix. Batch 306:
    # neither pick keeps the VO2 work, so today's VO2 counts as missed this week.
    mix = verdict["weeklyMix"]
    assert mix.get("eased") is None
    assert mix["shortfall"]["bucket"] == "vo2"
    assert mix["shortfall"]["message"] in adjustments
    vo2_bucket = next(bucket for bucket in mix["buckets"] if bucket["bucket"] == "vo2")
    assert vo2_bucket["target"] == 1 and vo2_bucket["atRisk"] is True

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
async def test_morning_packet_body_battery_reads_settled_row_not_morning_row(
    db_conn: AsyncConnection,
) -> None:
    """Batch 216 regression, pinning Mark's 2026-08-19 report: the Body Battery
    charge row rendered with its baseline but a blank value because the packet
    read the morning wake row, which can never hold a complete local-day total.
    A settled row synced later in the day must be picked up instead — recovery
    reads (readiness/RHR/HRV) must stay on the morning row throughout."""
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()
    subject_date = date(2026, 8, 19)

    async with session_factory() as session:
        player = Profile(
            id=user_id,
            display_name="Morning Body Battery Packet",
            role=UserRole.admin,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(player)
        await session.flush()
        session.add(
            DailyMetric(
                user_id=user_id,
                calendar_date=subject_date,
                phase="morning",
                readiness_score=68,
                body_battery_charged=52,
                body_battery_drained=31,
                raw_payload={
                    "body_battery": {
                        "charged": 52,
                        "drained": 31,
                        "startTimestampLocal": f"{subject_date.isoformat()}T00:00:00.0",
                        "endTimestampLocal": f"{subject_date.isoformat()}T09:10:00.0",
                    }
                },
            )
        )
        session.add(
            DailyMetric(
                user_id=user_id,
                calendar_date=subject_date,
                phase="settled",
                readiness_score=61,  # a later re-sync value; must never surface here
                body_battery_charged=80,
                body_battery_drained=64,
                raw_payload={
                    "body_battery": {
                        "charged": 80,
                        "drained": 64,
                        "startTimestampLocal": f"{subject_date.isoformat()}T00:00:00.0",
                        "endTimestampLocal": (
                            f"{(subject_date + timedelta(days=1)).isoformat()}T00:00:00.0"
                        ),
                    }
                },
            )
        )
        session.add_all(
            MetricBaseline(
                user_id=user_id,
                metric_key=key,
                metric_label=label,
                source="test",
                window_start_date=date(2026, 5, 1),
                window_end_date=date(2026, 8, 18),
                sample_count=109,
                excluded_sample_count=0,
                mean_value=63.8,
                median_value=64,
                lower_quartile_value=54,
                upper_quartile_value=74,
                raw_payload={},
            )
            for key, label in [
                ("body_battery_charge", "Body Battery charge"),
                ("body_battery_drain", "Body Battery drain"),
                ("readiness_score", "Training readiness"),
            ]
        )
        await session.commit()

        packet = await MorningAnalysisService(session).assemble_context_packet(player, subject_date)

    table = {row["metricKey"]: row for row in packet["metricsVsBaselines"]}
    assert table["body_battery_charge"]["currentValue"] == 80
    assert table["body_battery_drain"]["currentValue"] == 64
    assert table["readiness_score"]["currentValue"] == 68


@pytest.mark.asyncio
async def test_live_morning_packet_surfaces_charge_and_explains_withheld_drain(
    db_conn: AsyncConnection,
) -> None:
    """Batch 224: no settled row exists when the live morning is generated."""

    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()
    subject_date = date(2026, 8, 24)

    async with session_factory() as session:
        player = Profile(
            id=user_id,
            display_name="Live Morning Body Battery",
            role=UserRole.admin,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(player)
        await session.flush()
        session.add(
            DailyMetric(
                user_id=user_id,
                calendar_date=subject_date,
                phase="morning",
                readiness_score=77,
                body_battery_charged=69,
                body_battery_drained=10,
                body_battery_end=97,
                stress_avg=14,
                raw_payload={
                    "body_battery": {
                        "charged": 69,
                        "drained": 10,
                        "startTimestampLocal": f"{subject_date.isoformat()}T00:00:00.0",
                        "endTimestampLocal": f"{subject_date.isoformat()}T09:26:00.0",
                    }
                },
            )
        )
        session.add_all(
            MetricBaseline(
                user_id=user_id,
                metric_key=key,
                metric_label=label,
                source="test",
                window_start_date=date(2026, 5, 1),
                window_end_date=date(2026, 8, 23),
                sample_count=83,
                excluded_sample_count=0,
                mean_value=mean,
                median_value=median,
                lower_quartile_value=lower,
                upper_quartile_value=upper,
                raw_payload={},
            )
            for key, label, mean, median, lower, upper in [
                ("body_battery_charge", "Body Battery charge", 65.2, 68, 59.5, 72),
                ("body_battery_drain", "Body Battery drain", 64.6, 67, 57.5, 75),
            ]
        )
        await session.commit()

        packet = await MorningAnalysisService(session).assemble_context_packet(player, subject_date)

    table = {row["metricKey"]: row for row in packet["metricsVsBaselines"]}
    assert table["body_battery_charge"]["currentValue"] == 69
    assert table["body_battery_charge"]["basis"] == (
        "Garmin's overnight charge accumulated from midnight to this morning's sync."
    )
    assert table["body_battery_drain"]["currentValue"] is None
    assert table["body_battery_drain"]["deltaVsBaseline"] is None
    assert table["body_battery_drain"]["unavailableReason"] == (
        "This drain is still a part-day value at the morning sync; compare it with your "
        "full-day baseline after the day closes."
    )


@pytest.mark.asyncio
async def test_morning_packet_carries_effective_weight_with_as_of_date(
    db_conn: AsyncConnection,
) -> None:
    """Batch 202: morning/chat can answer body-metric questions from app data."""
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()
    subject_date = date(2026, 1, 5)

    async with session_factory() as session:
        player = Profile(
            id=user_id,
            display_name="Morning Weight Packet",
            role=UserRole.admin,
            timezone="Europe/London",
            is_active=True,
        )
        session.add(player)
        await session.flush()
        session.add(
            DailyMetric(
                user_id=user_id,
                calendar_date=date(2026, 1, 3),
                weight_kg=78.4,
                raw_payload={},
            )
        )
        await session.commit()

        packet = await MorningAnalysisService(session).assemble_context_packet(player, subject_date)

    assert packet["profile"]["weightKg"] == 78.4
    assert packet["profile"]["weightAsOfDate"] == "2026-01-03"
    assert packet["profile"]["weightOnFile"] is True


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
@pytest.mark.parametrize(
    ("feel", "expected_status"),
    [
        pytest.param(3, "Red", id="red_drops_it"),
        # Batch 306: low readiness confirming a fair night is a tired morning, so the
        # VO2 is his pick of easy Zone 2 or tempo, and neither keeps it in the week.
        pytest.param(None, "Amber", id="a_tired_amber_misses_it_too"),
    ],
)
async def test_cautious_morning_says_no_vo2_this_week_when_it_cannot_be_repatched(
    db_conn: AsyncConnection,
    feel: int | None,
    expected_status: str,
) -> None:
    """Batch 70 (#143): a readiness-dropped VO2 with no sound later slot is not
    silently lost — the verdict states plainly it won't be made up this week.

    Batch 299: under the graded verdict only a morning that drops the session says so.
    A Red (here a Rough check-in) replaces it with a recovery spin. An Amber eases it a
    zone at full length, so it still counts and the week is never called short."""
    session_factory = async_sessionmaker(bind=db_conn, expire_on_commit=False)
    user_id = uuid.uuid4()
    subject_date = date(2026, 1, 2)  # Friday — VO2 today, no later bike day this week
    check_ins = (
        [
            ManualEntry(
                user_id=user_id,
                entry_date=subject_date,
                entry_at_utc=datetime(2026, 1, 2, 6, 15),
                subjective_score=feel,
            )
        ]
        if feel is not None
        else []
    )

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
                *check_ins,
            ]
        )
        await session.commit()

        packet = await MorningAnalysisService(session).assemble_context_packet(player, subject_date)

    verdict = packet["verdict"]
    assert verdict["status"] == expected_status
    assert "swapSuggestion" not in verdict  # no sound later slot to swap into
    mix = verdict["weeklyMix"]
    adjustments = verdict["planAdjustments"]
    says_no_vo2 = any("no vo2 session this week" in item.lower() for item in adjustments)
    assert mix["shortfall"]["bucket"] == "vo2"
    assert mix["shortfall"]["repatched"] is False
    assert "eased" not in mix
    assert says_no_vo2


def test_vo2_is_detected_from_buildable_ir_before_type_name() -> None:
    """hasVo2WorkoutToday reads the ride's own steps first, so Red-never-VO2 sees it."""
    workout = PlannedWorkout(
        user_id=uuid.uuid4(),
        workout_date=date(2026, 1, 2),
        version=1,
        title="Manual hard override",
        workout_type="bike_custom",
        structured_workout={
            "format": "bike",
            "steps": [
                {"label": "Warm-up", "minutes": 10, "target": "easy spin"},
                {"label": "Hard work", "minutes": 8, "target": "108% FTP"},
                {"label": "Cool-down", "minutes": 10, "target": "easy spin"},
            ],
        },
    )

    context = verdict_context(
        daily_metric=None,
        sleep=None,
        age_adjusted_sleep_score=58,
        manual_entries=[],
        planned_workouts=[workout],
    )

    assert context["hasVo2WorkoutToday"] is True


def test_no_vo2_is_claimed_when_no_vo2_workout_exists() -> None:
    context = verdict_context(
        daily_metric=None,
        sleep=None,
        age_adjusted_sleep_score=58,
        manual_entries=[],
        planned_workouts=[
            PlannedWorkout(
                user_id=uuid.uuid4(),
                workout_date=date(2026, 1, 2),
                version=1,
                title="Endurance",
                workout_type="bike_endurance",
                structured_workout={
                    "format": "bike",
                    "steps": [{"label": "Endurance", "minutes": 45, "target": "67% FTP"}],
                },
            )
        ],
    )

    assert context["hasVo2WorkoutToday"] is False


def test_prompt_answers_a_question_in_checkin_notes() -> None:
    """Batch 85: the read answers a question Mark leaves in his check-in notes,
    grounded in the packet. The instruction lives in the (version-bumped) system
    prompt, and his note text reaches the user prompt."""
    assert PROMPT_VERSION.startswith("morning-analysis-v62")
    assert "Your question" in SYSTEM_PROMPT
    assert "answer it" in SYSTEM_PROMPT.lower()
    assert "restDay.isRestDay" in SYSTEM_PROMPT
    # Batch 313 reflowed the graded rest-day paragraph; the rule is the words, not the wrap.
    assert "status is skipped" in " ".join(SYSTEM_PROMPT.split())
    assert "experimentLoop.experiments" in SYSTEM_PROMPT
    assert "never ask Mark to notice" in SYSTEM_PROMPT
    assert 'Unknown application is unknown, never "not applied"' in SYSTEM_PROMPT

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


def test_the_prompt_never_states_the_ladders_load_cap() -> None:
    # Batch 296: the graded verdict's load domain rates the ratio; Batch 308 deleted the
    # ladder's prompt, which explained its high-load cap.
    flat = " ".join(SYSTEM_PROMPT.split())
    assert "trainingLoadCap" not in SYSTEM_PROMPT
    assert ">=1.5 triggers the deterministic high-load cap" not in flat
    assert "the graded verdict's load domain has already rated them" in flat


def test_the_prompt_keeps_missing_data_neutral_and_states_the_age_credit_guard() -> None:
    assert "Missing HRV and absent" in SYSTEM_PROMPT
    assert "never describe absent data as proof" in SYSTEM_PROMPT
    assert "verdict.graded.ageCreditGuardApplied" in SYSTEM_PROMPT
    for ladder_rule in ("verdict.sleepCreditCeiling", "verdict.cumulativeEscalation"):
        assert ladder_rule not in SYSTEM_PROMPT


def test_prompt_treats_readiness_baseline_decline_as_warning_only() -> None:
    assert "When verdict.readinessBaselineTrend triggers" in SYSTEM_PROMPT
    assert "never hide, soften" in SYSTEM_PROMPT
    assert "It does not set the" in SYSTEM_PROMPT
    assert "colour itself" in SYSTEM_PROMPT
    assert "readinessEffectiveFloor" not in SYSTEM_PROMPT


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


def _stored_reading(entry: ManualEntry, **causes: tuple[str, str]) -> CheckInReading:
    """A stored notes reading (Batch 297): every flag absent, the given causes present."""
    absent_flag = {"state": "absent", "who": "unknown", "when": "unknown", "words": ""}
    absent_cause = {"state": "absent", "when": "unknown", "words": ""}
    reading: dict[str, Any] = {
        name: dict(absent_flag)
        for name in ("chest_heart", "fever_aches", "head_cold", "unwell", "fatigue")
    }
    for name in ("alcohol", "travel", "disturbed_night", "training_load", "deliberate_rest"):
        when, words = causes.get(name, ("", ""))
        reading[name] = (
            {"state": "present", "when": when, "words": words} if words else dict(absent_cause)
        )
    return CheckInReading(
        user_id=entry.user_id,
        manual_entry_id=entry.id,
        notes_sha256=notes_hash(entry.notes) or "",
        status="read",
        reading=reading,
        model_name="claude-test",
        prompt_version="notes-reader-test",
        created_at=entry.entry_at_utc + timedelta(minutes=1),
    )


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
        # Batch 226: no finished-day figure to compare, so no empty comparison
        # either — a figure with no value is omitted rather than annotated.
        "baselines": {},
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
            [_drain_baseline()],
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
        # Batch 226: the finished day's cost now arrives with the distribution
        # that describes it, wired all the way from the stored baseline rows.
        "baselines": {
            "bodyBatteryDrained": {
                "metricKey": "body_battery_drain",
                "label": "Body Battery drain",
                "baselineMedian": 67.0,
                "baselineMean": 64.58,
                "deltaVsBaseline": 11.0,
                "lowerQuartile": 57.5,
                "upperQuartile": 75.0,
                "sampleCount": 83,
            },
            "allDayStressAvg": {
                "metricKey": "stress_avg",
                "unavailableReason": (
                    "The app has not computed a personal baseline for this figure, so there is "
                    "nothing to compare it against."
                ),
            },
            "bodyBatteryEnd": {
                "metricKey": "body_battery_end",
                "unavailableReason": (
                    "The app has not computed a personal baseline for this figure, so there is "
                    "nothing to compare it against."
                ),
            },
        },
    }
    assert "`yesterdayLoad.wholeDayCost` independently" in SYSTEM_PROMPT
    assert "the compared\nform replaces it" in SYSTEM_PROMPT


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

    packet = _yesterday_load_packet([], [], DayAggregates.from_metric(metric))["wholeDayCost"]

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

    kwargs: dict[str, Any] = {
        "sleep": None,
        "age_adjusted_sleep_score": 82,
        "manual_entries": [],
        "planned_workouts": [],
    }

    assert verdict_context(daily_metric=partial, **kwargs) == verdict_context(
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
        verdict={
            "status": "Amber",
            "swapSuggestion": swap,
            "verdictAdjustment": {"graded": True, "adjustedWorkPowerPct": 94},
        },
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
    ride = _bike_workout(
        workout_type="bike_vo2",
        intensity_target="105-110% FTP",
        structured_workout=_HARD_VO2_STRUCTURED,
    )
    actions = build_today_actions(
        verdict={"status": "Red", "verdictAdjustment": _red_ride_adjustment([ride])},
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


_MARK_0808_STRUCTURED = {
    "format": "bike",
    "steps": [
        {"ramp": [50, 65], "label": "Warm-up ramp 50→65%", "minutes": 5},
        {"label": "Easy Z2 60–65%", "target": "60–65%", "minutes": 35},
        {"ramp": [60, 45], "label": "Cool-down ramp", "minutes": 5},
    ],
}


def _mark_0808_ride() -> PlannedWorkout:
    return _bike_workout(
        workout_date=date(2026, 8, 8),
        title="Easy Z2 (No Sprints)",
        workout_type="bike_endurance",
        status="planned",
        intensity_target="Zone 2 ~65–72% FTP",
        structured_workout=_MARK_0808_STRUCTURED,
    )


def test_red_packet_holds_zone_two_and_the_copy_stops_substituting_it() -> None:
    """Batch 215, pinned on the read Mark actually got. The stored 2026-08-08 packet
    reads ``adjustedDurationMin: 22, adjustedWorkPowerPct: 60,
    intensityHeldAtEndurance: false`` and the brief said "cut to 22 minutes at 60%
    FTP". His objection was that the easy ride is what helps him sleep."""
    ride = _mark_0808_ride()

    packet = _red_ride_adjustment([ride])

    assert packet is not None
    assert packet["plannedDurationMin"] == 45
    assert packet["plannedWorkPowerPct"] == 62
    assert packet["adjustedWorkPowerPct"] == 62  # held, not dropped to 60
    assert packet["adjustedDurationMin"] == 32  # monotonic below Amber, not the pre-fix 22
    assert packet["intensityHeldAtEndurance"] is True
    assert packet["companionSession"] is False
    assert packet["classificationImpact"] == "none"  # still explanatory only

    detail = _eased_ride_detail("Red", packet)
    assert "Zone 2" in detail
    assert "32 min" in detail
    # The copy must no longer tell him to swap an already-easy ride for rest.
    assert "Substitute" not in detail
    assert "mobility, or rest" not in detail


def test_red_packet_still_substitutes_recovery_for_a_hard_ride() -> None:
    """215.4: the safety rail is untouched — a VO2 ride on Red is still replaced,
    and the copy still says so."""
    ride = _bike_workout(
        workout_type="bike_vo2",
        intensity_target="105-110% FTP",
        structured_workout=_HARD_VO2_STRUCTURED,
    )

    packet = _red_ride_adjustment([ride])

    assert packet is not None
    assert packet["intensityHeldAtEndurance"] is False
    assert packet["adjustedWorkPowerPct"] <= 60
    assert packet["durationScalePct"] == 50

    detail = _eased_ride_detail("Red", packet)
    assert "Substitute recovery" in detail


_UPPER_ENDURANCE_STRUCTURED = {
    "format": "bike",
    "steps": [
        {"ramp": [50, 65], "label": "Warm-up ramp 50\u219265%", "minutes": 5},
        {"label": "Upper Z2 70%", "target": "70%", "minutes": 50},
        {"ramp": [60, 45], "label": "Cool-down ramp", "minutes": 5},
    ],
}


def test_upper_endurance_red_is_a_shortened_zone_two_not_a_substitution() -> None:
    """Batch 252.4 re-anchored 68-75% work to 67% FTP, which flipped
    ``intensityHeldAtEndurance`` to false for a ride the transform still routes down
    the endurance path. Keying the copy on that narrow flag made the brief say
    "Substitute recovery ... ~67% FTP" while the delivery rail built a 67% Zone 2
    ride — the brief/delivery disagreement Batch 173.3 and Batch 215 both exist to
    prevent. The substitution wording now reads ``keptAsEndurance`` instead."""
    ride = _bike_workout(
        workout_date=date(2026, 8, 8),
        title="Upper Zone 2",
        workout_type="bike_endurance",
        status="planned",
        intensity_target="Zone 2 ~70% FTP",
        structured_workout=_UPPER_ENDURANCE_STRUCTURED,
    )

    packet = _red_ride_adjustment([ride])
    assert packet is not None
    assert packet["plannedWorkPowerPct"] == 70
    # Eased to the prescription anchor, but still on the endurance path.
    assert packet["adjustedWorkPowerPct"] == 67
    assert packet["keptAsEndurance"] is True
    assert packet["intensityHeldAtEndurance"] is False

    detail = _eased_ride_detail("Red", packet)
    assert "Zone 2" in detail
    assert "67% FTP" in detail
    assert "Substitute" not in detail

    instructions = _red_plan_lines([ride])
    assert any("Hold Zone 2" in line for line in instructions)
    assert not any("Substitute recovery" in line for line in instructions)


def test_a_companion_session_reaches_the_packet_from_the_days_plan() -> None:
    """215.5 through the packet path: the day's other sessions are resolved from the
    planned workouts already in hand, so the brief quotes the same gated figure the
    delivery rail applies. A skipped companion is not load."""
    ride = _mark_0808_ride()
    strength = _bike_workout(
        workout_date=date(2026, 8, 8),
        title="Recovery Morning Routine",
        workout_type="strength_maintenance",
        status="planned",
        structured_workout={},
    )

    shared = _red_ride_adjustment([ride, strength])
    assert shared is not None
    assert shared["companionSession"] is True
    assert shared["adjustedDurationMin"] == 22
    assert shared["adjustedWorkPowerPct"] == 60
    assert shared["intensityHeldAtEndurance"] is False

    strength.status = "skipped"
    alone = _red_ride_adjustment([ride, strength])
    assert alone is not None
    assert alone["companionSession"] is False
    assert alone["adjustedDurationMin"] == 32


def test_red_plan_adjustment_instruction_follows_the_transform() -> None:
    """The instruction handed to the model must not assert a substitution that did
    not happen — that is the same class of false deterministic fact Batch 214 found
    the model will rationalise rather than contradict."""
    endurance = _red_plan_lines([_mark_0808_ride()])
    assert any("Hold Zone 2" in line for line in endurance)
    assert any("sleep pressure" in line for line in endurance)
    assert not any("Substitute recovery" in line for line in endurance)

    hard = _red_plan_lines(
        [
            _bike_workout(
                workout_type="bike_vo2",
                intensity_target="105-110% FTP",
                structured_workout=_HARD_VO2_STRUCTURED,
            )
        ],
    )
    assert hard == ["Substitute recovery, mobility, or rest."]


@pytest.mark.parametrize(
    ("workout_type", "expected", "forbidden"),
    [
        ("strength_maintenance", "submaximal", "% FTP"),
        ("mobility", "gentle", "intervals"),
        ("walk", "conversational", "Sweet Spot"),
    ],
)
def test_amber_plan_wording_matches_the_non_bike_session(
    workout_type: str, expected: str, forbidden: str
) -> None:
    workout = _bike_workout(
        workout_type=workout_type,
        intensity_target=None,
        structured_workout={},
    )
    amber = replace(grade(GradingInputs(subject_date=date(2026, 7, 21), acute={})), status="Amber")

    guidance = " ".join(
        graded_plan_adjustments(amber, [workout], is_rest_day=False, acute={}, has_vo2=False)
    )

    assert expected in guidance
    assert forbidden not in guidance


def test_red_ride_adjustment_is_none_without_a_ride() -> None:
    strength = _bike_workout(
        workout_type="strength_maintenance",
        intensity_target=None,
        structured_workout={},
    )
    assert _red_ride_adjustment([]) is None  # no ride today
    assert _red_ride_adjustment([strength]) is None


def test_build_today_actions_quotes_the_deterministic_adjustment() -> None:
    """The eased-ride action detail quotes verdict.verdictAdjustment, so the home
    card and the narrative show one set of numbers (Batch 173.2/173.3)."""
    ride = _bike_workout(
        workout_type="bike_endurance",
        intensity_target="64-70% FTP",
        structured_workout=_ENDURANCE_STRUCTURED,
    )
    packet = _red_ride_adjustment([ride])
    actions = build_today_actions(
        verdict={"status": "Red", "verdictAdjustment": packet},
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
    verdict = {
        "status": "Amber",
        "swapSuggestion": _swap_packet(),
        "verdictAdjustment": {"graded": True, "adjustedWorkPowerPct": 94},
    }
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


# ---------------------------------------------------------------------------
# Batch 225 — VO2 max reaches the two morning-brief consumers
# ---------------------------------------------------------------------------

_AGE_57_KB = {"profile": {"age": 57, "sex": "male"}}


def test_age_comparison_carries_a_vo2max_row_from_the_resolved_reading() -> None:
    """The silent half of the defect: ``ageComparison`` has carried no ``vo2max``
    key at all since July, because ``build_age_comparison`` drops a row for any
    metric handed to it as ``None`` and the wake row's column is always null."""
    morning_row = DailyMetric(
        user_id=uuid.uuid4(),
        calendar_date=date(2026, 8, 25),
        phase=DAILY_METRIC_PHASE_MORNING,
        resting_heart_rate_bpm=45,
        hrv_weekly_avg_ms=51,
        vo2max=None,
    )

    packet = _age_comparison(morning_row, None, _AGE_57_KB, vo2max=55.5)

    row = next(r for r in packet["rows"] if r["metricKey"] == "vo2max")
    assert row["value"] == pytest.approx(55.5)
    assert row["ageBand"] == "50–59"


def test_age_comparison_without_a_resolved_reading_is_unchanged() -> None:
    """No reading inside the 90-day window is still an honestly absent row, not
    a zero — the pre-Batch-225 behaviour for a genuinely empty history."""
    morning_row = DailyMetric(
        user_id=uuid.uuid4(),
        calendar_date=date(2026, 8, 25),
        phase=DAILY_METRIC_PHASE_MORNING,
        resting_heart_rate_bpm=45,
        vo2max=None,
    )

    packet = _age_comparison(morning_row, None, _AGE_57_KB, vo2max=None)

    assert [r["metricKey"] for r in packet["rows"]] == ["resting_heart_rate_bpm"]


def test_daily_metric_packet_carries_the_resolved_vo2max_with_its_date() -> None:
    """A carried-forward figure is never presented without the day it was
    measured — the convention ``athleteProfile.vo2maxAsOfDate`` already uses."""
    row = DailyMetric(
        user_id=uuid.uuid4(),
        calendar_date=date(2026, 8, 25),
        phase=DAILY_METRIC_PHASE_MORNING,
        vo2max=None,
    )

    packet = _daily_metric_packet(row, vo2max=55.5, vo2max_as_of_date=date(2026, 8, 22))

    assert packet is not None
    assert packet["vo2max"] == pytest.approx(55.5)
    assert packet["vo2maxAsOfDate"] == "2026-08-22"


def test_daily_metric_packet_prefers_the_rows_own_vo2max() -> None:
    """A settled row read back historically holds the reading for *its* date, so
    the carried value must not overwrite it."""
    row = DailyMetric(
        user_id=uuid.uuid4(),
        calendar_date=date(2026, 8, 22),
        phase=DAILY_METRIC_PHASE_SETTLED,
        vo2max=55.5,
    )

    packet = _daily_metric_packet(row, vo2max=48.0, vo2max_as_of_date=date(2026, 5, 1))

    assert packet is not None
    assert packet["vo2max"] == pytest.approx(55.5)
    assert packet["vo2maxAsOfDate"] == "2026-08-22"


def test_daily_metric_packet_states_no_vo2max_rather_than_a_bare_null() -> None:
    """No row value and nothing resolvable — both fields null together, so the
    packet never carries a date for a reading it does not have."""
    row = DailyMetric(
        user_id=uuid.uuid4(),
        calendar_date=date(2026, 8, 25),
        phase=DAILY_METRIC_PHASE_MORNING,
        vo2max=None,
    )

    packet = _daily_metric_packet(row)

    assert packet is not None
    assert packet["vo2max"] is None
    assert packet["vo2maxAsOfDate"] is None


# ---------------------------------------------------------------------------
# Batch 226 — the closed day's cost meets the baseline that describes it
# ---------------------------------------------------------------------------


def _closed_day_row(*, drained: int, stress: float, end: int) -> DailyMetric:
    """A settled row whose Garmin source window covers the whole local day."""
    return DailyMetric(
        user_id=uuid.uuid4(),
        calendar_date=date(2026, 8, 24),
        phase=DAILY_METRIC_PHASE_SETTLED,
        body_battery_drained=drained,
        body_battery_end=end,
        stress_avg=stress,
        raw_payload=_daily_aggregate_raw(date(2026, 8, 24), "2026-08-25T00:00:00.0"),
    )


def _drain_baseline() -> MetricBaseline:
    """Mark's live baseline as stored on 2026-08-25 (n=83 over 84 nights)."""
    return MetricBaseline(
        user_id=uuid.uuid4(),
        metric_key="body_battery_drain",
        metric_label="Body Battery drain",
        source="db_history",
        window_start_date=date(2026, 5, 29),
        window_end_date=date(2026, 8, 20),
        sample_count=83,
        excluded_sample_count=0,
        mean_value=64.58,
        median_value=67.0,
        lower_quartile_value=57.5,
        upper_quartile_value=75.0,
    )


def test_complete_yesterday_drain_carries_its_baseline_and_delta() -> None:
    """Mark's report: the figure reaches the read, the comparison never does.

    The 2026-08-25 packet held `bodyBatteryDrained: 66` beside a stored median of
    67 and nothing joined them.
    """
    packet = _yesterday_load_packet(
        [],
        [],
        DayAggregates.from_metric(_closed_day_row(drained=66, stress=24.0, end=35)),
        [_drain_baseline()],
    )["wholeDayCost"]

    assert packet["bodyBatteryDrained"] == 66
    drain = packet["baselines"]["bodyBatteryDrained"]
    assert drain["baselineMedian"] == 67.0
    assert drain["deltaVsBaseline"] == pytest.approx(-1.0)
    assert drain["lowerQuartile"] == 57.5
    assert drain["upperQuartile"] == 75.0
    assert drain["sampleCount"] == 83
    assert "unavailableReason" not in drain


def test_a_figure_with_no_stored_baseline_says_so_rather_than_comparing() -> None:
    """226.4: production holds no `stress_avg` baseline at all, so all-day stress
    must state the absence instead of arriving as an unanchored number."""
    packet = _yesterday_load_packet(
        [],
        [],
        DayAggregates.from_metric(_closed_day_row(drained=66, stress=24.0, end=35)),
        [_drain_baseline()],
    )["wholeDayCost"]

    stress = packet["baselines"]["allDayStressAvg"]
    assert stress["metricKey"] == "stress_avg"
    assert "has not computed a personal baseline" in stress["unavailableReason"]
    assert "baselineMedian" not in stress
    # The same rule covers the third figure, which also has no baseline.
    assert "unavailableReason" in packet["baselines"]["bodyBatteryEnd"]


def test_an_incomplete_yesterday_emits_neither_a_number_nor_a_comparison() -> None:
    """A part-day Garmin window already gates the value to None upstream; the
    comparison must not appear on its own."""
    partial = DailyMetric(
        user_id=uuid.uuid4(),
        calendar_date=date(2026, 8, 24),
        phase=DAILY_METRIC_PHASE_SETTLED,
        body_battery_drained=10,
        body_battery_end=90,
        stress_avg=14.0,
        raw_payload=_daily_aggregate_raw(date(2026, 8, 24), "2026-08-24T08:44:00.0"),
    )

    packet = _yesterday_load_packet(
        [], [], DayAggregates.from_metric(partial), [_drain_baseline()]
    )["wholeDayCost"]

    assert packet["bodyBatteryDrained"] is None
    assert packet["baselines"] == {}


def test_absent_yesterday_row_emits_no_comparison() -> None:
    packet = _yesterday_load_packet([], [], None, [_drain_baseline()])["wholeDayCost"]

    assert packet["baselines"] == {}
    assert packet["coverage"]["status"] == "unknown"


def test_morning_metrics_table_drain_row_is_untouched_by_batch_226() -> None:
    """226.1: Batch 224's withhold must survive byte-for-byte. A morning-window
    drain is still never compared against the full-day baseline."""
    morning_row = DailyMetric(
        user_id=uuid.uuid4(),
        calendar_date=date(2026, 8, 25),
        phase=DAILY_METRIC_PHASE_MORNING,
        body_battery_drained=10,
        raw_payload=_daily_aggregate_raw(date(2026, 8, 25), "2026-08-25T07:53:00.0"),
    )

    rows = _metrics_vs_baselines(morning_row, None, [_drain_baseline()], None, day_aggregates=None)

    drain = next(r for r in rows if r["metricKey"] == "body_battery_drain")
    assert drain["currentValue"] is None
    assert "still a part-day value" in drain["unavailableReason"]
    assert drain["lowerQuartile"] == 57.5
    assert drain["upperQuartile"] == 75.0
