import { describe, expect, it } from 'vitest';
import type { DailyLoopData } from '@/hooks/useDailyLoop';
import { actionSection, nextAction } from './homeActions';

type DataOverrides = Partial<{
  plannedWorkouts: Array<{ workoutType: string; delivery?: { changed?: boolean } | null }>;
  postWorkoutAnalyses: Array<{ postRideCheckIn?: unknown }>;
  manualEntry: unknown;
  sleepProjection: { tone: string } | null;
}>;

/** A "clear" day (checked in, nothing pending) unless overridden — so each test
 *  flips exactly the signal it exercises. Cast because the resolver reads only
 *  these four payload fields. */
function makeData(overrides: DataOverrides = {}): DailyLoopData {
  return {
    plannedWorkouts: [],
    postWorkoutAnalyses: [],
    manualEntry: { id: 'entry-1' },
    sleepProjection: null,
    ...overrides,
  } as unknown as DailyLoopData;
}

const bikeChanged = { workoutType: 'bike_tempo', delivery: { changed: true } };

describe('nextAction priority ladder', () => {
  it('1. surfaces a pending coach change on a bike session, expanding Today', () => {
    const action = nextAction(makeData({ plannedWorkouts: [bikeChanged] }), { isEvening: false });
    expect(action.key).toBe('review-ride');
    expect(action.sectionKey).toBe('today');
    expect(action.tone).toBe('warning');
    expect(action.to).toBeUndefined();
  });

  it('a changed non-bike session is not a pending coach change (falls through)', () => {
    // Strength/flexibility never deliver to Zwift, so a "changed" flag on one is
    // not an adjustment awaiting approval.
    const action = nextAction(
      makeData({ plannedWorkouts: [{ workoutType: 'strength', delivery: { changed: true } }] }),
      { isEvening: false },
    );
    expect(action.key).not.toBe('review-ride');
  });

  it('2. surfaces an unlogged ride check-in, expanding After-your-ride', () => {
    const action = nextAction(makeData({ postWorkoutAnalyses: [{ postRideCheckIn: null }] }), {
      isEvening: false,
    });
    expect(action.key).toBe('log-ride');
    expect(action.sectionKey).toBe('afterRide');
    expect(action.tone).toBe('warning');
  });

  it('a ride whose check-in is already logged does not surface rung 2', () => {
    const action = nextAction(
      makeData({ postWorkoutAnalyses: [{ postRideCheckIn: { rpe: 8 } }] }),
      { isEvening: false },
    );
    expect(action.key).not.toBe('log-ride');
    expect(action.key).toBe('all-set');
  });

  it('3. prompts the daily check-in when none is logged, linking to /check-in', () => {
    const action = nextAction(makeData({ manualEntry: null }), { isEvening: false });
    expect(action.key).toBe('check-in');
    expect(action.to).toBe('/check-in');
    expect(action.sectionKey).toBeUndefined();
  });

  it('4. protects tonight only in the evening when the projection says protect', () => {
    const protect = makeData({ sleepProjection: { tone: 'protect' } });
    expect(nextAction(protect, { isEvening: true }).key).toBe('protect-sleep');
    expect(nextAction(protect, { isEvening: true }).to).toBe('/sleep');
    // Same payload during the day → not yet the evening concern.
    expect(nextAction(protect, { isEvening: false }).key).toBe('all-set');
    // A non-protect projection in the evening → nothing to act on.
    expect(
      nextAction(makeData({ sleepProjection: { tone: 'routine' } }), { isEvening: true }).key,
    ).toBe('all-set');
  });

  it('5. is all-clear when nothing is pending', () => {
    const action = nextAction(makeData(), { isEvening: true });
    expect(action.key).toBe('all-set');
    expect(action.tone).toBe('muted');
    expect(action.to).toBeUndefined();
    expect(action.sectionKey).toBeUndefined();
  });
});

describe('nextAction precedence (need before time-of-day)', () => {
  it('a pending change outranks every lower rung, even in the evening', () => {
    const action = nextAction(
      makeData({
        plannedWorkouts: [bikeChanged],
        postWorkoutAnalyses: [{ postRideCheckIn: null }],
        manualEntry: null,
        sleepProjection: { tone: 'protect' },
      }),
      { isEvening: true },
    );
    expect(action.key).toBe('review-ride');
  });

  it('an unlogged ride outranks the daily check-in and protect-sleep', () => {
    const action = nextAction(
      makeData({
        postWorkoutAnalyses: [{ postRideCheckIn: null }],
        manualEntry: null,
        sleepProjection: { tone: 'protect' },
      }),
      { isEvening: true },
    );
    expect(action.key).toBe('log-ride');
  });

  it('the daily check-in outranks protect-sleep', () => {
    const action = nextAction(
      makeData({ manualEntry: null, sleepProjection: { tone: 'protect' } }),
      { isEvening: true },
    );
    expect(action.key).toBe('check-in');
  });
});

describe('actionSection', () => {
  it('returns the section for section-target actions and null otherwise', () => {
    expect(actionSection(nextAction(makeData({ plannedWorkouts: [bikeChanged] }), { isEvening: false }))).toBe(
      'today',
    );
    expect(
      actionSection(nextAction(makeData({ postWorkoutAnalyses: [{ postRideCheckIn: null }] }), { isEvening: false })),
    ).toBe('afterRide');
    expect(actionSection(nextAction(makeData({ manualEntry: null }), { isEvening: false }))).toBeNull();
    expect(actionSection(nextAction(makeData(), { isEvening: false }))).toBeNull();
  });
});
