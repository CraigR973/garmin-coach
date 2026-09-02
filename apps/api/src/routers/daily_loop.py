from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, date, datetime, time, timedelta
from time import perf_counter
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import CurrentUser
from src.config import settings
from src.database import AsyncSessionLocal, get_db
from src.models.coaching import (
    Activity,
    Analysis,
    BriefGenerationStatus,
    DailyMetric,
    Feedback,
    ManualEntry,
    PlannedWorkout,
    Sleep,
)
from src.models.profile import Profile
from src.rate_limit import paid_generation_limit
from src.routers.feedback import FeedbackOut, serialize_feedback
from src.services.anthropic_text import AnthropicApiError, anthropic_user_message
from src.services.breathwork_brief import BreathworkBriefResult
from src.services.brief_generation_status import (
    STATUS_FAILED,
    STATUS_GENERATING,
    BriefGenerationStatusService,
)
from src.services.chronic_patterns import ChronicPatternSuggestionService
from src.services.daily_loop import DailyLoopService, DeliveryState
from src.services.dreo_fan import (
    DreoConnectionError,
    DreoCredentialsError,
    DreoFanClient,
    DreoFanError,
)
from src.services.environment_freshness import is_hive_temperature_fresh
from src.services.executable_coaching import ExecutableCoachingService
from src.services.experiment_loop import ExperimentLoopService, rotation_from_assignment
from src.services.fan_control import describe_fan_intent
from src.services.generation_requests import GenerationRequestInProgress
from src.services.morning_analysis import MorningAnalysisService
from src.services.morning_inputs import morning_input_presence
from src.services.nudge_alerts import NudgeAlertService
from src.services.post_activity_analysis import (
    generate_post_activity_read,
    mark_prepared_post_activity_failed,
    post_activity_kind,
    prepare_post_activity_read,
)
from src.services.session_recovery import restore_after_rollback
from src.services.sleep_projection import SleepProjectionResult
from src.services.sleep_projection_context import SleepProjectionContextService
from src.services.strength_brief import StrengthBriefResult
from src.services.tts_pregenerate import pregenerate_brief_audio
from src.services.wake_detection import BACKSTOP
from src.services.walking_brief import WalkingBriefResult
from src.services.workout_categories import (
    DAY_CATEGORY_CYCLE,
    DAY_CATEGORY_FLEXIBILITY,
    DAY_CATEGORY_WEIGHTS,
    category_for_workout_type,
)

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


log = structlog.get_logger(__name__)


class MorningInputsNotReady(RuntimeError):
    """A successful model read cannot start from an unsynced wake date."""


async def _generate_brief_after_checkin(user_id: uuid.UUID, subject_date: date) -> None:
    """Sync, then finish today's brief off the request path and notify."""

    async with AsyncSessionLocal() as session:
        player = await session.get(Profile, user_id)
        if player is None or not player.is_active or player.deleted_at is not None:
            log.warning(
                "morning check-in background generation skipped",
                profile_id=str(user_id),
                subject_date=subject_date.isoformat(),
            )
            return

        try:
            # Batch 222: the waiting card already opens on "Syncing your
            # overnight data". Make that stage real. The wake job usually won
            # this idempotent race already; when it did not, the check-in now
            # closes the gap instead of reading an empty day.
            from src.scheduler import _sync_morning_inputs

            await _sync_morning_inputs(session, [player])
            inputs = await morning_input_presence(
                session,
                user_id=user_id,
                subject_date=subject_date,
            )
            allow_missing_sleep = _local_time(player.timezone) >= BACKSTOP
            if not inputs.ready_for_read(allow_missing_sleep=allow_missing_sleep):
                raise MorningInputsNotReady

            analysis = await ExecutableCoachingService(session).regenerate_after_morning_checkin(
                player,
                subject_date,
                morning_service=MorningAnalysisService(session),
                commit=False,
            )
            await NudgeAlertService(session).push_brief_ready(
                player,
                analysis,
                subject_date=subject_date,
                commit=False,
            )
            # Batch 141: record the ready state atomically with the brief so a
            # cold reopen (no client queuedAtMs) still reads "ready", not a stale
            # "generating".
            await BriefGenerationStatusService(session).mark_ready(
                user_id, subject_date, commit=False
            )
            await session.commit()
        except GenerationRequestInProgress:
            # Batch 232.1: another worker already holds this artifact scope and is
            # generating today's brief right now. That is not a failure and must
            # not be recorded as one — the holder will write ready-or-failed, and
            # marking failed here would replace a brief that is being written
            # successfully with a retryable failure card. Leave the ``generating``
            # status exactly as found; Batch 144's stale-after guard is the
            # backstop if the holder really does die.
            await session.rollback()
            log.info(
                "morning check-in background generation deferred to the in-flight holder",
                profile_id=str(user_id),
                subject_date=subject_date.isoformat(),
            )
            return
        except Exception as exc:
            await session.rollback()
            log.exception(
                "morning check-in background generation failed",
                profile_id=str(user_id),
                subject_date=subject_date.isoformat(),
            )
            # Batch 141: persist the failure so the app shows a retryable error
            # instead of an endless "Writing your brief", and alert the operator on
            # a billing/credit outage (the 2026-07-21 freeze). Best-effort — a
            # failure to record the failure must not re-raise out of a background task.
            reason = (
                exc.reason
                if isinstance(exc, AnthropicApiError)
                else "inputs"
                if isinstance(exc, MorningInputsNotReady)
                else "other"
            )
            try:
                await BriefGenerationStatusService(session).mark_failed(
                    user_id, subject_date, reason=reason, commit=True
                )
                if reason == "billing":
                    await NudgeAlertService(session).notify_admin_generation_failure(
                        reason=reason, subject_date=subject_date, commit=True
                    )
            except Exception:
                await session.rollback()
                log.exception(
                    "recording brief generation failure state failed",
                    profile_id=str(user_id),
                    subject_date=subject_date.isoformat(),
                )
            return

        # Warms the hosted-voice cache (Batch 116 follow-up) so a consenting
        # user's first "Listen" tap is often already synthesized. Best-effort
        # — never raises, so a Piper hiccup here can't undo the brief commit
        # above.
        await pregenerate_brief_audio(player, analysis)


