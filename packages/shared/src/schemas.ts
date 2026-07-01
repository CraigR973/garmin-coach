import { z } from 'zod';

export const roleSchema = z.enum(['admin', 'player']);
export const isoDateSchema = z.string().regex(/^\d{4}-\d{2}-\d{2}$/);
export const isoDateTimeSchema = z.string().datetime({ offset: true });
export const jsonObjectSchema = z.record(z.unknown());

export const profileSchema = z.object({
  id: z.string().uuid(),
  displayName: z.string().min(1),
  role: roleSchema,
  timezone: z.string().min(1),
  garminUserProfilePk: z.number().int().nullable().optional(),
  hiveHomeId: z.string().nullable().optional(),
  latitude: z.number().nullable().optional(),
  longitude: z.number().nullable().optional(),
});

export const dailyMetricSchema = z.object({
  id: z.string().uuid(),
  userId: z.string().uuid(),
  calendarDate: isoDateSchema,
  recordedAtUtc: isoDateTimeSchema.nullable().optional(),
  readinessScore: z.number().int().nullable().optional(),
  readinessLevel: z.string().nullable().optional(),
  readinessSleepScore: z.number().int().nullable().optional(),
  recoveryTimeMin: z.number().int().nullable().optional(),
  acuteLoad: z.number().nullable().optional(),
  trainingStatus: z.string().nullable().optional(),
  hrvLastNightAvgMs: z.number().int().nullable().optional(),
  hrvWeeklyAvgMs: z.number().int().nullable().optional(),
  hrvStatus: z.string().nullable().optional(),
  hrvBaselineLowMs: z.number().int().nullable().optional(),
  hrvBaselineHighMs: z.number().int().nullable().optional(),
  restingHeartRateBpm: z.number().int().nullable().optional(),
  stressAvg: z.number().nullable().optional(),
  bodyBatteryCharged: z.number().int().nullable().optional(),
  bodyBatteryDrained: z.number().int().nullable().optional(),
  bodyBatteryEnd: z.number().int().nullable().optional(),
  weightKg: z.number().nullable().optional(),
  vo2max: z.number().nullable().optional(),
  rawPayload: jsonObjectSchema.default({}),
});

export const sleepSchema = z.object({
  id: z.string().uuid(),
  userId: z.string().uuid(),
  calendarDate: isoDateSchema,
  sleepStartUtc: isoDateTimeSchema.nullable().optional(),
  sleepEndUtc: isoDateTimeSchema.nullable().optional(),
  score: z.number().int().nullable().optional(),
  ageAdjustedScore: z.number().int().nullable().optional(),
  qualifier: z.string().nullable().optional(),
  durationSec: z.number().int().nullable().optional(),
  deepSleepSec: z.number().int().nullable().optional(),
  lightSleepSec: z.number().int().nullable().optional(),
  remSleepSec: z.number().int().nullable().optional(),
  awakeSleepSec: z.number().int().nullable().optional(),
  unmeasurableSleepSec: z.number().int().nullable().optional(),
  averageSpo2Pct: z.number().nullable().optional(),
  lowestSpo2Pct: z.number().nullable().optional(),
  averageRespiration: z.number().nullable().optional(),
  restingHeartRateBpm: z.number().int().nullable().optional(),
  avgOvernightHrvMs: z.number().int().nullable().optional(),
  hrvStatus: z.string().nullable().optional(),
  avgSleepStress: z.number().nullable().optional(),
  restlessMomentsCount: z.number().int().nullable().optional(),
  bodyBatteryChange: z.number().int().nullable().optional(),
  factorsJson: jsonObjectSchema.default({}),
  rawPayload: jsonObjectSchema.default({}),
});

export const activitySchema = z.object({
  id: z.string().uuid(),
  userId: z.string().uuid(),
  garminActivityId: z.number().int(),
  garminActivityUuid: z.string().nullable().optional(),
  activityName: z.string().min(1),
  activityType: z.string().min(1),
  startUtc: isoDateTimeSchema,
  endUtc: isoDateTimeSchema.nullable().optional(),
  durationSec: z.number().nullable().optional(),
  elapsedDurationSec: z.number().nullable().optional(),
  movingDurationSec: z.number().nullable().optional(),
  distanceM: z.number().nullable().optional(),
  calories: z.number().nullable().optional(),
  avgHeartRateBpm: z.number().int().nullable().optional(),
  maxHeartRateBpm: z.number().int().nullable().optional(),
  avgPowerWatts: z.number().int().nullable().optional(),
  maxPowerWatts: z.number().int().nullable().optional(),
  normalizedPowerWatts: z.number().int().nullable().optional(),
  intensityFactor: z.number().nullable().optional(),
  trainingLoad: z.number().nullable().optional(),
  aerobicTrainingEffect: z.number().nullable().optional(),
  anaerobicTrainingEffect: z.number().nullable().optional(),
  avgCadenceRpm: z.number().nullable().optional(),
  maxCadenceRpm: z.number().nullable().optional(),
  avgRespiration: z.number().nullable().optional(),
  maxRespiration: z.number().nullable().optional(),
  minTemperatureC: z.number().nullable().optional(),
  maxTemperatureC: z.number().nullable().optional(),
  excludeFromRecovery: z.boolean().default(false),
  rawSummary: jsonObjectSchema.default({}),
});

