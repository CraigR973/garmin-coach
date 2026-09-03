"""Response and request models for ``/api/v1/daily-loop`` (Batch 251, CR236-09).

These 45 Pydantic models were 500 lines of a file with four routes in it. They move
here unchanged: the router owns transport, ``services/daily_loop_envelope`` owns
assembly, and the shape they both agree on lives in one place they can both import.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from src.routers.feedback import FeedbackOut


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
    acutePhysiology: dict[str, Any] = Field(default_factory=dict)
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