class ApiError(BaseModel):
    code: str
    detail: str


class ApiMeta(BaseModel):
    generatedAtUtc: str


class SleepSetupBody(BaseModel):
    """Structured controls used for the night ending on the entry date."""

    beddingWeight: Literal["quilt", "thin_cover", "sheet"] | None = None
    windowCount: int | None = Field(default=None, ge=0, le=8)
    windowApertureCm: float | None = Field(default=None, ge=0, le=100)
    blindPosition: Literal["closed", "at_windowsill", "away_from_windowsill", "open"] | None = None
    preCoolStartLocal: str | None = Field(
        default=None,
        pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$",
    )


class RemInterventionResponseBody(BaseModel):
    interventionId: str = Field(min_length=1, max_length=80)
    status: Literal["applied", "not_applied", "unknown"]


class RemInterventionFeedbackBody(BaseModel):
    """Mark's response for the assignment that covered the night just ended."""

    periodLabel: str = Field(pattern=r"^\d{4}-W\d{2}$")
    responses: list[RemInterventionResponseBody] = Field(default_factory=list, max_length=2)


class ManualEntryBody(BaseModel):
    bpSystolic: int | None = None
    bpDiastolic: int | None = None
    subjectiveScore: int | None = Field(default=None, ge=0, le=10)
    rpe: float | None = None
    feel: str | None = None
    supplementsJson: dict[str, Any] = Field(default_factory=dict)
    foodJson: dict[str, Any] = Field(default_factory=dict)
    # ``None`` means an older client omitted the new field; preserve any stored
    # setup in that case. An explicit empty object from the current client clears it.
    sleepSetupJson: SleepSetupBody | None = None
    # Same compatibility rule as sleep setup: omission preserves a response saved
    # by a newer client, while an explicit object replaces this wake-date answer.
    remInterventionFeedbackJson: RemInterventionFeedbackBody | None = None
    notes: str | None = None


class AdherenceBody(BaseModel):
    status: str
    rpe: float | None = None
    feel: str | None = None
    notes: str | None = None
    actualWorkoutJson: dict[str, Any] = Field(default_factory=dict)


class PostRideCheckInBody(BaseModel):
    subjectiveScore: int | None = Field(default=None, ge=0, le=10)
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
    sleepSetupJson: dict[str, Any]
    remInterventionFeedbackJson: dict[str, Any] | None
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
    swapSuggestion: dict[str, Any] | None = None
    weeklyMix: dict[str, Any] | None = None
    # Batch 86 (#159): deterministic "Today" action block rendered above the brief
    # prose; rides in context_packet["verdict"], so no migration.
    todayActions: list[dict[str, Any]] = []
    feedback: FeedbackOut | None = None


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
    feedback: FeedbackOut | None = None


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
    feedback: FeedbackOut | None = None


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
    feedback: FeedbackOut | None = None


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
    feedback: FeedbackOut | None = None


