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
  entryDate: isoDateSchema,
  entryAtUtc: isoDateTimeSchema,
  bpSystolic: z.number().int().nullable().optional(),
  bpDiastolic: z.number().int().nullable().optional(),
  subjectiveScore: z.number().int().min(1).max(10).nullable().optional(),
  rpe: z.number().min(0).max(10).nullable().optional(),
  feel: z.string().nullable().optional(),
  supplementsJson: jsonObjectSchema.default({}),
  foodJson: jsonObjectSchema.default({}),
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