export const activityTimeSeriesSchema = z.object({
  id: z.string().uuid(),
  activityId: z.string().uuid(),
  sampleIndex: z.number().int().nonnegative(),
  timestampUtc: isoDateTimeSchema.nullable().optional(),
  elapsedSec: z.number().nullable().optional(),
  movingDurationSec: z.number().nullable().optional(),
  distanceM: z.number().nullable().optional(),
  powerWatts: z.number().nullable().optional(),
  heartRateBpm: z.number().nullable().optional(),
  cadenceRpm: z.number().nullable().optional(),
  respiration: z.number().nullable().optional(),
  performanceCondition: z.number().nullable().optional(),
  availableStamina: z.number().nullable().optional(),
  potentialStamina: z.number().nullable().optional(),
  speedMps: z.number().nullable().optional(),
  airTemperatureC: z.number().nullable().optional(),
  rawMetrics: jsonObjectSchema.default({}),
});

export const temperatureReadingSchema = z.object({
  id: z.string().uuid(),
  userId: z.string().uuid(),
  source: z.literal('hive').or(z.string().min(1)),
  productId: z.string().nullable().optional(),
  deviceId: z.string().nullable().optional(),
  capturedAtUtc: isoDateTimeSchema,
  temperatureC: z.number(),
  targetTemperatureC: z.number().nullable().optional(),
  rawPayload: jsonObjectSchema.default({}),
});

export const weatherDailySchema = z.object({
  id: z.string().uuid(),
  userId: z.string().uuid(),
  calendarDate: isoDateSchema,
  source: z.literal('open_meteo').or(z.string().min(1)),
  latitude: z.number(),
  longitude: z.number(),
  tempHighC: z.number().nullable().optional(),
  tempLowC: z.number().nullable().optional(),
  overnightLowC: z.number().nullable().optional(),
  overnightWindMaxMph: z.number().nullable().optional(),
  overnightWindGustMph: z.number().nullable().optional(),
  windMaxMph: z.number().nullable().optional(),
  windGustMph: z.number().nullable().optional(),
  precipitationMm: z.number().nullable().optional(),
  sunriseUtc: isoDateTimeSchema.nullable().optional(),
  sunsetUtc: isoDateTimeSchema.nullable().optional(),
  rawPayload: jsonObjectSchema.default({}),
});

export const manualEntrySchema = z.object({
  id: z.string().uuid(),
  userId: z.string().uuid(),
  plannedWorkoutId: z.string().uuid().nullable().optional(),
  activityId: z.string().uuid().nullable().optional(),
  plannedWorkoutVersion: z.number().int().nullable().optional(),
  entryDate: isoDateSchema,
  entryAtUtc: isoDateTimeSchema,
  bpSystolic: z.number().int().nullable().optional(),
  bpDiastolic: z.number().int().nullable().optional(),
  subjectiveScore: z.number().int().min(1).max(10).nullable().optional(),
  rpe: z.number().min(0).max(10).nullable().optional(),
  feel: z.string().nullable().optional(),
  adherenceStatus: z.enum(['completed', 'modified', 'skipped']).nullable().optional(),
  actualWorkoutJson: jsonObjectSchema.default({}),
  supplementsJson: jsonObjectSchema.default({}),
  foodJson: jsonObjectSchema.default({}),
  notes: z.string().nullable().optional(),
});

export const manualEntryInputSchema = z.object({
  bpSystolic: z.number().int().positive().nullable().optional(),
  bpDiastolic: z.number().int().positive().nullable().optional(),
  subjectiveScore: z.number().int().min(1).max(10).nullable().optional(),
  rpe: z.number().min(0).max(10).nullable().optional(),
  feel: z.string().max(80).nullable().optional(),
  supplementsJson: jsonObjectSchema.default({}),
  foodJson: jsonObjectSchema.default({}),
  notes: z.string().nullable().optional(),
});

export const adherenceStatusSchema = z.enum(['completed', 'modified', 'skipped']);

export const plannedWorkoutAdherenceInputSchema = z.object({
  status: adherenceStatusSchema,
  rpe: z.number().min(0).max(10).nullable().optional(),
  feel: z.string().max(80).nullable().optional(),
  notes: z.string().nullable().optional(),
  actualWorkoutJson: jsonObjectSchema.default({}),
});

