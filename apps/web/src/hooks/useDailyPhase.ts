import type { DailyLoopData } from '@/hooks/useDailyLoop';

export type DailyPhase = 'pre_ride' | 'post_ride' | 'rest_day';

function isBikeWorkoutType(workoutType: string | null | undefined): boolean {
  const value = (workoutType ?? '').toLowerCase();
  return /bike|cycl|ride|vo2|z2|sweet|endurance|tempo|threshold/.test(value);
}

export function useDailyPhase(data: DailyLoopData | undefined): DailyPhase {
  if (!data) {
    return 'pre_ride';
  }

  if ((data.postWorkoutAnalyses?.length ?? 0) > 0) {
    return 'post_ride';
  }

  const hasBikeWorkout = data.plannedWorkouts.some((workout) => isBikeWorkoutType(workout.workoutType));
  if (!hasBikeWorkout) {
    return 'rest_day';
  }

  return 'pre_ride';
}

export function isBikeWorkout(workoutType: string | null | undefined): boolean {
  return isBikeWorkoutType(workoutType);
}
