import { isBikeWorkout } from '@/hooks/useDailyPhase';
import { type DailyLoopData } from '@/hooks/useDailyLoop';

type TodayAction = NonNullable<DailyLoopData['morningAnalysis']>['todayActions'][number];
type TodayWorkout = DailyLoopData['plannedWorkouts'][number];

export function visibleTodayActions(
  actions: readonly TodayAction[],
  workouts: readonly TodayWorkout[],
): TodayAction[] {
  return actions.filter((action) => {
    if (action.kind === 'approve_ride') {
      const workout = workouts.find((item) => item.id === action.plannedWorkoutId);
      return (
        Boolean(workout?.delivery?.changed) &&
        isBikeWorkout(workout?.workoutType ?? null) &&
        Boolean(action.plannedWorkoutId)
      );
    }

    if (action.kind === 'apply_swap') {
      return Boolean(action.plannedWorkoutId && action.targetDate);
    }

    return true;
  });
}