export const postRideCheckInInputSchema = z.object({
  subjectiveScore: z.number().int().min(1).max(10).nullable().optional(),
  rpe: z.number().min(0).max(10).nullable().optional(),
  feel: z.string().max(80).nullable().optional(),
  notes: z.string().nullable().optional(),
});

export const planBlockSchema = z.object({
  id: z.string().uuid(),
  userId: z.string().uuid(),
  name: z.string().min(1),
  version: z.number().int().positive(),
  sequenceIndex: z.number().int().nullable().optional(),
  blockType: z.string().nullable().optional(),
  startDate: isoDateSchema,
  endDate: isoDateSchema,
  goalsJson: jsonObjectSchema.default({}),
  rawPlan: jsonObjectSchema.default({}),
});

export const plannedWorkoutStatusSchema = z.enum([
  'planned',
  'approved',
  'pushed',
  'completed',
  'skipped',
  'superseded',
]);

export const plannedWorkoutSchema = z.object({
  id: z.string().uuid(),
  userId: z.string().uuid(),
  planBlockId: z.string().uuid().nullable().optional(),
  workoutDate: isoDateSchema,
  version: z.number().int().positive(),
  title: z.string().min(1),
  workoutType: z.string().min(1),
  status: plannedWorkoutStatusSchema,
  isActive: z.boolean(),
  plannedDurationMin: z.number().int().nullable().optional(),
  intensityTarget: z.string().nullable().optional(),
  structuredWorkout: jsonObjectSchema.default({}),
  source: z.string().nullable().optional(),
});

export const analysisTypeSchema = z.enum(['morning', 'post_workout', 'weekly', 'manual']);
export const verdictSchema = z.enum(['green', 'amber', 'red']).nullable();

export const analysisSchema = z.object({
  id: z.string().uuid(),
  userId: z.string().uuid(),
  activityId: z.string().uuid().nullable().optional(),
  analysisType: analysisTypeSchema,
  subjectDate: isoDateSchema,
  generatedAtUtc: isoDateTimeSchema,
  promptVersion: z.string().min(1),
  modelName: z.string().nullable().optional(),
  verdict: verdictSchema.optional(),
  contextPacket: jsonObjectSchema.default({}),
  outputMarkdown: z.string(),
  rawResponse: jsonObjectSchema.default({}),
});

export const experimentSchema = z.object({
  id: z.string().uuid(),
  userId: z.string().uuid(),
  title: z.string().min(1),
  hypothesis: z.string().min(1),
  status: z.enum(['active', 'paused', 'complete', 'abandoned']),
  startDate: isoDateSchema.nullable().optional(),
  endDate: isoDateSchema.nullable().optional(),
  successCriteriaJson: jsonObjectSchema.default({}),
  observationsJson: jsonObjectSchema.default({}),
});

export const knowledgeBaseSectionSchema = z.enum([
  'profile',
  'data_quality_rules',
  'age_adjustment',
  'sleep_protocol',
  'training_plan',
  'active_hypotheses',
  'analysis_rules',
]);

export const knowledgeBaseSchema = z.object({
  id: z.string().uuid(),
  userId: z.string().uuid(),
  section: knowledgeBaseSectionSchema,
  version: z.number().int().positive(),
  isActive: z.boolean(),
  source: z.string().nullable().optional(),
  content: jsonObjectSchema.default({}),
  updatedByProfileId: z.string().uuid().nullable().optional(),
});

export const apiErrorSchema = z.object({
  code: z.string().min(1),
  detail: z.string().min(1),
});

export const apiMetaSchema = z.object({
  generatedAtUtc: isoDateTimeSchema,
  seeded: z.boolean().optional(),
});

export const coachingStateSchema = z.object({
  knowledgeBaseSections: z.array(knowledgeBaseSchema),
  planBlocks: z.array(planBlockSchema),
  plannedWorkouts: z.array(plannedWorkoutSchema),
});

export const coachingStateEnvelopeSchema = z.object({
  data: coachingStateSchema,
  meta: apiMetaSchema,
  errors: z.array(apiErrorSchema),
});

export const knowledgeBaseUpdateInputSchema = z.object({
  source: z.string().min(1).nullable().optional(),
  content: jsonObjectSchema,
});

export const plannedWorkoutOverrideInputSchema = z.object({
  planBlockId: z.string().uuid().nullable().optional(),
  title: z.string().min(1),
  workoutType: z.string().min(1),
  status: plannedWorkoutStatusSchema.default('planned'),
  plannedDurationMin: z.number().int().positive().nullable().optional(),
  intensityTarget: z.string().nullable().optional(),
  structuredWorkout: jsonObjectSchema,
  source: z.string().min(1).nullable().optional(),
});

