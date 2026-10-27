import { isBikeWorkout } from '@/hooks/useDailyPhase';
import { type DailyLoopData } from '@/hooks/useDailyLoop';

type TodayAction = NonNullable<DailyLoopData['morningAnalysis']>['todayActions'][number];
type TodayWorkout = DailyLoopData['plannedWorkouts'][number];

export function visibleTodayActions(
  actions: readonly TodayAction[],
  workouts: readonly TodayWorkout[],
): TodayAction[] {
  return actions.filter((action) => {
    // Batch 306: a tired morning's pick is offered on the same pending change as an
    // eased ride, so it leaves the list the moment he has picked one.
    if (action.kind === 'approve_ride' || action.kind === 'pick_ride') {
      const workout = workouts.find((item) => item.id === action.plannedWorkoutId);
      return (
        Boolean(workout?.delivery?.changed) &&
        isBikeWorkout(workout?.workoutType ?? null) &&
        Boolean(action.plannedWorkoutId) &&
        (action.kind === 'approve_ride' || (action.choices?.length ?? 0) > 0)
      );
    }

    if (action.kind === 'apply_swap') {
      // Batch 335: once the session has moved it is no longer today's, and a second tap
      // would only get "Planned workout not found".
      return Boolean(
        action.plannedWorkoutId &&
          action.targetDate &&
          workouts.some((item) => item.id === action.plannedWorkoutId),
      );
    }

    return true;
  });
}