class PendingPostActivityOut(BaseModel):
    activityId: str
    activityName: str
    activityType: str
    activityKind: str
    plannedWorkoutId: str | None = None
    startUtc: str
    durationMin: int | None
    checkIn: ManualEntryOut | None = None


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
    id: str
    label: str
    model: str | None = None
    autoEnabled: bool
    autoTarget: bool
    mode: str
    isOn: bool | None
    speed: int | None
    oscillating: bool | None = None
    presetMode: str | None = None
    respondingToC: float | None
    nextOnLocalTime: str | None = None


class ThermalStateOut(BaseModel):
    latestTemperatureC: float | None
    targetTemperatureC: float | None
    capturedAtUtc: str | None
    overnightLowC: float | None
    overnightWindMaxMph: float | None
    overnightWindGustMph: float | None
    overnightWindDirectionDeg: float | None
    overnightRelativeHumidityMeanPct: float | None
    thermalReview: dict[str, Any]
    fans: list[FanStateOut]


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


class ChronicSuggestionRotationOut(BaseModel):
    periodLabel: str
    shown: int
    total: int
    interventionIds: list[str] = Field(default_factory=list)


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
    rotation: ChronicSuggestionRotationOut | None = None


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


class ActiveHolidayWindowOut(BaseModel):
    startDate: str
    endDate: str


class HolidayStateOut(BaseModel):
    isActive: bool
    awayTonight: bool
    activeWindow: ActiveHolidayWindowOut | None


class BriefGenerationStatusOut(BaseModel):
    """Batch 141: the state of today's morning-brief generation.

    ``status`` is ``generating`` | ``ready`` | ``failed``; ``reason`` is a
    classified slug (e.g. ``billing``) only on a failure. The client shows a
    retryable error on ``failed`` instead of an endless "Writing your brief".
    """

    status: str
    reason: str | None


class RemInterventionCheckInItemOut(BaseModel):
    id: str
    action: str
    status: Literal["applied", "not_applied", "unknown"]


class RemInterventionCheckInOut(BaseModel):
    assignmentId: str
    periodLabel: str
    windowStart: str
    windowEnd: str
    wakeDate: str
    interventions: list[RemInterventionCheckInItemOut]


class DailyLoopData(BaseModel):
    subjectDate: str
    timezone: str
    loopState: LoopStateOut
    holiday: HolidayStateOut
    hostedTtsConsent: bool
    morningAnalysis: AnalysisOut | None
    briefGeneration: BriefGenerationStatusOut | None
    dailyMetrics: DailyMetricOut | None
    sleep: SleepOut | None
    manualEntry: ManualEntryOut | None
    postWorkoutAnalyses: list[PostWorkoutAnalysisOut]
    postFlexibilityAnalyses: list[PostFlexibilityAnalysisOut]
    postStrengthAnalyses: list[PostStrengthAnalysisOut]
    postWalkAnalyses: list[PostWalkAnalysisOut]
    pendingPostWorkoutActivities: list[PendingPostActivityOut]
    plannedWorkouts: list[PlannedWorkoutOut]
    thermalState: ThermalStateOut
    sleepProjection: SleepProjectionOut
    chronicSuggestions: ChronicSuggestionsOut
    remInterventionCheckIn: RemInterventionCheckInOut | None
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


async def _envelope(player: CurrentUser, snapshot: Any, db: AsyncSession) -> DailyLoopEnvelope:
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
    if current_assignment is None and snapshot.subject_date == _local_today(player.timezone):
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


@router.get("", response_model=DailyLoopEnvelope)
async def get_daily_loop(
    player: CurrentUser,
    subject_date: date | None = None,
    db: AsyncSession = Depends(get_db),
) -> DailyLoopEnvelope:
    # Batch 62.5: attribute server time (snapshot round-trips vs envelope compute)
    # so the latency work can be measured before/after from the logs, not guessed.
    started = perf_counter()
    service = DailyLoopService(db)
    snapshot = await service.get_snapshot(player, subject_date=subject_date)
    snapshot_ms = round((perf_counter() - started) * 1000, 1)
    envelope = await _envelope(player, snapshot, db)
    log.info(
        "daily_loop served",
        snapshot_ms=snapshot_ms,
        envelope_ms=round((perf_counter() - started) * 1000 - snapshot_ms, 1),
        total_ms=round((perf_counter() - started) * 1000, 1),
    )
    return envelope


