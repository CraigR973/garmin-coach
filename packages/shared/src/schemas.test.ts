import { describe, expect, it } from 'vitest';

import {
  activityTimeSeriesSchema,
  ageComparisonRowSchema,
  coachingStateEnvelopeSchema,
  dailyLoopAnalysisSchema,
  dailyLoopEnvelopeSchema,
  dailyLoopPostWorkoutAnalysisSchema,
  dailyMetricSchema,
  knowledgeBaseUpdateInputSchema,
  plannedWorkoutOverrideInputSchema,
  profileSchema,
  rideIntervalSchema,
  sleepSchema,
  swapSuggestionSchema,
  weatherDailySchema,
} from './schemas';

const userId = '11111111-1111-4111-8111-111111111111';
const rowId = '22222222-2222-4222-8222-222222222222';

describe('v1 shared schemas', () => {
  it('parses interval-resolved ride execution and defaults intervals/execution', () => {
    const parsed = dailyLoopPostWorkoutAnalysisSchema.parse({
      id: rowId,
      generatedAtUtc: '2026-07-03T12:20:00Z',
      promptVersion: 'post-workout-analysis-v2-2026-07-03',
      outputMarkdown: '**Rating:** strong.',
      intervals: [
        {
          index: 1,
          label: 'Sweet spot',
          role: 'work',
          durationSec: 1200,
          pctFtp: 91,
          targetPctFtpLow: 91,
          targetPctFtpHigh: 91,
          adherence: 'on',
          fade: false,
        },
      ],
      execution: { hasPlan: true, workIntervalCount: 1 },
    });
    expect(parsed.intervals[0].adherence).toBe('on');
    expect(parsed.execution.workIntervalCount).toBe(1);

    // Both default when absent, so a free ride or a legacy payload still parses.
    const bare = dailyLoopPostWorkoutAnalysisSchema.parse({
      id: rowId,
      generatedAtUtc: '2026-07-03T12:20:00Z',
      promptVersion: 'post-workout-analysis-v2-2026-07-03',
      outputMarkdown: '**Rating:** solid.',
    });
    expect(bare.intervals).toEqual([]);
    expect(bare.execution).toEqual({});

    expect(() => rideIntervalSchema.parse({ index: 0, label: 'x', role: 'work', durationSec: 10 })).not.toThrow();
    expect(() =>
      rideIntervalSchema.parse({ index: 0, label: 'x', role: 'work', durationSec: 10, adherence: 'bogus' }),
    ).toThrow();
  });

  it('accepts the seeded private profile shape', () => {
    const parsed = profileSchema.parse({
      id: userId,
      displayName: 'Mark',
      role: 'admin',
      timezone: 'Europe/London',
      garminUserProfilePk: 9048542,
      hiveHomeId: 'aa1fbb37-6b65-4622-b609-5d75534fafd3',
      latitude: 55.6045,
      longitude: -4.5249,
    });

    expect(parsed.role).toBe('admin');
    expect(parsed.timezone).toBe('Europe/London');
  });

  it('keeps Garmin readiness recovery time in minutes', () => {
    const parsed = dailyMetricSchema.parse({
      id: rowId,
      userId,
      calendarDate: '2026-06-18',
      recordedAtUtc: '2026-06-18T06:30:00.000Z',
      readinessScore: 82,
      readinessLevel: 'HIGH',
      recoveryTimeMin: 540,
      rawPayload: { source: 'training_readiness.json' },
    });

    expect(parsed.recoveryTimeMin).toBe(540);
  });

  it('accepts the daily-loop breathwork brief shape', () => {
    const parsed = dailyLoopEnvelopeSchema.parse({
      data: {
        subjectDate: '2026-07-02',
        timezone: 'Europe/London',
        loopState: {
          dayPhase: 'wind_down',
          blockPhase: 'consolidation',
          nextAction: 'wind_down',
          atBlockBoundary: true,
        },
        morningAnalysis: null,
        dailyMetrics: null,
        sleep: null,
        manualEntry: null,
        postWorkoutAnalyses: [],
        postFlexibilityAnalyses: [],
        postWalkAnalyses: [],
        plannedWorkouts: [],
        thermalState: {
          fan: {
            autoEnabled: true,
            mode: 'idle',
            isOn: null,
            speed: null,
            respondingToC: null,
          },
        },
        sleepProjection: {
          status: 'personalized',
          tone: 'protect',
          headline: "Protect tonight's wind-down",
          summary: 'Hard late session plus warm room may make sleep more fragile.',
          evidence: ['Latest session started 18:05.'],
          prepActions: ['Let Auto manage the pre-cool.'],
          protocol: { bedtime: '23:15' },
        },
        chronicSuggestions: {
          status: 'active',
          headline: 'Chronic sleep patterns to work on',
          summary: '1 repeated pattern stood out across 24 recent nights.',
          evidenceWindow: {
            startDate: '2026-06-05',
            endDate: '2026-07-02',
            weeks: 4,
            nightsObserved: 24,
            nightsRequired: 21,
          },
          items: [
            {
              id: 'chronic-rem_sleep_pct',
              metricKey: 'rem_sleep_pct',
              label: 'REM',
              title: 'Protect REM consistency',
              summary: 'REM has repeatedly missed its age norm.',
              tone: 'watch',
              priority: 1,
              evidence: ['14 of 24 measured nights missed typical value.'],
              actions: ['Make 23:15 the latest normal lights-out target.'],
              driver: {
                driver: 'prev_day_training_load',
                label: 'training load',
                coefficient: -0.61,
                sampleCount: 18,
                summary: 'Higher load nights averaged 5 points lower sleep score.',
              },
            },
          ],
        },
        dataQualityWarnings: [],
        walkingBrief: {
          asOfDate: '2026-07-02',
          window4w: {
            sessionCount: 0,
            totalDistanceM: 0,
            totalDurationMin: 0,
            sessionsPerWeek: 0,
          },
          window12w: {
            sessionCount: 0,
            totalDistanceM: 0,
            totalDurationMin: 0,
            sessionsPerWeek: 0,
          },
          recentSessions: [],
          trend: 'insufficient_data',
          trendReason: 'Only 0 walks.',
        },
        breathworkBrief: {
          asOfDate: '2026-07-02',
          window4w: {
            sessionCount: 18,
            totalDurationMin: 54,
            sessionsPerWeek: 4.5,
          },
          window12w: {
            sessionCount: 54,
            totalDurationMin: 162,
            sessionsPerWeek: 4.5,
          },
          recentSessions: [],
          trend: 'stable',
          trendReason: 'Frequency holding at ~4.5/wk over 28 days.',
        },
      },
      meta: { generatedAtUtc: '2026-07-02T06:30:00Z' },
      errors: [],
    });

    expect(parsed.data.breathworkBrief?.window4w.sessionCount).toBe(18);
    expect(parsed.data.sleepProjection?.tone).toBe('protect');
    expect(parsed.data.chronicSuggestions?.items[0]?.driver?.label).toBe('training load');
    expect(parsed.data.loopState?.dayPhase).toBe('wind_down');
    expect(parsed.data.loopState?.atBlockBoundary).toBe(true);
  });

  it('accepts the daily-loop post-strength analysis shape', () => {
    const parsed = dailyLoopEnvelopeSchema.parse({
      data: {
        subjectDate: '2026-07-02',
        timezone: 'Europe/London',
        morningAnalysis: null,
        dailyMetrics: null,
        sleep: null,
        manualEntry: null,
        postWorkoutAnalyses: [],
        postFlexibilityAnalyses: [],
        postStrengthAnalyses: [
          {
            id: '55555555-5555-4555-8555-555555555555',
            activityId: '66666666-6666-4666-8666-666666666666',
            activityName: 'Strength maintenance',
            activityType: 'strength_training',
            generatedAtUtc: '2026-07-02T08:15:00.000Z',
            promptVersion: 'post-strength-analysis-v1-2026-07-02',
            modelName: 'claude-test',
            outputMarkdown: '**Strength read:** solid session.',
            heartRateReview: { avgHeartRateBpm: 96, avgAboveRestingBpm: 51 },
            consistency: { sessions4w: 6, trend: 'stable' },
            activityCheckIn: null,
          },
        ],
        postWalkAnalyses: [],
        plannedWorkouts: [],
        thermalState: {
          fan: {
            autoEnabled: true,
            mode: 'idle',
            isOn: null,
            speed: null,
            respondingToC: null,
          },
        },
        dataQualityWarnings: [],
      },
      meta: { generatedAtUtc: '2026-07-02T08:15:00Z' },
      errors: [],
    });

    expect(parsed.data.postStrengthAnalyses[0]?.consistency.sessions4w).toBe(6);
  });

  it('carries the plannedWorkoutId link on a completed ride analysis (Batch 60)', () => {
    const parsed = dailyLoopEnvelopeSchema.parse({
      data: {
        subjectDate: '2026-07-06',
        timezone: 'Europe/London',
        morningAnalysis: null,
        dailyMetrics: null,
        sleep: null,
        manualEntry: null,
        postWorkoutAnalyses: [
          {
            id: '11111111-1111-4111-8111-111111111111',
            activityId: '22222222-2222-4222-8222-222222222222',
            plannedWorkoutId: '33333333-3333-4333-8333-333333333333',
            activityName: 'Tempo ride',
            activityType: 'indoor_cycling',
            generatedAtUtc: '2026-07-06T12:20:00.000Z',
            promptVersion: 'post-workout-analysis-v2-2026-07-03',
            modelName: 'claude-test',
            outputMarkdown: '**Rating:** strong.',
            tomorrowImpact: 'Easy endurance tomorrow.',
          },
        ],
        postFlexibilityAnalyses: [],
        postStrengthAnalyses: [],
        postWalkAnalyses: [],
        plannedWorkouts: [],
        thermalState: {
          fan: { autoEnabled: true, mode: 'idle', isOn: null, speed: null, respondingToC: null },
        },
        dataQualityWarnings: [],
      },
      meta: { generatedAtUtc: '2026-07-06T12:20:00Z' },
      errors: [],
    });

    expect(parsed.data.postWorkoutAnalyses[0]?.plannedWorkoutId).toBe(
      '33333333-3333-4333-8333-333333333333',
    );
  });

  it('stores age-adjusted sleep separately from Garmin score', () => {
    const parsed = sleepSchema.parse({
      id: rowId,
      userId,
      calendarDate: '2026-06-18',
      score: 70,
      ageAdjustedScore: 74,
      remSleepSec: 3780,
      factorsJson: {},
      rawPayload: {},
    });

    expect(parsed.score).toBe(70);
    expect(parsed.ageAdjustedScore).toBe(74);
  });

  it('parses an age-comparison row with a healthy band and defaults it for legacy payloads (Batch 61)', () => {
    const banded = ageComparisonRowSchema.parse({
      metricKey: 'rem_sleep_pct',
      label: 'REM',
      value: 16,
      unit: '%',
      ageAverage: 19,
      ageBand: '50–59',
      betterDirection: 'higher',
      tone: 'good',
      descriptor: 'Healthy for your age',
      bandLow: 15,
      bandHigh: 23,
      garminTargetLow: 21,
      garminTargetHigh: 31,
    });
    expect(banded.bandLow).toBe(15);
    expect(banded.bandHigh).toBe(23);
    expect(banded.garminTargetLow).toBe(21);
    expect(banded.garminTargetHigh).toBe(31);

    // A pre-Batch-61 payload has no band keys; they default to null and parse.
    const legacy = ageComparisonRowSchema.parse({
      metricKey: 'vo2max',
      label: 'VO₂max',
      value: 54,
      unit: '',
      ageAverage: 31,
      ageBand: '50–59',
      betterDirection: 'higher',
      tone: 'good',
      descriptor: 'Much better than average',
    });
    expect(legacy.bandLow).toBeNull();
    expect(legacy.bandHigh).toBeNull();
    expect(legacy.garminTargetLow).toBeNull();
    expect(legacy.garminTargetHigh).toBeNull();
  });

  it('covers Performance Condition and Stamina time-series channels', () => {
    const parsed = activityTimeSeriesSchema.parse({
      id: rowId,
      activityId: '33333333-3333-4333-8333-333333333333',
      sampleIndex: 2,
      timestampUtc: '2026-06-18T08:00:10.000Z',
      powerWatts: 141,
      heartRateBpm: 80,
      performanceCondition: 21.26,
      availableStamina: 96,
      potentialStamina: 96,
      rawMetrics: { directPerformanceCondition: 21.26 },
    });

    expect(parsed.performanceCondition).toBeCloseTo(21.26);
    expect(parsed.availableStamina).toBe(96);
  });

  it('captures Kilmarnock daily weather and overnight wind context', () => {
    const parsed = weatherDailySchema.parse({
      id: rowId,
      userId,
      calendarDate: '2026-06-18',
      source: 'open_meteo',
      latitude: 55.6045,
      longitude: -4.5249,
      tempHighC: 17.8,
      tempLowC: 8.9,
      overnightLowC: 8.4,
      overnightWindMaxMph: 8,
      overnightWindGustMph: 15.5,
      windMaxMph: 14.2,
      windGustMph: 24.1,
      rawPayload: {},
    });

    expect(parsed.overnightWindGustMph).toBe(15.5);
  });

  it('parses the coaching-state envelope used by the internal editor', () => {
    const parsed = coachingStateEnvelopeSchema.parse({
      data: {
        knowledgeBaseSections: [
          {
            id: rowId,
            userId,
            section: 'profile',
            version: 1,
            isActive: true,
            source: 'batch_5_seed',
            content: { ftpWatts: 280, vo2max: 54 },
            updatedByProfileId: userId,
          },
        ],
        planBlocks: [
          {
            id: rowId,
            userId,
            name: 'Week 01 Build 1',
            version: 1,
            sequenceIndex: 1,
            blockType: 'build',
            startDate: '2026-06-22',
            endDate: '2026-06-28',
            goalsJson: { focus: 'Aerobic build' },
            rawPlan: {},
          },
        ],
        plannedWorkouts: [
          {
            id: rowId,
            userId,
            planBlockId: rowId,
            workoutDate: '2026-06-23',
            version: 1,
            title: 'VO2 Max 30/30',
            workoutType: 'bike_vo2',
            status: 'planned',
            isActive: true,
            plannedDurationMin: 60,
            intensityTarget: '105-110% FTP',
            structuredWorkout: { steps: [] },
            source: 'batch_5_seed',
          },
        ],
      },
      meta: {
        generatedAtUtc: '2026-06-20T09:00:00.000Z',
        seeded: true,
      },
      errors: [],
    });

    expect(parsed.data.knowledgeBaseSections[0]?.section).toBe('profile');
    expect(parsed.meta.seeded).toBe(true);
  });

  it('validates knowledge-base updates and workout override inputs', () => {
    const kb = knowledgeBaseUpdateInputSchema.parse({
      source: 'manual_edit',
      content: { bedtime: '23:15' },
    });
    const workout = plannedWorkoutOverrideInputSchema.parse({
      planBlockId: null,
      title: 'Sweet Spot Builder',
      workoutType: 'bike_sweet_spot',
      status: 'planned',
      plannedDurationMin: 75,
      intensityTarget: '88-94% FTP',
      structuredWorkout: { steps: [{ label: 'Main set', minutes: 24 }] },
      source: 'coach_override',
    });

    expect(kb.content.bedtime).toBe('23:15');
    expect(workout.structuredWorkout.steps).toHaveLength(1);
  });

  it('parses a swap-first suggestion and keeps it optional on the analysis (Batch 66)', () => {
    const swap = swapSuggestionSchema.parse({
      hardWorkoutId: rowId,
      hardTitle: 'VO2 30/15',
      hardCategory: 'vo2',
      moveToDate: '2026-07-11',
      moveToWeekday: 'Saturday',
      bringForwardTitle: 'Z2 + Neuromuscular',
    });
    expect(swap.moveToWeekday).toBe('Saturday');

    const withSwap = dailyLoopAnalysisSchema.parse({
      id: rowId,
      generatedAtUtc: '2026-07-08T06:30:00Z',
      verdict: 'amber',
      promptVersion: 'morning-analysis-v6-2026-07-08',
      outputMarkdown: '**Verdict:** Amber',
      swapSuggestion: swap,
    });
    expect(withSwap.swapSuggestion?.hardTitle).toBe('VO2 30/15');

    // A Green day carries no suggestion; the field is optional.
    const withoutSwap = dailyLoopAnalysisSchema.parse({
      id: rowId,
      generatedAtUtc: '2026-07-08T06:30:00Z',
      verdict: 'green',
      promptVersion: 'morning-analysis-v6-2026-07-08',
      outputMarkdown: '**Verdict:** Green',
    });
    expect(withoutSwap.swapSuggestion ?? null).toBeNull();
  });
});
