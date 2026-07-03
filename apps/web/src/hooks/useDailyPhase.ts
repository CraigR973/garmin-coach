import type { DailyLoopData } from '@/hooks/useDailyLoop';
import { isBikeWorkoutType } from '@/lib/workoutCategories';

/**
 * The generalised daily loop phase (Batch 48). The old cycling-shaped model
 * (`pre_ride | post_ride | rest_day`) is generalised two ways:
 *
 * - `post_ride` → `post_training`, fired off *any* post-session read
 *   (ride / strength / flexibility / walk) so a non-ride day advances instead
 *   of being stuck `pre_ride`.
 * - a first-class evening `wind_down` phase replaces the 20:00 clock reorder.
 *
 * These rules mirror the backend `services/daily_loop_state.py`.
 */
export type DailyPhase = 'pre_training' | 'post_training' | 'rest_day' | 'wind_down';

/** The daily-loop fields that carry a completed post-session read. */
const POST_ANALYSIS_KEYS = [
  'postWorkoutAnalyses',
  'postFlexibilityAnalyses',
  'postStrengthAnalyses',
  'postWalkAnalyses',
] as const;

function hasAnyPostAnalysis(data: DailyLoopData): boolean {
  return POST_ANALYSIS_KEYS.some((key) => (data[key]?.length ?? 0) > 0);
}

/** The clock-independent day stage. Prefers the server's loop-state model, and
 *  falls back to local derivation for a stale cached / offline payload. */
function derivePhaseFromData(
  data: DailyLoopData | undefined,
): Exclude<DailyPhase, 'wind_down'> {
  const serverStage = data?.loopState?.dayPhase;
  if (
    serverStage === 'pre_training' ||
    serverStage === 'post_training' ||
    serverStage === 'rest_day'
  ) {
    return serverStage;
  }

  if (!data) {
    return 'pre_training';
  }
  if (hasAnyPostAnalysis(data)) {
    return 'post_training';
  }
  // Any planned workout — bike or not — leads the Today card (Batch 29). A
  // rest day is only when nothing at all is on the slate.
  if (data.plannedWorkouts.length === 0) {
    return 'rest_day';
  }
  return 'pre_training';
}

/**
 * Where Mark is in his day. The evening `wind_down` (sleep prep — the evening's
 * focus since Batch 46) wins over the data stage; `isEvening` is passed in so
 * the caller threads a single clock read through both the phase and the section
 * ordering.
 */
export function useDailyPhase(data: DailyLoopData | undefined, isEvening: boolean): DailyPhase {
  if (isEvening) {
    return 'wind_down';
  }
  return derivePhaseFromData(data);
}

export function isBikeWorkout(workoutType: string | null | undefined): boolean {
  return isBikeWorkoutType(workoutType);
}
