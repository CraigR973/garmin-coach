import { describe, expect, it } from 'vitest';
import type { DailyLoopData } from '@/hooks/useDailyLoop';
import { actionSection, nextAction } from './homeActions';

type DataOverrides = Partial<{
  plannedWorkouts: Array<{ workoutType: string; delivery?: { changed?: boolean } | null }>;
  postWorkoutAnalyses: Array<{
    postRideCheckIn?: unknown;
    activityName?: string | null;
    plannedWorkoutId?: string | null;
  }>;
  manualEntry: unknown;
  sleepProjection: { tone: string } | null;
  morningAnalysis: unknown;
}>;

/** A "clear" day (checked in, nothing pending) unless overridden — so each test
 *  flips exactly the signal it exercises. Cast because the resolver reads only
 *  these payload fields. */
function makeData(overrides: DataOverrides = {}): DailyLoopData {
  return {
    plannedWorkouts: [],
    postWorkoutAnalyses: [],
    manualEntry: { id: 'entry-1' },
    sleepProjection: null,
    morningAnalysis: null,
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

  it('2b. points a completed *planned* ride check-in at the Today card (Batch 60)', () => {
    // A matched ride folds into its Today-card row, so its check-in lives there —
    // not in the standalone After-your-ride section (kept for unplanned rides).
    const action = nextAction(
      makeData({ postWorkoutAnalyses: [{ postRideCheckIn: null, plannedWorkoutId: 'pw-1' }] }),
      { isEvening: false },
    );
    expect(action.key).toBe('log-ride');
    expect(action.sectionKey).toBe('today');
  });

  it('names the specific ride in the log-ride label, not a generic "check in"', () => {
    const action = nextAction(
      makeData({ postWorkoutAnalyses: [{ postRideCheckIn: null, activityName: 'Tempo ride' }] }),
      { isEvening: false },
    );
    expect(action.label).toBe('Log how Tempo ride felt');
  });

  it('falls back to "your ride" when the analysed activity has no name', () => {
    const action = nextAction(
      makeData({ postWorkoutAnalyses: [{ postRideCheckIn: null, activityName: null }] }),
      { isEvening: false },
    );
    expect(action.label).toBe('Log how your ride felt');
  });

  it('a ride whose check-in is already logged does not surface rung 2', () => {
    const action = nextAction(
      makeData({ postWorkoutAnalyses: [{ postRideCheckIn: { rpe: 8 } }] }),
      { isEvening: false },
    );
    expect(action.key).not.toBe('log-ride');
    expect(action.key).toBe('all-set');
  });

  it('3. prompts the morning check-in when none is logged, linking to /check-in', () => {
    const action = nextAction(makeData({ manualEntry: null }), { isEvening: false });
    expect(action.key).toBe('check-in');
    expect(action.label).toBe('Morning check-in');
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

describe('nextAction morning order (sleep → check-in → eased ride)', () => {
  const morning = { isEvening: false, isMorning: true } as const;
  const synced = { morningAnalysis: { verdict: 'Green' } };

  it('leads with reviewing last night once metrics have synced', () => {
    const action = nextAction(makeData({ ...synced, manualEntry: null }), {
      ...morning,
      hasReviewedSleep: false,
    });
    expect(action.key).toBe('review-sleep');
    expect(action.label).toBe("Review last night's sleep");
    expect(action.to).toBe('/sleep');
    expect(action.tone).toBe('default');
    expect(action.sectionKey).toBeUndefined();
  });

  it('does not prompt a sleep review before metrics sync (falls to the check-in)', () => {
    // morningAnalysis null = "verdict pending" — nothing to review yet.
    const action = nextAction(makeData({ manualEntry: null }), { ...morning, hasReviewedSleep: false });
    expect(action.key).toBe('check-in');
  });

  it('steps down to the check-in once sleep has been opened today', () => {
    const action = nextAction(makeData({ ...synced, manualEntry: null }), {
      ...morning,
      hasReviewedSleep: true,
    });
    expect(action.key).toBe('check-in');
  });

  it('review-sleep outranks a pending eased ride in the morning', () => {
    const action = nextAction(makeData({ ...synced, plannedWorkouts: [bikeChanged], manualEntry: null }), {
      ...morning,
      hasReviewedSleep: false,
    });
    expect(action.key).toBe('review-sleep');
  });

  it('the optional check-in still outranks the eased ride in the morning', () => {
    // The Zwift-affecting ride approval is deliberately below the check-in in
    // the morning (Craig's call) — recovery is read before the ride is set.
    const action = nextAction(makeData({ ...synced, plannedWorkouts: [bikeChanged], manualEntry: null }), {
      ...morning,
      hasReviewedSleep: true,
    });
    expect(action.key).toBe('check-in');
  });

  it('reviews the eased ride only after sleep and check-in are done', () => {
    const action = nextAction(makeData({ ...synced, plannedWorkouts: [bikeChanged] }), {
      ...morning,
      hasReviewedSleep: true,
    });
    expect(action.key).toBe('review-ride');
  });

  it('is all-clear in the morning once nothing is pending', () => {
    const action = nextAction(makeData({ ...synced }), { ...morning, hasReviewedSleep: true });
    expect(action.key).toBe('all-set');
  });

  it('keeps the ride-first order outside the morning (regression)', () => {
    // Same synced payload with an eased ride, but not the morning phase → the
    // day-time ladder still surfaces the ride first, no sleep rung.
    const action = nextAction(makeData({ ...synced, plannedWorkouts: [bikeChanged], manualEntry: null }), {
      isEvening: false,
    });
    expect(action.key).toBe('review-ride');
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