@router.put("/{subject_date}/manual-entry", response_model=DailyLoopEnvelope)
@paid_generation_limit
async def upsert_manual_entry(
    subject_date: date,
    body: ManualEntryBody,
    request: Request,
    player: CurrentUser,
    background_tasks: BackgroundTasks,
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
        sleep_setup_json=(
            body.sleepSetupJson.model_dump(exclude_none=True)
            if body.sleepSetupJson is not None
            else None
        ),
        rem_intervention_feedback_json=(
            body.remInterventionFeedbackJson.model_dump()
            if body.remInterventionFeedbackJson is not None
            else None
        ),
        notes=body.notes,
    )
    # Batch 97: keep the check-in as the primary generate trigger, but move the
    # actual brief generation off the request path. Saving returns immediately;
    # the background task regenerates the brief, preserves Batch 85's downgrade-
    # only / never-touch-an-approved-ride guardrails, then fires a ready push.
    if subject_date == _local_today(player.timezone):
        # Batch 141: mark generating before the background task runs so the
        # envelope this request returns already reads "generating" (the task
        # flips it to ready/failed), giving the client a real state to poll.
        await BriefGenerationStatusService(db).mark_generating(player.id, subject_date, commit=True)
        background_tasks.add_task(_generate_brief_after_checkin, player.id, subject_date)
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
@paid_generation_limit
async def upsert_post_ride_checkin(
    subject_date: date,
    activity_id: uuid.UUID,
    body: PostRideCheckInBody,
    request: Request,
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
    # Batch 87: the generic activity-linked check-in is the primary generation
    # trigger for rides, strength, mobility, and deliberate walks. The save above
    # commits first, so every reader sees the just-entered RPE/feel/notes.
    activity = await db.get(Activity, activity_id)
    read_error: ApiError | None = None
    if activity is not None and post_activity_kind(activity) is not None:
        # Batch 143: the check-in above already committed (service.commit), so his
        # RPE/feel/notes are safe. An Anthropic outage on the read must not 500 that
        # away. Generate inside a SAVEPOINT so a failure rolls back only the
        # half-written analysis (and its planned-workout completion flip), never the
        # committed check-in — then surface a non-fatal note (the activity re-appears
        # as a pending read carrying the saved check-in, so re-submitting is the
        # retry) and alert on a billing outage the same way as the morning brief.
        prepared = await prepare_post_activity_read(db, player, activity, commit=True)
        try:
            async with db.begin_nested():
                await generate_post_activity_read(db, player, activity, force=True, commit=False)
            await db.commit()
        except AnthropicApiError as exc:
            await mark_prepared_post_activity_failed(
                db,
                player,
                activity,
                prepared,
                reason=exc.reason,
                commit=True,
            )
            if exc.reason == "billing":
                await NudgeAlertService(db).notify_admin_generation_failure(
                    reason=exc.reason, subject_date=subject_date, commit=True
                )
            read_error = ApiError(
                code="post_workout_read_failed",
                detail=anthropic_user_message(exc.reason),
            )
        except GenerationRequestInProgress:
            # Batch 232.1: another worker owns this activity's read. Roll back the
            # savepoint but leave the prepared ``generating`` status alone — the
            # holder writes the real outcome, and recording a failure here would
            # replace a read that is being generated with a failed one. The 409
            # propagates so the client polls rather than treating it as an error.
            await db.rollback()
            raise
        except Exception:
            await db.rollback()
            # Batch 242 (CR236-01): the rollback expired both ORM instances, and
            # ``mark_prepared_post_activity_failed`` reads ``player.id`` and
            # ``activity.id``. Without the reload it raises MissingGreenlet from
            # inside this handler, so the read is never marked failed and Mark is
            # left on a spinner rather than a retryable state. ``prepared`` is a
            # plain dataclass and is unaffected.
            await restore_after_rollback(db, player, activity)
            await mark_prepared_post_activity_failed(
                db,
                player,
                activity,
                prepared,
                reason="generation_error",
                commit=True,
            )
            raise
    snapshot = await service.get_snapshot(player, subject_date=subject_date)
    envelope = await _envelope(player, snapshot, db)
    if read_error is not None:
        envelope.errors.append(read_error)
    return envelope