// Today-card actions (Batch 29). Edit reuses the same duration/intensity dials as
// the same-day override; Swap day takes the target calendar date.
export const todayCardEditInputSchema = z.object({
  durationScalePct: z.number().int().min(50).max(125).nullable().optional(),
  intensityScalePct: z.number().int().min(50).max(120).nullable().optional(),
});

export const todayCardSwapInputSchema = z.object({
  targetDate: isoDateSchema,
});

export const dayCategorySchema = z.enum(['cycle', 'weights', 'flexibility', 'rest']);

export const planActionWorkoutSchema = z.object({
  id: z.string().uuid(),
  workoutDate: isoDateSchema,
  version: z.number().int(),
  title: z.string().min(1),
  workoutType: z.string().min(1),
  status: z.string().min(1),
  plannedDurationMin: z.number().int().nullable().optional(),
  intensityTarget: z.string().nullable().optional(),
  source: z.string().nullable().optional(),
});

export const planDayStateSchema = z.object({
  categories: z.array(dayCategorySchema),
  label: z.string().min(1),
  isRest: z.boolean(),
});

export const planScheduleDaySchema = z.object({
  date: isoDateSchema,
  dayState: planDayStateSchema,
  workouts: z.array(planActionWorkoutSchema),
});

export const planScheduleEnvelopeSchema = z.object({
  data: z.object({
    startDate: isoDateSchema,
    days: z.number().int(),
    schedule: z.array(planScheduleDaySchema),
  }),
  meta: apiMetaSchema,
  errors: z.array(apiErrorSchema),
});

export const planAddWorkoutInputSchema = z.object({
  category: z.enum(['cycle', 'weights', 'flexibility']),
});

export const planSwapIntoDateInputSchema = z.object({
  plannedWorkoutId: z.string().uuid(),
});

export const planRecordActualInputSchema = z.object({
  label: z.string().min(1).max(120),
  notes: z.string().nullable().optional(),
});

export const dailyLoopWarningSchema = z.object({
  id: z.string().min(1),
  summary: z.string().min(1),
  reason: z.string().min(1),
  status: z.enum(['info', 'active']),
  detail: z.string().nullable().optional(),
});

export const metricBaselineRowSchema = z.object({
  metricKey: z.string().min(1),
  label: z.string().min(1),
  currentValue: z.number().nullable().optional(),
  baselineMedian: z.number().nullable().optional(),
  baselineMean: z.number().nullable().optional(),
  deltaVsBaseline: z.number().nullable().optional(),
  lowerQuartile: z.number().nullable().optional(),
  upperQuartile: z.number().nullable().optional(),
  sampleCount: z.number().int().optional(),
  excludedSampleCount: z.number().int().optional(),
  reliabilityStartDate: z.string().nullable().optional(),
});

export const ageComparisonRowSchema = z.object({
  metricKey: z.string().min(1),
  label: z.string().min(1),
  value: z.number(),
  unit: z.string().default(''),
  ageAverage: z.number(),
  ageBand: z.string().min(1),
  betterDirection: z.enum(['higher', 'lower']),
  tone: z.enum(['good', 'warn', 'neutral']),
  descriptor: z.string().min(1),
});

export const ageComparisonSchema = z.object({
  age: z.number().int().nullable().optional(),
  ageBand: z.string().nullable().optional(),
  fitnessAge: z.number().int().nullable().optional(),
  fitnessAgeDelta: z.number().int().nullable().optional(),
  fitnessAgeTone: z.enum(['good', 'warn', 'neutral']).nullable().optional(),
  rows: z.array(ageComparisonRowSchema).default([]),
});

export const dailyLoopAnalysisSchema = z.object({
  id: z.string().uuid(),
  generatedAtUtc: isoDateTimeSchema,
  verdict: verdictSchema,
  promptVersion: z.string().min(1),
  modelName: z.string().nullable().optional(),
  outputMarkdown: z.string(),
  planAdjustments: z.array(z.string()).default([]),
  reasons: z.array(z.string()).default([]),
  readinessInterpretation: z.string().nullable().optional(),
  thermalReview: jsonObjectSchema.default({}),
  metricsVsBaselines: z.array(metricBaselineRowSchema).default([]),
  ageComparison: ageComparisonSchema.default({ rows: [] }),
});

export const dailyLoopPostWorkoutAnalysisSchema = z.object({
  id: z.string().uuid(),
  activityId: z.string().uuid().nullable().optional(),
  activityName: z.string().nullable().optional(),
  activityType: z.string().nullable().optional(),
  generatedAtUtc: isoDateTimeSchema,
  promptVersion: z.string().min(1),
  modelName: z.string().nullable().optional(),
  outputMarkdown: z.string(),
  recoveryDecision: jsonObjectSchema.default({}),
  timeSeriesSummary: jsonObjectSchema.default({}),
  tomorrowImpact: z.string().nullable().optional(),
  postRideCheckIn: manualEntrySchema.nullable().optional(),
});

