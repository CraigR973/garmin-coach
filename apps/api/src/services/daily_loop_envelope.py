"""Assemble the ``/api/v1/daily-loop`` envelope (Batch 251, CR236-09).

``routers/daily_loop.py`` was 1,747 lines holding 45 DTOs, a 261-line ``build_envelope``,
a Dreo fan client wrapper and a background generation task — around **four** routes.
Two concrete defects followed from one file owning transport, serialization,
orchestration and a device client: ``build_envelope`` performs a write and a commit
because it was the only place that saw the assembled suggestion, and the background
task's need for input sync forced a router to import a private scheduler helper.

The background task went to ``services/morning_pipeline`` (CR236-02). Everything
that turns stored rows into the envelope lives here, where the REM-assignment write
has a testable home that is not a serializer inside a router. The fan helpers come
too: they build ``FanStateOut`` from a ``DreoFanClient`` snapshot, so they are
serialization — the device client itself already lives in ``services/dreo_fan``.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import CurrentUser
from src.config import settings
from src.models.coaching import (
    Analysis,
    BriefGenerationStatus,
    DailyMetric,
    Feedback,
    ManualEntry,
    PlannedWorkout,
    Sleep,
)
from src.routers.daily_loop_schemas import (
    ActiveHolidayWindowOut,
    AnalysisOut,
    ApiMeta,
    BreathworkBriefOut,
    BreathworkSessionOut,
    BreathworkWindowStatsOut,
    BriefGenerationStatusOut,
    ChronicSuggestionsOut,
    DailyLoopData,
    DailyLoopEnvelope,
    DailyMetricOut,
    DataQualityWarningOut,
    DeliveryStateOut,
    FanStateOut,
    HolidayStateOut,
    LoopStateOut,
    ManualEntryOut,
    PendingPostActivityOut,
    PlannedWorkoutOut,
    PostFlexibilityAnalysisOut,
    PostStrengthAnalysisOut,
    PostWalkAnalysisOut,
    PostWorkoutAnalysisOut,
    RemInterventionCheckInOut,
    SleepOut,
    SleepProjectionOut,
    StrengthBriefOut,
    StrengthSessionOut,
    ThermalStateOut,
    WalkingBriefOut,
    WalkingSessionOut,
    WalkingWindowStatsOut,
    WindowStatsOut,
)
from src.routers.feedback import serialize_feedback
from src.services.breathwork_brief import BreathworkBriefResult
from src.services.brief_generation_status import (
    STATUS_FAILED,
    STATUS_GENERATING,
    BriefGenerationStatusService,
)
from src.services.chronic_patterns import ChronicPatternSuggestionService
from src.services.daily_loop import DeliveryState
from src.services.dreo_fan import (
    DreoConnectionError,
    DreoCredentialsError,
    DreoFanClient,
    DreoFanError,
)
from src.services.environment_freshness import is_hive_temperature_fresh
from src.services.experiment_loop import ExperimentLoopService, rotation_from_assignment
from src.services.fan_control import describe_fan_intent
from src.services.morning_verdict import MEDICAL_BOUNDARY_STANDING_LINE
from src.services.post_activity_analysis import (
    post_activity_kind,
)
from src.services.sleep_projection import SleepProjectionResult
from src.services.sleep_projection_context import SleepProjectionContextService
from src.services.strength_brief import StrengthBriefResult
from src.services.walking_brief import WalkingBriefResult
from src.services.workout_categories import (
    DAY_CATEGORY_CYCLE,
    DAY_CATEGORY_FLEXIBILITY,
    DAY_CATEGORY_WEIGHTS,
    category_for_workout_type,
)

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


def _generated_at() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")


def _local_time(timezone_name: str) -> time:
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        zone = ZoneInfo("UTC")
    return datetime.now(zone).time()


def local_today(timezone_name: str) -> date:
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        zone = ZoneInfo("UTC")
    return datetime.now(zone).date()


def _fallback_fans(
    *,
    auto_enabled: bool,
    timezone_name: str,
    fresh_temperature_c: float | None,
) -> list[FanStateOut]:
    intent = describe_fan_intent(
        _local_time(timezone_name), fresh_temperature_c, auto_enabled=auto_enabled
    )
    return [
        FanStateOut(
            id="default",
            label="Bedroom fan",
            model=None,
            autoEnabled=intent.auto_enabled,
            autoTarget=True,
            mode=intent.mode,
            isOn=intent.is_on,
            speed=intent.speed,
            oscillating=None,
            presetMode=None,
            respondingToC=intent.responding_to_c,
            nextOnLocalTime=intent.next_on_local_time,
        )
    ]


def _read_fans(
    *,
    auto_enabled: bool,
    timezone_name: str,
    fresh_temperature_c: float | None,
) -> list[FanStateOut]:
    client = DreoFanClient()
    try:
        client.connect()
        intent = describe_fan_intent(
            _local_time(timezone_name), fresh_temperature_c, auto_enabled=auto_enabled
        )
        fans: list[FanStateOut] = []
        for snapshot in client.read_all_states():
            is_auto_target = snapshot.info.auto_target
            fans.append(
                FanStateOut(
                    id=snapshot.info.fan_id,
                    label=snapshot.info.label,
                    model=snapshot.info.model,
                    autoEnabled=(intent.auto_enabled if is_auto_target else False),
                    autoTarget=is_auto_target,
                    mode=(intent.mode if is_auto_target else "manual"),
                    isOn=(intent.is_on if is_auto_target else snapshot.state.is_on),
                    speed=(intent.speed if is_auto_target else snapshot.state.fan_speed),
                    oscillating=snapshot.state.oscillating,
                    presetMode=snapshot.state.preset_mode,
                    respondingToC=(intent.responding_to_c if is_auto_target else None),
                    nextOnLocalTime=(intent.next_on_local_time if is_auto_target else None),
                )
            )
        return fans or _fallback_fans(
            auto_enabled=auto_enabled,
            timezone_name=timezone_name,
            fresh_temperature_c=fresh_temperature_c,
        )
    finally:
        client.close()


def _serialize_manual_entry(entry: ManualEntry | None) -> ManualEntryOut | None:
    if entry is None:
        return None
    return ManualEntryOut(
        id=str(entry.id),
        userId=str(entry.user_id),
        plannedWorkoutId=str(entry.planned_workout_id) if entry.planned_workout_id else None,
        activityId=str(entry.activity_id) if entry.activity_id else None,
        plannedWorkoutVersion=entry.planned_workout_version,
        entryDate=entry.entry_date.isoformat(),
        entryAtUtc=_dt(entry.entry_at_utc) or "",
        bpSystolic=entry.bp_systolic,
        bpDiastolic=entry.bp_diastolic,
        subjectiveScore=entry.subjective_score,
        rpe=entry.rpe,
        feel=entry.feel,
        adherenceStatus=entry.adherence_status,
        actualWorkoutJson=entry.actual_workout_json,
        supplementsJson=entry.supplements_json,
        foodJson=entry.food_json,
        sleepSetupJson=entry.sleep_setup_json,
        remInterventionFeedbackJson=(entry.rem_intervention_feedback_json or None),
        notes=entry.notes,
    )


def _normalize_api_verdict(verdict: str | None) -> str | None:
    if not verdict:
        return None
    return verdict.strip().lower()


def _serialize_analysis(
    analysis: Analysis | None, feedback: Feedback | None = None
) -> AnalysisOut | None:
    if analysis is None:
        return None
    verdict = (
        analysis.context_packet.get("verdict", {})
        if isinstance(analysis.context_packet, dict)
        else {}
    )
    environment = (
        analysis.context_packet.get("environment", {})
        if isinstance(analysis.context_packet, dict)
        else {}
    )
    thermal_review = environment.get("thermalReview", {}) if isinstance(environment, dict) else {}
    metrics_vs_baselines = (
        analysis.context_packet.get("metricsVsBaselines", [])
        if isinstance(analysis.context_packet, dict)
        else []
    )
    age_comparison = (
        analysis.context_packet.get("ageComparison", {})
        if isinstance(analysis.context_packet, dict)
        else {}
    )
    acute_physiology = verdict.get("acutePhysiology", {}) if isinstance(verdict, dict) else {}
    if not isinstance(acute_physiology, dict):
        acute_physiology = {}
    # The standing boundary is a product invariant, including for a stored
    # pre-Batch-246 analysis during the narrow deploy/regeneration window.
    acute_physiology = {
        **acute_physiology,
        "standingLine": MEDICAL_BOUNDARY_STANDING_LINE,
    }
    return AnalysisOut(
        id=str(analysis.id),
        generatedAtUtc=_dt(analysis.generated_at_utc) or "",
        verdict=_normalize_api_verdict(analysis.verdict),
        promptVersion=analysis.prompt_version,
        modelName=analysis.model_name,
        outputMarkdown=analysis.output_markdown,
        planAdjustments=(verdict.get("planAdjustments", []) if isinstance(verdict, dict) else []),
        reasons=verdict.get("reasons", []) if isinstance(verdict, dict) else [],
        readinessInterpretation=verdict.get("readinessInterpretation")
        if isinstance(verdict, dict)
        else None,
        thermalReview=thermal_review if isinstance(thermal_review, dict) else {},
        metricsVsBaselines=metrics_vs_baselines if isinstance(metrics_vs_baselines, list) else [],
        ageComparison=age_comparison if isinstance(age_comparison, dict) else {},
        swapSuggestion=(
            verdict.get("swapSuggestion")
            if isinstance(verdict, dict) and isinstance(verdict.get("swapSuggestion"), dict)
            else None
        ),
        weeklyMix=(
            verdict.get("weeklyMix")
            if isinstance(verdict, dict) and isinstance(verdict.get("weeklyMix"), dict)
            else None
        ),
        todayActions=(
            verdict.get("todayActions", [])
            if isinstance(verdict, dict) and isinstance(verdict.get("todayActions"), list)
            else []
        ),
        acutePhysiology=acute_physiology,
        feedback=serialize_feedback(feedback) if feedback is not None else None,
    )


def _serialize_post_workout_analysis(
    analysis: Analysis,
    post_ride_checkin: ManualEntry | None,
    feedback: Feedback | None = None,
) -> PostWorkoutAnalysisOut:
    packet = analysis.context_packet if isinstance(analysis.context_packet, dict) else {}
    activity = packet.get("activity", {}) if isinstance(packet.get("activity", {}), dict) else {}
    recovery_decision = (
        packet.get("recoveryDecision", {})
        if isinstance(packet.get("recoveryDecision", {}), dict)
        else {}
    )
    time_series_summary = (
        packet.get("timeSeriesSummary", {})
        if isinstance(packet.get("timeSeriesSummary", {}), dict)
        else {}
    )
    raw_intervals = packet.get("intervals")
    intervals = (
        [item for item in raw_intervals if isinstance(item, dict)]
        if isinstance(raw_intervals, list)
        else []
    )
    execution = packet.get("execution")
    execution = execution if isinstance(execution, dict) else {}
    tomorrow_impact = packet.get("tomorrowImpact")
    return PostWorkoutAnalysisOut(
        id=str(analysis.id),
        activityId=str(analysis.activity_id) if analysis.activity_id else None,
        plannedWorkoutId=(
            str(analysis.planned_workout_id) if analysis.planned_workout_id else None
        ),
        activityName=(
            activity.get("activityName") if isinstance(activity.get("activityName"), str) else None
        ),
        activityType=(
            activity.get("activityType") if isinstance(activity.get("activityType"), str) else None
        ),
        generatedAtUtc=_dt(analysis.generated_at_utc) or "",
        promptVersion=analysis.prompt_version,
        modelName=analysis.model_name,
        outputMarkdown=analysis.output_markdown,
        recoveryDecision=recovery_decision,
        timeSeriesSummary=time_series_summary,
        intervals=intervals,
        execution=execution,
        tomorrowImpact=tomorrow_impact if isinstance(tomorrow_impact, str) else None,
        postRideCheckIn=_serialize_manual_entry(post_ride_checkin),
        feedback=serialize_feedback(feedback) if feedback is not None else None,
    )


def _serialize_post_flexibility_analysis(
    analysis: Analysis,
    activity_checkin: ManualEntry | None,
    feedback: Feedback | None = None,
) -> PostFlexibilityAnalysisOut:
    packet = analysis.context_packet if isinstance(analysis.context_packet, dict) else {}
    activity = packet.get("activity", {}) if isinstance(packet.get("activity", {}), dict) else {}
    heart_rate_review = (
        packet.get("heartRateReview", {})
        if isinstance(packet.get("heartRateReview", {}), dict)
        else {}
    )
    consistency = (
        packet.get("consistency", {}) if isinstance(packet.get("consistency", {}), dict) else {}
    )
    return PostFlexibilityAnalysisOut(
        id=str(analysis.id),
        activityId=str(analysis.activity_id) if analysis.activity_id else None,
        activityName=(
            activity.get("activityName") if isinstance(activity.get("activityName"), str) else None
        ),
        activityType=(
            activity.get("activityType") if isinstance(activity.get("activityType"), str) else None
        ),
        generatedAtUtc=_dt(analysis.generated_at_utc) or "",
        promptVersion=analysis.prompt_version,
        modelName=analysis.model_name,
        outputMarkdown=analysis.output_markdown,
        heartRateReview=heart_rate_review,
        consistency=consistency,
        activityCheckIn=_serialize_manual_entry(activity_checkin),
        feedback=serialize_feedback(feedback) if feedback is not None else None,
    )


def _serialize_post_strength_analysis(
    analysis: Analysis,
    activity_checkin: ManualEntry | None,
    feedback: Feedback | None = None,
) -> PostStrengthAnalysisOut:
    packet = analysis.context_packet if isinstance(analysis.context_packet, dict) else {}
    activity = packet.get("activity", {}) if isinstance(packet.get("activity", {}), dict) else {}
    heart_rate_review = (
        packet.get("heartRateReview", {})
        if isinstance(packet.get("heartRateReview", {}), dict)
        else {}
    )
    consistency = (
        packet.get("consistency", {}) if isinstance(packet.get("consistency", {}), dict) else {}
    )
    return PostStrengthAnalysisOut(
        id=str(analysis.id),
        activityId=str(analysis.activity_id) if analysis.activity_id else None,
        activityName=(
            activity.get("activityName") if isinstance(activity.get("activityName"), str) else None
        ),
        activityType=(
            activity.get("activityType") if isinstance(activity.get("activityType"), str) else None
        ),
        generatedAtUtc=_dt(analysis.generated_at_utc) or "",
        promptVersion=analysis.prompt_version,
        modelName=analysis.model_name,
        outputMarkdown=analysis.output_markdown,
        heartRateReview=heart_rate_review,
        consistency=consistency,
        activityCheckIn=_serialize_manual_entry(activity_checkin),
        feedback=serialize_feedback(feedback) if feedback is not None else None,
    )


def _serialize_post_walk_analysis(
    analysis: Analysis,
    activity_checkin: ManualEntry | None,
    feedback: Feedback | None = None,
) -> PostWalkAnalysisOut:
    packet = analysis.context_packet if isinstance(analysis.context_packet, dict) else {}
    activity = packet.get("activity", {}) if isinstance(packet.get("activity", {}), dict) else {}
    heart_rate_review = (
        packet.get("heartRateReview", {})
        if isinstance(packet.get("heartRateReview", {}), dict)
        else {}
    )
    pace_review = (
        packet.get("paceReview", {}) if isinstance(packet.get("paceReview", {}), dict) else {}
    )
    active_recovery = (
        packet.get("activeRecoveryContext", {})
        if isinstance(packet.get("activeRecoveryContext", {}), dict)
        else {}
    )
    return PostWalkAnalysisOut(
        id=str(analysis.id),
        activityId=str(analysis.activity_id) if analysis.activity_id else None,
        activityName=(
            activity.get("activityName") if isinstance(activity.get("activityName"), str) else None
        ),
        activityType=(
            activity.get("activityType") if isinstance(activity.get("activityType"), str) else None
        ),
        generatedAtUtc=_dt(analysis.generated_at_utc) or "",
        promptVersion=analysis.prompt_version,
        modelName=analysis.model_name,
        outputMarkdown=analysis.output_markdown,
        heartRateReview=heart_rate_review,
        paceReview=pace_review,
        activeRecoveryContext=active_recovery,
        activityCheckIn=_serialize_manual_entry(activity_checkin),
        feedback=serialize_feedback(feedback) if feedback is not None else None,
    )


def _serialize_daily_metric(metric: DailyMetric | None) -> DailyMetricOut | None:
    if metric is None:
        return None
    return DailyMetricOut(
        id=str(metric.id),
        userId=str(metric.user_id),
        calendarDate=metric.calendar_date.isoformat(),
        recordedAtUtc=_dt(metric.recorded_at_utc),
        readinessScore=metric.readiness_score,
        readinessLevel=metric.readiness_level,
        readinessSleepScore=metric.readiness_sleep_score,
        recoveryTimeMin=metric.recovery_time_min,
        acuteLoad=metric.acute_load,
        trainingStatus=metric.training_status,
        hrvLastNightAvgMs=metric.hrv_last_night_avg_ms,
        hrvWeeklyAvgMs=metric.hrv_weekly_avg_ms,
        hrvStatus=metric.hrv_status,
        hrvBaselineLowMs=metric.hrv_baseline_low_ms,
        hrvBaselineHighMs=metric.hrv_baseline_high_ms,
        restingHeartRateBpm=metric.resting_heart_rate_bpm,
        stressAvg=metric.stress_avg,
        bodyBatteryCharged=metric.body_battery_charged,
        bodyBatteryDrained=metric.body_battery_drained,
        bodyBatteryEnd=metric.body_battery_end,
        weightKg=metric.weight_kg,
        vo2max=metric.vo2max,
    )


def _serialize_sleep(sleep: Sleep | None) -> SleepOut | None:
    if sleep is None:
        return None
    return SleepOut(
        id=str(sleep.id),
        userId=str(sleep.user_id),
        calendarDate=sleep.calendar_date.isoformat(),
        sleepStartUtc=_dt(sleep.sleep_start_utc),
        sleepEndUtc=_dt(sleep.sleep_end_utc),
        score=sleep.score,
        ageAdjustedScore=sleep.age_adjusted_score,
        qualifier=sleep.qualifier,
        durationSec=sleep.duration_sec,
        deepSleepSec=sleep.deep_sleep_sec,
        lightSleepSec=sleep.light_sleep_sec,
        remSleepSec=sleep.rem_sleep_sec,
        awakeSleepSec=sleep.awake_sleep_sec,
        unmeasurableSleepSec=sleep.unmeasurable_sleep_sec,
        averageSpo2Pct=sleep.average_spo2_pct,
        lowestSpo2Pct=sleep.lowest_spo2_pct,
        averageRespiration=sleep.average_respiration,
        restingHeartRateBpm=sleep.resting_heart_rate_bpm,
        avgOvernightHrvMs=sleep.avg_overnight_hrv_ms,
        hrvStatus=sleep.hrv_status,
        avgSleepStress=sleep.avg_sleep_stress,
        restlessMomentsCount=sleep.restless_moments_count,
        bodyBatteryChange=sleep.body_battery_change,
        factorsJson=sleep.factors_json,
    )


def _serialize_delivery(state: DeliveryState | None) -> DeliveryStateOut | None:
    if state is None:
        return None
    return DeliveryStateOut(
        liveStatus=state.live_status,
        liveOrigin=state.live_origin,
        intervalsEventId=state.intervals_event_id,
        changed=state.changed,
        adjustment=state.adjustment,
    )


def _serialize_planned_workout(
    workout: PlannedWorkout,
    adherence: ManualEntry | None,
    delivery: DeliveryState | None = None,
) -> PlannedWorkoutOut:
    return PlannedWorkoutOut(
        id=str(workout.id),
        userId=str(workout.user_id),
        planBlockId=str(workout.plan_block_id) if workout.plan_block_id else None,
        workoutDate=workout.workout_date.isoformat(),
        version=workout.version,
        title=workout.title,
        workoutType=workout.workout_type,
        status=workout.status,
        isActive=workout.is_active,
        plannedDurationMin=workout.planned_duration_min,
        intensityTarget=workout.intensity_target,
        structuredWorkout=workout.structured_workout,
        source=workout.source,
        adherence=_serialize_manual_entry(adherence),
        delivery=_serialize_delivery(delivery),
    )


def _serialize_strength_brief(result: StrengthBriefResult) -> StrengthBriefOut:
    return StrengthBriefOut(
        asOfDate=result.as_of_date.isoformat(),
        window4w=WindowStatsOut(
            sessionCount=result.window_4w.session_count,
            totalDurationMin=result.window_4w.total_duration_min,
            totalLoadProxy=result.window_4w.total_load_proxy,
            sessionsPerWeek=result.window_4w.sessions_per_week,
        ),
        window12w=WindowStatsOut(
            sessionCount=result.window_12w.session_count,
            totalDurationMin=result.window_12w.total_duration_min,
            totalLoadProxy=result.window_12w.total_load_proxy,
            sessionsPerWeek=result.window_12w.sessions_per_week,
        ),
        recentSessions=[
            StrengthSessionOut(
                activityId=str(s.activity_id),
                activityName=s.activity_name,
                activityType=s.activity_type,
                sessionDate=s.session_date.isoformat(),
                durationMin=s.duration_min,
                trainingLoad=s.training_load,
            )
            for s in result.recent_sessions
        ],
        trend=result.trend,
        trendReason=result.trend_reason,
    )


def _serialize_walking_brief(result: WalkingBriefResult) -> WalkingBriefOut:
    return WalkingBriefOut(
        asOfDate=result.as_of_date.isoformat(),
        window4w=WalkingWindowStatsOut(
            sessionCount=result.window_4w.session_count,
            totalDistanceM=result.window_4w.total_distance_m,
            totalDurationMin=result.window_4w.total_duration_min,
            sessionsPerWeek=result.window_4w.sessions_per_week,
        ),
        window12w=WalkingWindowStatsOut(
            sessionCount=result.window_12w.session_count,
            totalDistanceM=result.window_12w.total_distance_m,
            totalDurationMin=result.window_12w.total_duration_min,
            sessionsPerWeek=result.window_12w.sessions_per_week,
        ),
        recentSessions=[
            WalkingSessionOut(
                activityId=str(s.activity_id),
                activityName=s.activity_name,
                activityType=s.activity_type,
                sessionDate=s.session_date.isoformat(),
                durationMin=s.duration_min,
                distanceM=s.distance_m,
            )
            for s in result.recent_sessions
        ],
        trend=result.trend,
        trendReason=result.trend_reason,
    )


def _serialize_breathwork_brief(result: BreathworkBriefResult) -> BreathworkBriefOut:
    return BreathworkBriefOut(
        asOfDate=result.as_of_date.isoformat(),
        window4w=BreathworkWindowStatsOut(
            sessionCount=result.window_4w.session_count,
            totalDurationMin=result.window_4w.total_duration_min,
            sessionsPerWeek=result.window_4w.sessions_per_week,
        ),
        window12w=BreathworkWindowStatsOut(
            sessionCount=result.window_12w.session_count,
            totalDurationMin=result.window_12w.total_duration_min,
            sessionsPerWeek=result.window_12w.sessions_per_week,
        ),
        recentSessions=[
            BreathworkSessionOut(
                activityId=str(s.activity_id),
                activityName=s.activity_name,
                activityType=s.activity_type,
                sessionDate=s.session_date.isoformat(),
                durationMin=s.duration_min,
            )
            for s in result.recent_sessions
        ],
        trend=result.trend,
        trendReason=result.trend_reason,
    )


def _serialize_sleep_projection(result: SleepProjectionResult) -> SleepProjectionOut:
    return SleepProjectionOut(
        status=result.status,
        tone=result.tone,
        headline=result.headline,
        summary=result.summary,
        evidence=result.evidence,
        prepActions=result.prep_actions,
        protocol=result.protocol,
    )


#: Batch 144: classified ``reason`` for a ``generating`` row that was never flipped
#: to ready/failed by its background task — an orphaned generation (process restart
#: or a hung Anthropic call) resolved at read time rather than a clean failure.
STALE_GENERATING_REASON = "stale"


def _is_stale_generating(row: BriefGenerationStatus, *, now: datetime | None = None) -> bool:
    """Batch 144: has a ``generating`` row sat past the staleness threshold?

    ``updated_at`` is stamped on every ``mark_*`` (so it tracks when the row was
    last moved to ``generating``); a naive UTC datetime, matching ``now``.
    """
    current = now if now is not None else datetime.now(UTC).replace(tzinfo=None)
    threshold = timedelta(minutes=settings.brief_generation_stale_after_minutes)
    return current - row.updated_at > threshold


def _serialize_brief_generation(
    row: BriefGenerationStatus | None,
    *,
    has_analysis: bool,
    now: datetime | None = None,
) -> BriefGenerationStatusOut | None:
    """Batch 141: a real brief on the day is authoritative — a stale
    ``generating`` / ``failed`` row never overrides an analysis that exists.

    Batch 144: a ``generating`` row orphaned by a process restart or a hung
    Anthropic call is never flipped to ready/failed, so without this it reads
    ``generating`` forever (the 2026-07-21 endless-spinner class). Once it is older
    than the threshold, derive a retryable ``failed``/``stale`` state — read-time
    only, no writer/migration/scheduler (Decision #223)."""
    if has_analysis:
        return BriefGenerationStatusOut(status="ready", reason=None)
    if row is None:
        return None
    if row.status == STATUS_GENERATING and _is_stale_generating(row, now=now):
        return BriefGenerationStatusOut(status=STATUS_FAILED, reason=STALE_GENERATING_REASON)
    return BriefGenerationStatusOut(status=row.status, reason=row.reason)


async def build_envelope(player: CurrentUser, snapshot: Any, db: AsyncSession) -> DailyLoopEnvelope:
    """Turn one daily-loop snapshot into the envelope the app reads."""
    feedback_map = snapshot.feedback
    morning_analysis = _serialize_analysis(
        snapshot.morning_analysis,
        feedback_map.get(snapshot.morning_analysis.id) if snapshot.morning_analysis else None,
    )
    brief_generation = _serialize_brief_generation(
        await BriefGenerationStatusService(db).get(player.id, snapshot.subject_date),
        has_analysis=snapshot.morning_analysis is not None,
    )
    fresh_temperature = (
        snapshot.latest_temperature
        if is_hive_temperature_fresh(
            snapshot.latest_temperature.captured_at_utc if snapshot.latest_temperature else None
        )
        else None
    )
    planned_workouts = [
        _serialize_planned_workout(
            workout,
            snapshot.adherence_entries.get(workout.id),
            snapshot.deliveries.get(workout.id),
        )
        for workout in snapshot.planned_workouts
    ]
    analysed_activity_ids = {
        analysis.activity_id
        for analysis in (
            *snapshot.post_workout_analyses,
            *snapshot.post_flexibility_analyses,
            *snapshot.post_strength_analyses,
            *snapshot.post_walk_analyses,
        )
        if analysis.activity_id is not None
    }
    pending_post_activities = []
    claimed_pending_workouts: set[uuid.UUID] = set()
    for activity in snapshot.activities:
        kind = post_activity_kind(activity)
        if kind is None or activity.id in analysed_activity_ids:
            continue
        desired_category = {
            "ride": DAY_CATEGORY_CYCLE,
            "strength": DAY_CATEGORY_WEIGHTS,
            "flexibility": DAY_CATEGORY_FLEXIBILITY,
        }.get(kind)
        matched_workout = next(
            (
                workout
                for workout in snapshot.planned_workouts
                if desired_category is not None
                and workout.id not in claimed_pending_workouts
                and category_for_workout_type(workout.workout_type) == desired_category
                and workout.status != "skipped"
            ),
            None,
        )
        if matched_workout is not None:
            claimed_pending_workouts.add(matched_workout.id)
        pending_post_activities.append(
            PendingPostActivityOut(
                activityId=str(activity.id),
                activityName=activity.activity_name,
                activityType=activity.activity_type,
                activityKind=kind,
                plannedWorkoutId=(str(matched_workout.id) if matched_workout else None),
                startUtc=_dt(activity.start_utc) or "",
                durationMin=(round(activity.duration_sec / 60) if activity.duration_sec else None),
                checkIn=_serialize_manual_entry(snapshot.post_ride_checkins.get(activity.id)),
            )
        )
    thermal_review = morning_analysis.thermalReview if morning_analysis is not None else {}
    fresh_temperature_c = (
        round(float(fresh_temperature.temperature_c), 1) if fresh_temperature else None
    )
    try:
        fan_states = await asyncio.to_thread(
            _read_fans,
            auto_enabled=player.fan_auto_enabled,
            timezone_name=player.timezone,
            fresh_temperature_c=fresh_temperature_c,
        )
    except (DreoCredentialsError, DreoConnectionError, DreoFanError) as exc:
        log.warning("daily loop fan inventory unavailable", error=str(exc))
        fan_states = _fallback_fans(
            auto_enabled=player.fan_auto_enabled,
            timezone_name=player.timezone,
            fresh_temperature_c=fresh_temperature_c,
        )
    projection_build = await SleepProjectionContextService(db).build_from_snapshot(
        player,
        snapshot,
    )
    sleep_projection = projection_build.projection
    drivers_report = projection_build.drivers_report
    experiment_loop = ExperimentLoopService(db)
    current_assignment = await experiment_loop.current_assignment(
        player.id,
        as_of=snapshot.subject_date,
    )
    chronic_suggestions = await ChronicPatternSuggestionService(db).suggestions(
        player,
        as_of=snapshot.subject_date,
        driver_outcomes=drivers_report.outcomes,
        sleep_protocol=snapshot.sleep_protocol,
        standing_habits=snapshot.standing_habits,
        rem_rotation=rotation_from_assignment(current_assignment),
    )
    # Showing a current-week REM action is the act of issuing it. Persist that
    # exact rendered selection before returning the card; historical reads must
    # never manufacture an assignment that Mark was not actually shown then.
    if current_assignment is None and snapshot.subject_date == local_today(player.timezone):
        selected_rotation = next(
            (
                item.rotation
                for item in chronic_suggestions.items
                if item.metric_key == "rem_sleep_pct" and item.rotation is not None
            ),
            None,
        )
        if selected_rotation is not None:
            current_assignment = await experiment_loop.ensure_assignment(
                player,
                as_of=snapshot.subject_date,
                actions=list(selected_rotation.actions),
                rotation=selected_rotation,
                commit=True,
            )
            chronic_suggestions = await ChronicPatternSuggestionService(db).suggestions(
                player,
                as_of=snapshot.subject_date,
                driver_outcomes=drivers_report.outcomes,
                sleep_protocol=snapshot.sleep_protocol,
                standing_habits=snapshot.standing_habits,
                rem_rotation=rotation_from_assignment(current_assignment),
            )
    rem_check_in = await experiment_loop.rem_check_in_packet(
        player,
        wake_date=snapshot.subject_date,
        manual_entry=snapshot.manual_entry,
    )
    return DailyLoopEnvelope(
        data=DailyLoopData(
            subjectDate=snapshot.subject_date.isoformat(),
            timezone=player.timezone,
            loopState=LoopStateOut(
                dayPhase=snapshot.loop_state.day_phase,
                blockPhase=snapshot.loop_state.block_phase,
                nextAction=snapshot.loop_state.next_action,
                atBlockBoundary=snapshot.loop_state.at_block_boundary,
            ),
            holiday=HolidayStateOut(
                isActive=snapshot.active_holiday_window is not None,
                awayTonight=snapshot.overnight_away_window is not None,
                activeWindow=(
                    ActiveHolidayWindowOut(
                        startDate=snapshot.active_holiday_window.start_date.isoformat(),
                        endDate=snapshot.active_holiday_window.end_date.isoformat(),
                    )
                    if snapshot.active_holiday_window is not None
                    else None
                ),
            ),
            hostedTtsConsent=player.hosted_tts_consent,
            morningAnalysis=morning_analysis,
            briefGeneration=brief_generation,
            dailyMetrics=_serialize_daily_metric(snapshot.daily_metric),
            sleep=_serialize_sleep(snapshot.sleep),
            manualEntry=_serialize_manual_entry(snapshot.manual_entry),
            postWorkoutAnalyses=[
                _serialize_post_workout_analysis(
                    analysis,
                    snapshot.post_ride_checkins.get(analysis.activity_id)
                    if analysis.activity_id
                    else None,
                    feedback_map.get(analysis.id),
                )
                for analysis in snapshot.post_workout_analyses
            ],
            postFlexibilityAnalyses=[
                _serialize_post_flexibility_analysis(
                    analysis,
                    snapshot.post_ride_checkins.get(analysis.activity_id)
                    if analysis.activity_id
                    else None,
                    feedback_map.get(analysis.id),
                )
                for analysis in snapshot.post_flexibility_analyses
            ],
            postStrengthAnalyses=[
                _serialize_post_strength_analysis(
                    analysis,
                    snapshot.post_ride_checkins.get(analysis.activity_id)
                    if analysis.activity_id
                    else None,
                    feedback_map.get(analysis.id),
                )
                for analysis in snapshot.post_strength_analyses
            ],
            postWalkAnalyses=[
                _serialize_post_walk_analysis(
                    analysis,
                    snapshot.post_ride_checkins.get(analysis.activity_id)
                    if analysis.activity_id
                    else None,
                    feedback_map.get(analysis.id),
                )
                for analysis in snapshot.post_walk_analyses
            ],
            pendingPostWorkoutActivities=pending_post_activities,
            plannedWorkouts=planned_workouts,
            thermalState=ThermalStateOut(
                latestTemperatureC=(fresh_temperature.temperature_c if fresh_temperature else None),
                targetTemperatureC=(
                    fresh_temperature.target_temperature_c if fresh_temperature else None
                ),
                capturedAtUtc=(
                    _dt(snapshot.latest_temperature.captured_at_utc)
                    if snapshot.latest_temperature
                    else None
                ),
                overnightLowC=(snapshot.weather.overnight_low_c if snapshot.weather else None),
                overnightWindMaxMph=snapshot.weather.overnight_wind_max_mph
                if snapshot.weather
                else None,
                overnightWindGustMph=(
                    snapshot.weather.overnight_wind_gust_mph if snapshot.weather else None
                ),
                overnightWindDirectionDeg=(
                    snapshot.weather.overnight_wind_direction_deg if snapshot.weather else None
                ),
                overnightRelativeHumidityMeanPct=(
                    snapshot.weather.overnight_relative_humidity_mean_pct
                    if snapshot.weather
                    else None
                ),
                thermalReview=thermal_review,
                fans=fan_states,
            ),
            sleepProjection=_serialize_sleep_projection(sleep_projection),
            chronicSuggestions=ChronicSuggestionsOut(**chronic_suggestions.to_dict()),
            remInterventionCheckIn=(
                RemInterventionCheckInOut(**rem_check_in) if rem_check_in is not None else None
            ),
            dataQualityWarnings=[
                DataQualityWarningOut(
                    id=warning["id"],
                    summary=warning["summary"],
                    reason=warning["reason"],
                    status=warning["status"],
                    detail=warning["detail"] or None,
                )
                for warning in snapshot.data_quality_warnings
            ],
            strengthBrief=_serialize_strength_brief(snapshot.strength_brief),
            walkingBrief=_serialize_walking_brief(snapshot.walking_brief),
            breathworkBrief=_serialize_breathwork_brief(snapshot.breathwork_brief),
        ),
        meta=ApiMeta(generatedAtUtc=_generated_at()),
        errors=[],
    )
