import { z } from 'zod';

import {
  activitySchema,
  activityTimeSeriesSchema,
  analysisSchema,
  blockProgressionProposalSchema,
  dailyMetricSchema,
  experimentSchema,
  generatedBlockDraftSchema,
  generatedBlockWeekSchema,
  generatedBlockWorkoutSchema,
  knowledgeBaseSchema,
  manualEntrySchema,
  planBlockSchema,
  plannedWorkoutSchema,
  profileSchema,
  roleSchema,
  sleepSchema,
  temperatureReadingSchema,
  weatherDailySchema,
} from './schemas';

export type Role = z.infer<typeof roleSchema>;
export type Profile = z.infer<typeof profileSchema>;
export type DailyMetric = z.infer<typeof dailyMetricSchema>;
export type Sleep = z.infer<typeof sleepSchema>;
export type Activity = z.infer<typeof activitySchema>;
export type ActivityTimeSeries = z.infer<typeof activityTimeSeriesSchema>;
export type TemperatureReading = z.infer<typeof temperatureReadingSchema>;
export type WeatherDaily = z.infer<typeof weatherDailySchema>;
export type ManualEntry = z.infer<typeof manualEntrySchema>;
export type PlanBlock = z.infer<typeof planBlockSchema>;
export type PlannedWorkout = z.infer<typeof plannedWorkoutSchema>;
export type Analysis = z.infer<typeof analysisSchema>;
export type Experiment = z.infer<typeof experimentSchema>;
export type KnowledgeBase = z.infer<typeof knowledgeBaseSchema>;
export type BlockProgressionProposal = z.infer<typeof blockProgressionProposalSchema>;
export type GeneratedBlockWorkout = z.infer<typeof generatedBlockWorkoutSchema>;
export type GeneratedBlockWeek = z.infer<typeof generatedBlockWeekSchema>;
export type GeneratedBlockDraft = z.infer<typeof generatedBlockDraftSchema>;