export const dailyLoopDeliverySchema = z.object({
  // The live Zwift event for the slot (push-on-plan-set delivers the baseline).
  liveStatus: z.string().nullable(),
  liveOrigin: z.string().nullable(),
  intervalsEventId: z.string().nullable(),
  // True when an un-acted coach adjustment is waiting → the card's "changes" state.
  changed: z.boolean(),
  adjustment: jsonObjectSchema.nullable(),
});

export const dailyLoopPlannedWorkoutSchema = plannedWorkoutSchema.extend({
  adherence: manualEntrySchema.nullable().optional(),
  delivery: dailyLoopDeliverySchema.nullable().optional(),
});

export const dailyLoopFanSchema = z.object({
  autoEnabled: z.boolean(),
  // 'manual' (auto off) | 'control' | 'winddown' | 'idle' (overnight phases).
  mode: z.string().min(1),
  // The autopilot's intended on/off; null when unknown (manual, or no fresh temp).
  isOn: z.boolean().nullable(),
  speed: z.number().int().nullable(),
  respondingToC: z.number().nullable(),
});

export const dailyLoopThermalStateSchema = z.object({
  latestTemperatureC: z.number().nullable().optional(),
  targetTemperatureC: z.number().nullable().optional(),
  capturedAtUtc: isoDateTimeSchema.nullable().optional(),
  overnightLowC: z.number().nullable().optional(),
  overnightWindMaxMph: z.number().nullable().optional(),
  overnightWindGustMph: z.number().nullable().optional(),
  thermalReview: jsonObjectSchema.default({}),
  fan: dailyLoopFanSchema,
});

export const fanAutoInputSchema = z.object({
  enabled: z.boolean(),
});

export const fanCommandInputSchema = z.object({
  power: z.boolean().nullable().optional(),
  speed: z.number().int().min(1).max(9).nullable().optional(),
});

export const fanEnvelopeSchema = z.object({
  data: z.object({
    autoEnabled: z.boolean(),
    isOn: z.boolean().nullable().optional(),
    speed: z.number().int().nullable().optional(),
  }),
  meta: apiMetaSchema,
  errors: z.array(apiErrorSchema),
});

// Overnight bedroom chart (Batch 31) — GET /api/v1/bedroom/overnight.
export const bedroomTemperaturePointSchema = z.object({
  t: isoDateTimeSchema,
  c: z.number(),
});

export const bedroomFanPointSchema = z.object({
  t: isoDateTimeSchema,
  on: z.boolean().nullable(),
  speed: z.number().int().nullable(),
  // apply | hold | no_data | auto_off | unreachable | winddown
  action: z.string().min(1),
  reason: z.string().nullable(),
  observedTempC: z.number().nullable(),
  autoEnabled: z.boolean(),
});

export const bedroomSleepStageSpanSchema = z.object({
  start: isoDateTimeSchema,
  end: isoDateTimeSchema,
  // deep | light | rem | awake | unknown
  stage: z.string().min(1),
});

export const bedroomOvernightSleepSchema = z.object({
  start: isoDateTimeSchema.nullable(),
  end: isoDateTimeSchema.nullable(),
  score: z.number().int().nullable(),
  ageAdjustedScore: z.number().int().nullable(),
  durationSec: z.number().int().nullable(),
  awakeSec: z.number().int().nullable(),
  restlessMoments: z.number().int().nullable(),
  stages: z.array(bedroomSleepStageSpanSchema).default([]),
});

export const bedroomOvernightThresholdsSchema = z.object({
  onC: z.number(),
  criticalC: z.number(),
});

export const bedroomOvernightSummarySchema = z.object({
  minTempC: z.number().nullable(),
  maxTempC: z.number().nullable(),
  fanRanMinutes: z.number().int(),
  peakSpeed: z.number().int().nullable(),
});

export const bedroomOvernightSchema = z.object({
  night: isoDateSchema,
  timezone: z.string().min(1),
  windowStartUtc: isoDateTimeSchema,
  windowEndUtc: isoDateTimeSchema,
  thresholds: bedroomOvernightThresholdsSchema,
  temperature: z.array(bedroomTemperaturePointSchema),
  fan: z.array(bedroomFanPointSchema),
  sleep: bedroomOvernightSleepSchema.nullable(),
  summary: bedroomOvernightSummarySchema.nullable(),
  nights: z.array(isoDateSchema),
});

export const bedroomOvernightEnvelopeSchema = z.object({
  data: bedroomOvernightSchema,
  meta: apiMetaSchema,
  errors: z.array(apiErrorSchema),
});

