from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import CurrentUser
from src.database import get_db
from src.models.coaching import Analysis, DailyMetric, ManualEntry, PlannedWorkout, Sleep
from src.services.breathwork_brief import BreathworkBriefResult
from src.services.chronic_patterns import ChronicPatternSuggestionService
from src.services.daily_loop import DailyLoopService, DeliveryState
from src.services.environment_freshness import is_hive_temperature_fresh
from src.services.executable_coaching import ExecutableCoachingService
from src.services.fan_control import describe_fan_intent
from src.services.insights import OUTCOME_SLEEP_SCORE, DriversReport, InsightsService
from src.services.morning_analysis import MorningAnalysisService
from src.services.sleep_projection import (
    SleepDriverEvidence,
    SleepProjectionInputs,
    SleepProjectionResult,
    TrainingSignal,
    project_sleep,
)
from src.services.strength_brief import StrengthBriefResult
from src.services.walking_brief import WalkingBriefResult

router = APIRouter(prefix="/api/v1/daily-loop", tags=["daily-loop"])


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


def _local_today(timezone_name: str) -> date:
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        zone = ZoneInfo("UTC")
    return datetime.now(zone).date()


log = structlog.get_logger(__name__)


class ApiError(BaseModel):
    code: str
    detail: str


class ApiMeta(BaseModel):
    generatedAtUtc: str


class ManualEntryBody(BaseModel):
    bpSystolic: int | None = None
    bpDiastolic: int | None = None
    subjectiveScore: int | None = None
    rpe: float | None = None
    feel: str | None = None
    supplementsJson: dict[str, Any] = Field(default_factory=dict)
    foodJson: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = None


class AdherenceBody(BaseModel):
    status: str
    rpe: float | None = None
    feel: str | None = None
    notes: str | None = None
    actualWorkoutJson: dict[str, Any] = Field(default_factory=dict)


class PostRideCheckInBody(BaseModel):
    subjectiveScore: int | None = None
    rpe: float | None = None
    feel: str | None = None
    notes: str | None = None


class ManualEntryOut(BaseModel):
    id: str
    userId: str
    plannedWorkoutId: str | None
    activityId: str | None
    plannedWorkoutVersion: int | None
    entryDate: str
    entryAtUtc: str
    bpSystolic: int | None
    bpDiastolic: int | None
    subjectiveScore: int | None
    rpe: float | None
    feel: str | None
    adherenceStatus: str | None
    actualWorkoutJson: dict[str, Any]
    supplementsJson: dict[str, Any]
    foodJson: dict[str, Any]
    notes: str | None


class AnalysisOut(BaseModel):
    id: str
    generatedAtUtc: str
    verdict: str | None
    promptVersion: str
    modelName: str | None
    outputMarkdown: str
    planAdjustments: list[str]
    reasons: list[str]
    readinessInterpretation: str | None
    thermalReview: dict[str, Any]
    metricsVsBaselines: list[dict[str, Any]]
    ageComparison: dict[str, Any]


class PostWorkoutAnalysisOut(BaseModel):
    id: str
    activityId: str | None
    plannedWorkoutId: str | None
    activityName: str | None
    activityType: str | None
    generatedAtUtc: str
    promptVersion: str
    modelName: str | None
    outputMarkdown: str
    recoveryDecision: dict[str, Any]
    timeSeriesSummary: dict[str, Any]
    intervals: list[dict[str, Any]]
    execution: dict[str, Any]
    tomorrowImpact: str | None
    postRideCheckIn: ManualEntryOut | None = None


class PostFlexibilityAnalysisOut(BaseModel):
    id: str
    activityId: str | None
    activityName: str | None
    activityType: str | None
    generatedAtUtc: str
    promptVersion: str
    modelName: str | None
    outputMarkdown: str
    heartRateReview: dict[str, Any]
    consistency: dict[str, Any]
    activityCheckIn: ManualEntryOut | None = None


class PostStrengthAnalysisOut(BaseModel):
    id: str
    activityId: str | None
    activityName: str | None
    activityType: str | None
    generatedAtUtc: str
    promptVersion: str
    modelName: str | None
    outputMarkdown: str
    heartRateReview: dict[str, Any]
    consistency: dict[str, Any]
    activityCheckIn: ManualEntryOut | None = None


