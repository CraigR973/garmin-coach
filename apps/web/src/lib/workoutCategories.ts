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

// Clean, human label for a workout-type enum, used in the day-card subtitle.
// Replaces the old per-page `type.replace(/[_-]+/g, ' ')` which leaked the raw
// discipline prefix ("Bike sweet spot", "Bike z2") beneath an already-friendly
// title. The category badge/icon already conveys the discipline, so the label
// drops the `bike_`/`strength_` prefix and reads as the session's character.
const WORKOUT_TYPE_LABELS: Record<string, string> = {
  bike_z2: 'Zone 2',
  bike_endurance: 'Endurance',
  bike_tempo: 'Tempo',
  bike_sweet_spot: 'Sweet spot',
  bike_threshold: 'Threshold',
  bike_vo2: 'VO₂',
  bike_recovery: 'Recovery ride',
  strength: 'Strength',
  mobility: 'Mobility',
  flexibility: 'Mobility',
  walk: 'Walk',
  deliberate_walk: 'Walk',
};

export function workoutTypeLabel(workoutType: string | null | undefined): string {
  const value = (workoutType ?? '').toLowerCase().trim();
  if (!value) return 'Session';
  const mapped = WORKOUT_TYPE_LABELS[value];
  if (mapped) return mapped;
  // Fallback: strip a known discipline prefix, de-underscore, sentence-case.
  const stripped = value.replace(/^(bike|strength|cycle|ride)_/, '');
  const cleaned = stripped.replace(/[_-]+/g, ' ').trim();
  return cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
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
