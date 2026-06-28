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
    Analysis,
    DailyMetric,
    ManualEntry,
    MetricBaseline,
    PlannedWorkout,
    Sleep,
    TemperatureReading,
    WeatherDaily,
)
from src.models.profile import Profile, UserRole
from src.services.morning_analysis import (
    PROMPT_VERSION,
    ClaudeGenerationResult,
    MorningAnalysisService,
    _daily_metric_packet,
    _morning_verdict,
    _training_and_activity_fields,
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
                "**Sleep summary:** age-adjusted sleep clears the green line.\n\n"
                "- **Verdict:** Green, with readiness treated as load-driven."
            ),
            raw_response={
                "id": "msg_test",
                "model": "claude-test",
                "content": [{"type": "text", "text": "ok"}],
                "contextVerdict": context_packet["verdict"]["status"],
            },
            model_name="claude-test",
        )


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
            pin_hash="x" * 60,
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
                    score=71,
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
        assert packet["sleep"]["ageAdjustedScore"] == 75
        assert packet["verdict"]["status"] == "Green"
        assert packet["verdict"]["readinessInterpretation"] == "load_driven"
        assert packet["verdict"]["hasVo2WorkoutToday"] is True
        assert packet["environment"]["thermalReview"]["flags"] == [
            "thermal_disruption_likely",
            "precool_target_missed",
            "wind_disruption_watch",
        ]
        assert packet["metricsVsBaselines"][0]["deltaVsBaseline"] == 1.0
        assert any(
            rule["id"] == "no_lr_balance"
            for rule in packet["knowledgeBase"]["dataQualityGuardrails"]
        )
        assert "leftRightBalance" not in json.dumps(packet)

        stored = await session.scalar(select(Analysis).where(Analysis.id == result.analysis.id))
        assert stored is not None
        assert stored.prompt_version == PROMPT_VERSION
        assert stored.model_name == "claude-test"
        assert stored.verdict == "Green"
        assert stored.output_markdown.startswith("**Sleep summary:**")

        second = await service.generate_and_store(player, subject_date, client=fake_client)
        assert second.generated is False
        assert second.analysis.id == result.analysis.id
        assert fake_client.calls == 1


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