class PostWalkAnalysisOut(BaseModel):
    id: str
    activityId: str | None
    activityName: str | None
    activityType: str | None
    generatedAtUtc: str
    promptVersion: str
    modelName: str | None
    outputMarkdown: str
    heartRateReview: dict[str, Any]
    paceReview: dict[str, Any]
    activeRecoveryContext: dict[str, Any]
    activityCheckIn: ManualEntryOut | None = None


class DailyMetricOut(BaseModel):
    id: str
    userId: str
    calendarDate: str
    recordedAtUtc: str | None
    readinessScore: int | None
    readinessLevel: str | None
    readinessSleepScore: int | None
    recoveryTimeMin: int | None
    acuteLoad: float | None
    trainingStatus: str | None
    hrvLastNightAvgMs: int | None
    hrvWeeklyAvgMs: int | None
    hrvStatus: str | None
    hrvBaselineLowMs: int | None
    hrvBaselineHighMs: int | None
    restingHeartRateBpm: int | None
    stressAvg: float | None
    bodyBatteryCharged: int | None
    bodyBatteryDrained: int | None
    bodyBatteryEnd: int | None
    weightKg: float | None
    vo2max: float | None
    rawPayload: dict[str, Any]


class SleepOut(BaseModel):
    id: str
    userId: str
    calendarDate: str
    sleepStartUtc: str | None
    sleepEndUtc: str | None
    score: int | None
    ageAdjustedScore: int | None
    qualifier: str | None
    durationSec: int | None
    deepSleepSec: int | None
    lightSleepSec: int | None
    remSleepSec: int | None
    awakeSleepSec: int | None
    unmeasurableSleepSec: int | None
    averageSpo2Pct: float | None
    lowestSpo2Pct: float | None
    averageRespiration: float | None
    restingHeartRateBpm: int | None
    avgOvernightHrvMs: int | None
    hrvStatus: str | None
    avgSleepStress: float | None
    restlessMomentsCount: int | None
    bodyBatteryChange: int | None
    factorsJson: dict[str, Any]
    rawPayload: dict[str, Any]


class DeliveryStateOut(BaseModel):
    liveStatus: str | None
    liveOrigin: str | None
    intervalsEventId: str | None
    changed: bool
    adjustment: dict[str, Any] | None


class PlannedWorkoutOut(BaseModel):
    id: str
    userId: str
    planBlockId: str | None
    workoutDate: str
    version: int
    title: str
    workoutType: str
    status: str
    isActive: bool
    plannedDurationMin: int | None
    intensityTarget: str | None
    structuredWorkout: dict[str, Any]
    source: str | None
    adherence: ManualEntryOut | None = None
    delivery: DeliveryStateOut | None = None


class FanStateOut(BaseModel):
    autoEnabled: bool
    mode: str
    isOn: bool | None
    speed: int | None
    respondingToC: float | None


class ThermalStateOut(BaseModel):
    latestTemperatureC: float | None
    targetTemperatureC: float | None
    capturedAtUtc: str | None
    overnightLowC: float | None
    overnightWindMaxMph: float | None
    overnightWindGustMph: float | None
    thermalReview: dict[str, Any]
    fan: FanStateOut


class SleepProjectionOut(BaseModel):
    status: str
    tone: str
    headline: str
    summary: str
    evidence: list[str]
    prepActions: list[str]
    protocol: dict[str, Any]


class ChronicSuggestionDriverOut(BaseModel):
    driver: str
    label: str
    coefficient: float
    sampleCount: int
    summary: str | None = None


class ChronicSuggestionItemOut(BaseModel):
    id: str
    metricKey: str
    label: str
    title: str
    summary: str
    tone: str
    priority: int
    evidence: list[str]
    actions: list[str]
    driver: ChronicSuggestionDriverOut | None = None


class ChronicSuggestionWindowOut(BaseModel):
    startDate: str
    endDate: str
    weeks: int
    nightsObserved: int
    nightsRequired: int


