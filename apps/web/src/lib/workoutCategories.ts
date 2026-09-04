import {
  categoryForWorkoutType,
  isKnownWorkoutType,
  WORKOUT_TYPE_CATEGORY,
  WORKOUT_TYPES,
} from '@coach/shared';
import type { DayCategory, WorkoutType } from '@coach/shared';

import type { DailyLoopData } from '@/hooks/useDailyLoop';

// Batch 253 (CR236-05): the vocabulary and the classifier now live in
// `@coach/shared`, mirrored entry-for-entry by `services/workout_categories`.
// This module re-exports them so its existing importers do not move, and keeps
// only what is genuinely app-side: the labels and the day-card assembly.
export { categoryForWorkoutType, isKnownWorkoutType, WORKOUT_TYPE_CATEGORY, WORKOUT_TYPES };
export type { DayCategory, WorkoutType };

const LABELS: Record<Exclude<DayCategory, 'rest'>, string> = {
  cycle: 'Cycle',
  weights: 'Weights',
  flexibility: 'Flexibility',
  walk: 'Walk',
};

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
