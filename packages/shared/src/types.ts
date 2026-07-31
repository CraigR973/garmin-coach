import { z } from 'zod';

import {
  activitySchema,
  activityTimeSeriesSchema,
  analysisSchema,
  blockProgressionProposalSchema,
  briefMessageInputSchema,
  briefMessageRoleSchema,
  briefMessageSchema,
  briefMessageTurnSchema,
  coachMessageInputSchema,
  coachOriginKindSchema,
  conversationLearningEvidenceSchema,
  conversationLearningKindSchema,
  conversationLearningProposalSchema,
  dailyMetricSchema,
  experimentSchema,
  feedbackInputSchema,
  feedbackKindSchema,
  feedbackRatingSchema,
  feedbackReasonTagSchema,
  feedbackSchema,
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
export type Feedback = z.infer<typeof feedbackSchema>;
export type FeedbackInput = z.infer<typeof feedbackInputSchema>;
export type FeedbackKind = z.infer<typeof feedbackKindSchema>;
export type FeedbackRating = z.infer<typeof feedbackRatingSchema>;
export type FeedbackReasonTag = z.infer<typeof feedbackReasonTagSchema>;
export type BriefMessageRole = z.infer<typeof briefMessageRoleSchema>;
export type BriefMessage = z.infer<typeof briefMessageSchema>;
export type BriefMessageInput = z.infer<typeof briefMessageInputSchema>;
export type BriefMessageTurn = z.infer<typeof briefMessageTurnSchema>;
export type CoachOriginKind = z.infer<typeof coachOriginKindSchema>;
export type CoachMessageInput = z.infer<typeof coachMessageInputSchema>;
export type ConversationLearningKind = z.infer<typeof conversationLearningKindSchema>;
export type ConversationLearningEvidence = z.infer<typeof conversationLearningEvidenceSchema>;
export type ConversationLearningProposal = z.infer<typeof conversationLearningProposalSchema>;
export type Experiment = z.infer<typeof experimentSchema>;
export type KnowledgeBase = z.infer<typeof knowledgeBaseSchema>;
export type BlockProgressionProposal = z.infer<typeof blockProgressionProposalSchema>;
export type GeneratedBlockWorkout = z.infer<typeof generatedBlockWorkoutSchema>;
export type GeneratedBlockWeek = z.infer<typeof generatedBlockWeekSchema>;
export type GeneratedBlockDraft = z.infer<typeof generatedBlockDraftSchema>;