class ChronicSuggestionsOut(BaseModel):
    status: str
    headline: str
    summary: str
    evidenceWindow: ChronicSuggestionWindowOut
    items: list[ChronicSuggestionItemOut]


class DataQualityWarningOut(BaseModel):
    id: str
    summary: str
    reason: str
    status: str
    detail: str | None = None


class WindowStatsOut(BaseModel):
    sessionCount: int
    totalDurationMin: int
    totalLoadProxy: float
    sessionsPerWeek: float


class WalkingWindowStatsOut(BaseModel):
    sessionCount: int
    totalDistanceM: float
    totalDurationMin: int
    sessionsPerWeek: float


class BreathworkWindowStatsOut(BaseModel):
    sessionCount: int
    totalDurationMin: int
    sessionsPerWeek: float


class StrengthSessionOut(BaseModel):
    activityId: str
    activityName: str
    activityType: str
    sessionDate: str
    durationMin: int | None
    trainingLoad: float | None


class StrengthBriefOut(BaseModel):
    asOfDate: str
    window4w: WindowStatsOut
    window12w: WindowStatsOut
    recentSessions: list[StrengthSessionOut]
    trend: str
    trendReason: str


class WalkingSessionOut(BaseModel):
    activityId: str
    activityName: str
    activityType: str
    sessionDate: str
    durationMin: int | None
    distanceM: float | None


class WalkingBriefOut(BaseModel):
    asOfDate: str
    window4w: WalkingWindowStatsOut
    window12w: WalkingWindowStatsOut
    recentSessions: list[WalkingSessionOut]
    trend: str
    trendReason: str


class BreathworkSessionOut(BaseModel):
    activityId: str
    activityName: str
    activityType: str
    sessionDate: str
    durationMin: int | None


class BreathworkBriefOut(BaseModel):
    asOfDate: str
    window4w: BreathworkWindowStatsOut
    window12w: BreathworkWindowStatsOut
    recentSessions: list[BreathworkSessionOut]
    trend: str
    trendReason: str


class LoopStateOut(BaseModel):
    dayPhase: str
    blockPhase: str | None
    nextAction: str
    atBlockBoundary: bool


class DailyLoopData(BaseModel):
    subjectDate: str
    timezone: str
    loopState: LoopStateOut
    morningAnalysis: AnalysisOut | None
    dailyMetrics: DailyMetricOut | None
    sleep: SleepOut | None
    manualEntry: ManualEntryOut | None
    postWorkoutAnalyses: list[PostWorkoutAnalysisOut]
    postFlexibilityAnalyses: list[PostFlexibilityAnalysisOut]
    postStrengthAnalyses: list[PostStrengthAnalysisOut]
    postWalkAnalyses: list[PostWalkAnalysisOut]
    plannedWorkouts: list[PlannedWorkoutOut]
    thermalState: ThermalStateOut
    sleepProjection: SleepProjectionOut
    chronicSuggestions: ChronicSuggestionsOut
    dataQualityWarnings: list[DataQualityWarningOut]
    strengthBrief: StrengthBriefOut
    walkingBrief: WalkingBriefOut
    breathworkBrief: BreathworkBriefOut


class DailyLoopEnvelope(BaseModel):
    data: DailyLoopData
    meta: ApiMeta
    errors: list[ApiError]


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
        notes=entry.notes,
    )


def _normalize_api_verdict(verdict: str | None) -> str | None:
    if not verdict:
        return None
    return verdict.strip().lower()


def _serialize_analysis(analysis: Analysis | None) -> AnalysisOut | None:
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
    )


def _serialize_post_workout_analysis(
    analysis: Analysis,
    post_ride_checkin: ManualEntry | None,
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
    )


def _serialize_post_flexibility_analysis(
    analysis: Analysis,
    activity_checkin: ManualEntry | None,
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
    )


def _serialize_post_strength_analysis(
    analysis: Analysis,
    activity_checkin: ManualEntry | None,
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
    )


