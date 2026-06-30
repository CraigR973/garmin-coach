import type { DailyLoopData } from '@/hooks/useDailyLoop';
import { isBikeWorkoutType } from '@/lib/workoutCategories';

export type DailyPhase = 'pre_ride' | 'post_ride' | 'rest_day';

export function useDailyPhase(data: DailyLoopData | undefined): DailyPhase {
  if (!data) {
    return 'pre_ride';
  }

  if ((data.postWorkoutAnalyses?.length ?? 0) > 0) {
    return 'post_ride';
  }

  // Any planned workout — bike or not — leads the Today card (Batch 29). A
  // rest day is only when nothing at all is on the slate.
  if (data.plannedWorkouts.length === 0) {
    return 'rest_day';
  }

  return 'pre_ride';
}

export function isBikeWorkout(workoutType: string | null | undefined): boolean {
  return isBikeWorkoutType(workoutType);
}
