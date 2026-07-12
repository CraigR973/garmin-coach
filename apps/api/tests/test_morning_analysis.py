from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime
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
    PlannedWorkout,
    Sleep,
    TemperatureReading,
    WeatherDaily,
)
from src.models.profile import Profile, UserRole
from src.services.morning_analysis import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    ClaudeGenerationResult,
    MorningAnalysisError,
    MorningAnalysisService,
    _daily_metric_packet,
    _date_label,
    _manual_entry_packet,
    _morning_verdict,
    _sleep_packet,
    _thermal_action,
    _training_and_activity_fields,
    _yesterday_load_packet,
    build_morning_user_prompt,
    build_today_actions,
    subjective_score_label,
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
                    sleep_start_utc=datetime(2026, 1, 1, 0, 17),
                    sleep_end_utc=datetime(2026, 1, 1, 7, 31),
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
        assert packet["sleep"]["ageAdjustedScore"] == 71
        # Batch 91: local wall-clock bed/wake alongside the *Utc fields. Jan 1 is
        # GMT so the local clock equals the UTC clock (proves the wiring; the BST
        # offset is covered in the pure _sleep_packet test).
        assert packet["sleep"]["sleepStartUtc"] == "2026-01-01T00:17:00Z"
        assert packet["sleep"]["sleepStartLocal"] == "00:17"
        assert packet["sleep"]["sleepEndLocal"] == "07:31"
        # Authoritative header date and the check-in spoken as Mark's word.
        assert packet["subjectDateLabel"] == "Thursday 1 January 2026"
        assert packet["manualEntries"][0]["subjectiveLabel"] == "OK"
        assert packet["verdict"]["subjectiveLabel"] == "OK"
        assert packet["verdict"]["status"] == "Amber"
        assert packet["verdict"]["readinessInterpretation"] is None
        assert packet["verdict"]["hasVo2WorkoutToday"] is True
        assert packet["environment"]["thermalReview"]["flags"] == [
            "thermal_disruption_likely",
            "precool_target_missed",
            "wind_disruption_watch",
        ]
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
            pin_hash="x" * 60,
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
    assert PROMPT_VERSION.startswith("morning-analysis-v11")
    assert "Your question" in SYSTEM_PROMPT
    assert "answer it" in SYSTEM_PROMPT.lower()

    packet = {
        "manualEntries": [
            {"notes": "Why am I so tired even though I slept 8 hours?", "subjectiveScore": 4}
        ],
        "verdict": {"status": "Amber"},
    }
    prompt = build_morning_user_prompt(packet)
    assert "Why am I so tired" in prompt


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
    # normalize wrapped whitespace so the assertions are line-break agnostic
    normalized = " ".join(SYSTEM_PROMPT.lower().split())
    assert "never print a `*utc` timestamp" in normalized
    assert "never surface the raw subjectivescore number" in normalized


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
        manual_entries=[],
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
        manual_entries=[],
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
        manual_entries=[],
        planned_workouts=[],
        baselines={"resting_heart_rate_bpm": _rhr_baseline(user_id)},
    )

    assert verdict["status"] == "Amber"
    assert verdict["softSleepRecoveryOverride"] is False


def test_soft_sleep_override_uses_personal_readiness_floor_not_generic_70() -> None:
    # Mark's real 2026-07-05: soft sleep (72) + Moderate readiness 66 (below the old
    # generic >=70 gate) but above his personal readiness median (53.5), with clean
    # HRV and resting HR in band -> stays Green under the #133 personal floor.
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
        manual_entries=[],
        planned_workouts=[],
        baselines={
            "resting_heart_rate_bpm": _rhr_baseline(user_id),
            "readiness_score": _readiness_baseline(user_id),
        },
    )

    assert verdict["status"] == "Green"
    assert verdict["softSleepRecoveryOverride"] is True


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
        manual_entries=[],
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
    assert packet["totalTrainingLoad"] == 165
    assert packet["hardestActivity"]["name"] == "VO2 Max 30/15"
    assert packet["postSessionAnalyses"][0]["analysisType"] == "post_workout"
    assert "hard session" in packet["postSessionAnalyses"][0]["summary"]


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
    assert thermal["href"] == "/sleep"
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