export const dailyLoopSchema = z.object({
  subjectDate: isoDateSchema,
  timezone: z.string().min(1),
  morningAnalysis: dailyLoopAnalysisSchema.nullable(),
  dailyMetrics: dailyMetricSchema.nullable(),
  sleep: sleepSchema.nullable(),
  manualEntry: manualEntrySchema.nullable(),
  postWorkoutAnalyses: z.array(dailyLoopPostWorkoutAnalysisSchema).default([]),
  plannedWorkouts: z.array(dailyLoopPlannedWorkoutSchema),
  thermalState: dailyLoopThermalStateSchema,
  dataQualityWarnings: z.array(dailyLoopWarningSchema),
});

export const dailyLoopEnvelopeSchema = z.object({
  data: dailyLoopSchema,
  meta: apiMetaSchema,
  errors: z.array(apiErrorSchema),
});

export const workoutDeliveryStatusSchema = z.enum(['proposed', 'approved', 'pushed', 'failed']);

export const workoutDeliveryProposalSchema = z.object({
  id: z.string().uuid(),
  userId: z.string().uuid(),
  plannedWorkoutId: z.string().uuid().nullable(),
  plannedWorkoutVersion: z.number().int(),
  workoutDate: isoDateSchema,
  provider: z.string().min(1),
  status: workoutDeliveryStatusSchema,
  proposedAtUtc: isoDateTimeSchema,
  approvedAtUtc: isoDateTimeSchema.nullable(),
  approvedByProfileId: z.string().uuid().nullable(),
  pushedAtUtc: isoDateTimeSchema.nullable(),
  intervalsEventId: z.string().nullable(),
  structuredWorkoutIr: jsonObjectSchema.default({}),
  intervalsPayload: jsonObjectSchema.default({}),
  zwoXml: z.string(),
  lastError: z.string().nullable(),
});

export const workoutDeliveryEnvelopeSchema = z.object({
  data: z.object({ proposals: z.array(workoutDeliveryProposalSchema) }),
  meta: apiMetaSchema,
  errors: z.array(apiErrorSchema),
});

export const weekAheadWorkoutSchema = z.object({
  plannedWorkoutId: z.string().uuid(),
  workoutDate: isoDateSchema,
  version: z.number().int(),
  title: z.string().min(1),
  workoutType: z.string().min(1),
  status: z.string().min(1),
  plannedDurationMin: z.number().int().nullable().optional(),
  intensityTarget: z.string().nullable().optional(),
  deliverable: z.boolean(),
  proposal: workoutDeliveryProposalSchema.nullable(),
});

export const weekAheadEnvelopeSchema = z.object({
  data: z.object({
    startDate: isoDateSchema,
    days: z.number().int(),
    workouts: z.array(weekAheadWorkoutSchema),
  }),
  meta: apiMetaSchema,
  errors: z.array(apiErrorSchema),
});

export const holidayWindowSchema = z.object({
  startDate: isoDateSchema,
  endDate: isoDateSchema,
  pausedAtUtc: z.string().min(1),
  resumedAtUtc: z.string().nullable(),
  isActive: z.boolean(),
});

export const holidayEnvelopeSchema = z.object({
  data: z.object({
    windows: z.array(holidayWindowSchema),
    activeWindow: holidayWindowSchema.nullable(),
  }),
  meta: apiMetaSchema,
  errors: z.array(apiErrorSchema),
});

export const pauseInputSchema = z.object({
  startDate: isoDateSchema,
  endDate: isoDateSchema,
});

export const pauseEnvelopeSchema = z.object({
  data: z.object({
    window: holidayWindowSchema,
    skippedCount: z.number().int(),
  }),
  meta: apiMetaSchema,
  errors: z.array(apiErrorSchema),
});

export const resumeEnvelopeSchema = z.object({
  data: z.object({
    window: holidayWindowSchema,
    continuationLabel: z.string().min(1),
    regeneratedCount: z.number().int(),
  }),
  meta: apiMetaSchema,
  errors: z.array(apiErrorSchema),
});

// --- Batch 16: app-generated 13-week blocks -------------------------------

export const generatedBlockWorkoutSchema = z.object({
  dayOffset: z.number().int(),
  workoutDate: isoDateSchema,
  title: z.string().min(1),
  workoutType: z.string().min(1),
  plannedDurationMin: z.number().int().nullable().optional(),
  intensityTarget: z.string().nullable().optional(),
  structuredWorkout: jsonObjectSchema.default({}),
});

export const generatedBlockWeekSchema = z.object({
  weekNumber: z.number().int().positive(),
  blockType: z.string().min(1),
  label: z.string().min(1),
  focus: z.string().optional(),
  startDate: isoDateSchema,
  endDate: isoDateSchema,
  workouts: z.array(generatedBlockWorkoutSchema),
});

