import { describe, expect, it } from 'vitest';
import type { DailyLoopData } from '@/hooks/useDailyLoop';
import { useDailyPhase } from './useDailyPhase';

/** Minimal daily-loop payload — the hook only reads the post-session arrays,
 *  the planned workouts, and the (optional) server loop-state. */
function loop(partial: Partial<DailyLoopData>): DailyLoopData {
  return {
    postWorkoutAnalyses: [],
    postFlexibilityAnalyses: [],
    postStrengthAnalyses: [],
    postWalkAnalyses: [],
    plannedWorkouts: [],
    ...partial,
  } as unknown as DailyLoopData;
}

const stub = { id: 'x' } as unknown;

describe('useDailyPhase', () => {
  it('is pre_training before data loads (daytime)', () => {
    expect(useDailyPhase(undefined, false)).toBe('pre_training');
  });

  it('is wind_down in the evening regardless of data', () => {
    expect(useDailyPhase(undefined, true)).toBe('wind_down');
    expect(useDailyPhase(loop({ postWorkoutAnalyses: [stub] as never }), true)).toBe('wind_down');
  });

  describe('prefers the server loop-state model for the data stage', () => {
    it('uses the server dayPhase when present', () => {
      const data = loop({
        loopState: { dayPhase: 'post_training' } as never,
        // arrays empty — proves it is the server stage, not local derivation.
      });
      expect(useDailyPhase(data, false)).toBe('post_training');
    });

    it('honours a server rest_day', () => {
      const data = loop({
        loopState: { dayPhase: 'rest_day' } as never,
        plannedWorkouts: [stub] as never,
      });
      expect(useDailyPhase(data, false)).toBe('rest_day');
    });

    it('ignores a server wind_down stage and re-derives locally when not evening', () => {
      const data = loop({
        loopState: { dayPhase: 'wind_down' } as never,
        postStrengthAnalyses: [stub] as never,
      });
      expect(useDailyPhase(data, false)).toBe('post_training');
    });
  });

  describe('local fallback derivation (no server loop-state)', () => {
    it('advances to post_training off a strength-only read', () => {
      expect(useDailyPhase(loop({ postStrengthAnalyses: [stub] as never }), false)).toBe(
        'post_training',
      );
    });

    it('advances to post_training off a walk-only read', () => {
      expect(useDailyPhase(loop({ postWalkAnalyses: [stub] as never }), false)).toBe(
        'post_training',
      );
    });

    it('is pre_training with a planned workout and no read yet', () => {
      expect(useDailyPhase(loop({ plannedWorkouts: [stub] as never }), false)).toBe('pre_training');
    });

    it('is rest_day with nothing planned and no read', () => {
      expect(useDailyPhase(loop({}), false)).toBe('rest_day');
    });
  });
});
