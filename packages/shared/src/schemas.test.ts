import { describe, expect, it } from 'vitest';

import {
  activityTimeSeriesSchema,
  dailyMetricSchema,
  profileSchema,
  sleepSchema,
} from './schemas';

const userId = '11111111-1111-4111-8111-111111111111';
const rowId = '22222222-2222-4222-8222-222222222222';

describe('v1 shared schemas', () => {
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
});