export const generatedBlockDraftSchema = z.object({
  status: z.enum(['draft', 'locked']),
  framework: z.string().min(1),
  startDate: isoDateSchema,
  endDate: isoDateSchema,
  ftpWatts: z.number().int().positive(),
  athleteName: z.string().min(1),
  generatedAtUtc: z.string().min(1),
  lockedAtUtc: z.string().nullable(),
  weeks: z.array(generatedBlockWeekSchema),
});

export const blockGeneratorEnvelopeSchema = z.object({
  data: z.object({
    draft: generatedBlockDraftSchema.nullable(),
    canGenerate: z.boolean(),
  }),
  meta: apiMetaSchema,
  errors: z.array(apiErrorSchema),
});

export const generateBlockInputSchema = z.object({
  startDate: isoDateSchema.nullable().optional(),
  ftpWatts: z.number().int().positive().nullable().optional(),
});

export const refineBlockInputSchema = z.object({
  weekNumber: z.number().int().positive(),
  dayOffset: z.number().int().nonnegative(),
  title: z.string().min(1).nullable().optional(),
  workoutType: z.string().min(1).nullable().optional(),
  plannedDurationMin: z.number().int().positive().nullable().optional(),
  intensityTarget: z.string().nullable().optional(),
  structuredWorkout: jsonObjectSchema.nullable().optional(),
});

export const blockLockEnvelopeSchema = z.object({
  data: z.object({
    blocksCreated: z.number().int(),
    workoutsWritten: z.number().int(),
    startDate: isoDateSchema,
    endDate: isoDateSchema,
  }),
  meta: apiMetaSchema,
  errors: z.array(apiErrorSchema),
});

// --- Weekly & monthly deep reviews (Batch 20) ---

export const reviewPeriodSchema = z.enum(['weekly', 'monthly']);

export const reviewRollupSchema = z.object({
  sleep: z.object({
    nights: z.number().int(),
    avgScore: z.number().nullable(),
    avgAgeAdjustedScore: z.number().nullable(),
    avgDurationMin: z.number().nullable(),
    avgDeepMin: z.number().nullable(),
    avgRemMin: z.number().nullable(),
    trend: z.string(),
  }),
  recovery: z.object({
    days: z.number().int(),
    avgHrvMs: z.number().nullable(),
    avgReadiness: z.number().nullable(),
    avgRestingHrBpm: z.number().nullable(),
    avgBodyBatteryCharged: z.number().nullable(),
    trend: z.string(),
  }),
  trainingLoad: z.object({
    activityCount: z.number().int(),
    totalLoad: z.number(),
    totalDurationMin: z.number().int(),
    byType: z.record(z.number()),
  }),
  adherence: z.object({
    plannedCount: z.number().int(),
    capturedCount: z.number().int(),
    statusCounts: z.record(z.number()),
  }),
  verdicts: z.object({
    green: z.number().int(),
    amber: z.number().int(),
    red: z.number().int(),
    total: z.number().int(),
  }),
  thermal: z.object({
    nights: z.number().int(),
    avgIndoorPeakC: z.number().nullable(),
    avgOvernightLowC: z.number().nullable(),
    disruptionNights: z.number().int(),
  }),
});

export const storedReviewSchema = z.object({
  generatedAtUtc: z.string().min(1),
  modelName: z.string().nullable(),
  promptVersion: z.string(),
  markdown: z.string(),
});

export const reviewEnvelopeSchema = z.object({
  data: z.object({
    period: reviewPeriodSchema,
    periodStart: isoDateSchema,
    periodEnd: isoDateSchema,
    dayCount: z.number().int(),
    rollup: reviewRollupSchema,
    strength: z.object({
      trend: z.string(),
      sessions4w: z.number().int(),
      sessionsPerWeek4w: z.number(),
      sessions12w: z.number().int(),
    }),
    insights: z.object({
      ftpDriftStatus: z.string(),
      earlyWarningStatus: z.string(),
      earlyWarningFired: z.boolean(),
    }),
    review: storedReviewSchema.nullable(),
  }),
  meta: apiMetaSchema,
  errors: z.array(apiErrorSchema),
});

// --- Year-on-year & seasonal trends (Batch 21) ---

export const trendBucketSchema = z.enum(['month', 'season']);

export const trendMetricSummarySchema = z.object({
  metricKey: z.string(),
  label: z.string(),
  sampleCount: z.number().int(),
  excludedCount: z.number().int(),
  mean: z.number().nullable(),
  median: z.number().nullable(),
  min: z.number().nullable(),
  max: z.number().nullable(),
});