def _serialize_post_walk_analysis(
    analysis: Analysis,
    activity_checkin: ManualEntry | None,
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
        rawPayload=metric.raw_payload,
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
        rawPayload=sleep.raw_payload,
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


def _activity_training_signals(snapshot: Any, timezone_name: str) -> list[TrainingSignal]:
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        zone = ZoneInfo("UTC")
    signals: list[TrainingSignal] = []
    for activity in snapshot.activities:
        local_start = activity.start_utc.replace(tzinfo=UTC).astimezone(zone).time()
        signals.append(
            TrainingSignal(
                name=activity.activity_name,
                activity_type=activity.activity_type,
                local_start=local_start,
                duration_min=(
                    round(float(activity.duration_sec) / 60, 1)
                    if activity.duration_sec is not None
                    else None
                ),
                training_load=(
                    float(activity.training_load) if activity.training_load is not None else None
                ),
                aerobic_training_effect=(
                    float(activity.aerobic_training_effect)
                    if activity.aerobic_training_effect is not None
                    else None
                ),
                anaerobic_training_effect=(
                    float(activity.anaerobic_training_effect)
                    if activity.anaerobic_training_effect is not None
                    else None
                ),
            )
        )
    return signals


async def _sleep_projection(
    player: CurrentUser,
    snapshot: Any,
    *,
    latest_bedroom_temperature_c: float | None,
    drivers_report: DriversReport,
) -> SleepProjectionResult:
    sleep_drivers = [
        SleepDriverEvidence(
            driver=driver.driver,
            coefficient=driver.coefficient,
            sample_count=driver.sample_count,
            summary=driver.summary,
        )
        for driver in drivers_report.outcomes.get(OUTCOME_SLEEP_SCORE, [])
    ]
    return project_sleep(
        SleepProjectionInputs(
            training=_activity_training_signals(snapshot, player.timezone),
            sleep_drivers=sleep_drivers,
            sleep_protocol=snapshot.sleep_protocol,
            latest_bedroom_temperature_c=latest_bedroom_temperature_c,
            overnight_low_c=snapshot.weather.overnight_low_c if snapshot.weather else None,
            overnight_wind_max_mph=(
                snapshot.weather.overnight_wind_max_mph if snapshot.weather else None
            ),
            fan_auto_enabled=player.fan_auto_enabled,
        )
    )


async def _envelope(player: CurrentUser, snapshot: Any, db: AsyncSession) -> DailyLoopEnvelope:
    morning_analysis = _serialize_analysis(snapshot.morning_analysis)
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
    thermal_review = morning_analysis.thermalReview if morning_analysis is not None else {}
    fresh_temperature_c = (
        round(float(fresh_temperature.temperature_c), 1) if fresh_temperature else None
    )
    fan_intent = describe_fan_intent(
        _local_time(player.timezone), fresh_temperature_c, auto_enabled=player.fan_auto_enabled
    )
    drivers_report = await InsightsService(db).drivers(player, as_of=snapshot.subject_date)
    sleep_projection = await _sleep_projection(
        player,
        snapshot,
        latest_bedroom_temperature_c=fresh_temperature_c,
        drivers_report=drivers_report,
    )
    chronic_suggestions = await ChronicPatternSuggestionService(db).suggestions(
        player,
        as_of=snapshot.subject_date,
        sleep_drivers=drivers_report.outcomes.get(OUTCOME_SLEEP_SCORE, []),
        sleep_protocol=snapshot.sleep_protocol,
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
            morningAnalysis=morning_analysis,
            dailyMetrics=_serialize_daily_metric(snapshot.daily_metric),
            sleep=_serialize_sleep(snapshot.sleep),
            manualEntry=_serialize_manual_entry(snapshot.manual_entry),
            postWorkoutAnalyses=[
                _serialize_post_workout_analysis(
                    analysis,
                    snapshot.post_ride_checkins.get(analysis.activity_id)
                    if analysis.activity_id
                    else None,
                )
                for analysis in snapshot.post_workout_analyses
            ],
            postFlexibilityAnalyses=[
                _serialize_post_flexibility_analysis(
                    analysis,
                    snapshot.post_ride_checkins.get(analysis.activity_id)
                    if analysis.activity_id
                    else None,
                )
                for analysis in snapshot.post_flexibility_analyses
            ],
            postStrengthAnalyses=[
                _serialize_post_strength_analysis(
                    analysis,
                    snapshot.post_ride_checkins.get(analysis.activity_id)
                    if analysis.activity_id
                    else None,
                )
                for analysis in snapshot.post_strength_analyses
            ],
            postWalkAnalyses=[
                _serialize_post_walk_analysis(
                    analysis,
                    snapshot.post_ride_checkins.get(analysis.activity_id)
                    if analysis.activity_id
                    else None,
                )
                for analysis in snapshot.post_walk_analyses
            ],
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
                thermalReview=thermal_review,
                fan=FanStateOut(
                    autoEnabled=fan_intent.auto_enabled,
                    mode=fan_intent.mode,
                    isOn=fan_intent.is_on,
                    speed=fan_intent.speed,
                    respondingToC=fan_intent.responding_to_c,
                ),
            ),
            sleepProjection=_serialize_sleep_projection(sleep_projection),
            chronicSuggestions=ChronicSuggestionsOut(**chronic_suggestions.to_dict()),
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


@router.get("", response_model=DailyLoopEnvelope)
async def get_daily_loop(
    player: CurrentUser,
    subject_date: date | None = None,
    db: AsyncSession = Depends(get_db),
) -> DailyLoopEnvelope:
    service = DailyLoopService(db)
    snapshot = await service.get_snapshot(player, subject_date=subject_date)
    return await _envelope(player, snapshot, db)


@router.put("/{subject_date}/manual-entry", response_model=DailyLoopEnvelope)
async def upsert_manual_entry(
    subject_date: date,
    body: ManualEntryBody,
    player: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> DailyLoopEnvelope:
    service = DailyLoopService(db)
    await service.upsert_manual_entry(
        player,
        subject_date=subject_date,
        bp_systolic=body.bpSystolic,
        bp_diastolic=body.bpDiastolic,
        subjective_score=body.subjectiveScore,
        rpe=body.rpe,
        feel=body.feel,
        supplements_json=body.supplementsJson,
        food_json=body.foodJson,
        notes=body.notes,
    )
    # A morning check-in adds Mark's subjective read after the wake verdict was
    # computed from sleep alone. If it worsens today's verdict while the eased ride
    # is still pending, recompute the verdict + ride so his notes shape the session
    # (never touches an approved/pushed ride). Best-effort — never blocks the save.
    if subject_date == _local_today(player.timezone):
        try:
            await ExecutableCoachingService(db).regenerate_after_morning_checkin(
                player, subject_date, morning_service=MorningAnalysisService(db)
            )
        except Exception:
            log.exception(
                "morning check-in verdict recompute failed",
                subject_date=subject_date.isoformat(),
            )
    snapshot = await service.get_snapshot(player, subject_date=subject_date)
    return await _envelope(player, snapshot, db)


@router.put(
    "/{subject_date}/planned-workouts/{planned_workout_id}/adherence",
    response_model=DailyLoopEnvelope,
)
async def upsert_workout_adherence(
    subject_date: date,
    planned_workout_id: uuid.UUID,
    body: AdherenceBody,
    player: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> DailyLoopEnvelope:
    service = DailyLoopService(db)
    await service.upsert_adherence(
        player,
        subject_date=subject_date,
        planned_workout_id=planned_workout_id,
        adherence_status=body.status,
        rpe=body.rpe,
        feel=body.feel,
        notes=body.notes,
        actual_workout_json=body.actualWorkoutJson,
    )
    snapshot = await service.get_snapshot(player, subject_date=subject_date)
    return await _envelope(player, snapshot, db)


@router.put(
    "/{subject_date}/activities/{activity_id}/post-ride-check-in",
    response_model=DailyLoopEnvelope,
)
async def upsert_post_ride_checkin(
    subject_date: date,
    activity_id: uuid.UUID,
    body: PostRideCheckInBody,
    player: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> DailyLoopEnvelope:
    service = DailyLoopService(db)
    await service.upsert_post_ride_checkin(
        player,
        subject_date=subject_date,
        activity_id=activity_id,
        subjective_score=body.subjectiveScore,
        rpe=body.rpe,
        feel=body.feel,
        notes=body.notes,
    )
    snapshot = await service.get_snapshot(player, subject_date=subject_date)
    return await _envelope(player, snapshot, db)
