import type { DailyLoopData } from '@/hooks/useDailyLoop';

export type DayCategory = 'cycle' | 'weights' | 'flexibility' | 'rest';

const LABELS: Record<Exclude<DayCategory, 'rest'>, string> = {
  cycle: 'Cycle',
  weights: 'Weights',
  flexibility: 'Flexibility',
};

export function categoryForWorkoutType(workoutType: string | null | undefined): Exclude<DayCategory, 'rest'> {
  const value = (workoutType ?? '').toLowerCase();
  if (value.startsWith('bike_') || /bike|cycl|ride|vo2|sweet|endurance|tempo|threshold/.test(value)) {
    return 'cycle';
  }
  if (value.startsWith('strength_') || /dumbbell|bodyweight|strength|resist/.test(value)) {
    return 'weights';
  }
  if (value === 'mobility' || /mobility|flex/.test(value)) {
    return 'flexibility';
  }
  return 'weights';
}

export function isBikeWorkoutType(workoutType: string | null | undefined): boolean {
  return categoryForWorkoutType(workoutType) === 'cycle';
}

export function dayStateForWorkouts(workouts: Array<Pick<DailyLoopData['plannedWorkouts'][number], 'workoutType'>>): {
  categories: DayCategory[];
  label: string;
  isRest: boolean;
} {
  const categories: Exclude<DayCategory, 'rest'>[] = [];
  for (const workout of workouts) {
    const category = categoryForWorkoutType(workout.workoutType);
    if (!categories.includes(category)) categories.push(category);
  }
  if (categories.length === 0) {
    return { categories: ['rest'], label: 'Rest', isRest: true };
  }
  return {
    categories,
    label: categories.map((category) => LABELS[category]).join(' + '),
    isRest: false,
  };
}