export const trendWindowSchema = z.object({
  bucket: trendBucketSchema,
  key: z.string(),
  label: z.string(),
  start: isoDateSchema,
  end: isoDateSchema,
  sampleDays: z.number().int(),
  metrics: z.array(trendMetricSummarySchema),
});

export const trendsSeasonalEnvelopeSchema = z.object({
  data: z.object({
    bucket: trendBucketSchema,
    windows: z.array(trendWindowSchema),
  }),
  meta: apiMetaSchema,
  errors: z.array(apiErrorSchema),
});

export const yearOnYearMetricSchema = z.object({
  metricKey: z.string(),
  label: z.string(),
  currentMean: z.number().nullable(),
  priorMean: z.number().nullable(),
  delta: z.number().nullable(),
  pctChange: z.number().nullable(),
  currentSampleCount: z.number().int(),
  priorSampleCount: z.number().int(),
  status: z.string(),
});

export const yearOnYearSchema = z.object({
  bucket: trendBucketSchema,
  status: z.string(),
  currentKey: z.string().nullable(),
  priorKey: z.string().nullable(),
  currentLabel: z.string().nullable(),
  priorLabel: z.string().nullable(),
  metrics: z.array(yearOnYearMetricSchema),
  reasons: z.array(z.string()),
});

export const trendsYearOnYearEnvelopeSchema = z.object({
  data: yearOnYearSchema,
  meta: apiMetaSchema,
  errors: z.array(apiErrorSchema),
});

export const storedTrendNarrativeSchema = z.object({
  generatedAtUtc: z.string().min(1),
  modelName: z.string().nullable(),
  promptVersion: z.string(),
  markdown: z.string(),
});

export const trendsNarrativeEnvelopeSchema = z.object({
  data: z.object({
    bucket: trendBucketSchema,
    targetKey: z.string(),
    subjectDate: isoDateSchema,
    yearOnYear: yearOnYearSchema,
    recentWindows: z.array(trendWindowSchema),
    status: z.string(),
    narrative: storedTrendNarrativeSchema.nullable(),
  }),
  meta: apiMetaSchema,
  errors: z.array(apiErrorSchema),
});

// --- Hypothesis evaluation (Batch 22) ---

export const experimentStatusSchema = z.enum(['active', 'paused', 'concluded']);

export const experimentOutSchema = z.object({
  id: z.string().uuid(),
  title: z.string(),
  hypothesis: z.string(),
  status: experimentStatusSchema,
  startDate: isoDateSchema.nullable(),
  endDate: isoDateSchema.nullable(),
  successCriteria: jsonObjectSchema.default({}),
  observations: jsonObjectSchema.default({}),
});

export const experimentListEnvelopeSchema = z.object({
  data: z.array(experimentOutSchema),
  meta: apiMetaSchema,
  errors: z.array(apiErrorSchema),
});

export const experimentEnvelopeSchema = z.object({
  data: experimentOutSchema,
  meta: apiMetaSchema,
  errors: z.array(apiErrorSchema),
});

export const evaluationRecommendationSchema = z.enum(['supported', 'refuted', 'inconclusive']);

export const storedEvaluationSchema = z.object({
  generatedAtUtc: z.string().min(1),
  subjectDate: isoDateSchema,
  recommendation: evaluationRecommendationSchema.nullable(),
  markdown: z.string(),
});

export const experimentEvaluationEnvelopeSchema = z.object({
  data: z.object({
    experimentId: z.string().uuid(),
    title: z.string(),
    status: experimentStatusSchema,
    slug: z.string().nullable(),
    kind: z.string(),
    evaluationStatus: z.string(),
    recommendation: evaluationRecommendationSchema.nullable(),
    sampleCount: z.number().int(),
    windowStart: isoDateSchema.nullable(),
    windowEnd: isoDateSchema.nullable(),
    evidence: jsonObjectSchema.default({}),
    reasons: z.array(z.string()),
    canConclude: z.boolean(),
    stored: storedEvaluationSchema.nullable(),
  }),
  meta: apiMetaSchema,
  errors: z.array(apiErrorSchema),
});

// --- Auto-generated handover-doc export (Batch 23) ---

export const storedHandoverSchema = z.object({
  generatedAtUtc: z.string().min(1),
  modelName: z.string().nullable(),
  promptVersion: z.string(),
  markdown: z.string(),
});

export const handoverEnvelopeSchema = z.object({
  data: z.object({
    subjectDate: isoDateSchema,
    // The assembled retained-state packet is deliberately freeform — it composes
    // KB, plan, baselines, reviews, trends, experiments and the strength brief.
    packet: jsonObjectSchema.default({}),
    markdown: z.string(),
    export: storedHandoverSchema.nullable(),
  }),
  meta: apiMetaSchema,
  errors: z.array(apiErrorSchema),
});
