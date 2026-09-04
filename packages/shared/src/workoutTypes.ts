/**
 * The workout-type vocabulary, shared by the API and the app (Batch 253, CR236-05).
 *
 * `PlannedWorkout.workout_type` is `String(80)` with no enum and no constraint, and
 * **ten** separate pieces of code classified it — nine in Python, one in
 * TypeScript — with the two languages implementing different rules. The API used
 * explicit sets plus `bike_`/`strength_`/`walk_` prefixes; the app used regexes.
 * They disagreed for values the app's own label map lists: `flexibility` and
 * `deliberate_walk` read as `flexibility`/`walk` in the app and **`weights`** in
 * the API, and a bare `vo2` or `endurance` read as `cycle` in the app and
 * `weights` in the API.
 *
 * That was latent rather than live — production holds seven values, all of which
 * classify identically — and it becomes live the moment the block generator, the
 * quick-add sheet or a hand-authored plan introduces an eighth. The symptom would
 * be the app and the coach disagreeing about what kind of day it is, with no error
 * anywhere.
 *
 * This table is the vocabulary. Python mirrors it in `services/workout_categories`
 * and a test in each language asserts the two agree entry for entry.
 */

export type DayCategory = 'cycle' | 'weights' | 'flexibility' | 'walk' | 'rest';

/** Every known workout type, and the single category it belongs to. */
export const WORKOUT_TYPE_CATEGORY = {
  bike_z2: 'cycle',
  bike_endurance: 'cycle',
  bike_recovery: 'cycle',
  bike_tempo: 'cycle',
  bike_sweet_spot: 'cycle',
  bike_threshold: 'cycle',
  bike_vo2: 'cycle',
  // Bare discipline words. TypeScript already classified these as `cycle` by
  // regex while Python's set lookup sent them to `weights`; naming them here
  // resolves the divergence the way a human reads them rather than the way the
  // stricter side happened to fall.
  z2: 'cycle',
  endurance: 'cycle',
  recovery_ride: 'cycle',
  tempo: 'cycle',
  sweet_spot: 'cycle',
  threshold: 'cycle',
  vo2: 'cycle',
  strength: 'weights',
  strength_maintenance: 'weights',
  strength_recovery: 'weights',
  mobility: 'flexibility',
  flexibility: 'flexibility',
  walk: 'walk',
  walking: 'walk',
  walk_recovery: 'walk',
  deliberate_walk: 'walk',
} as const satisfies Record<string, Exclude<DayCategory, 'rest'>>;

export type WorkoutType = keyof typeof WORKOUT_TYPE_CATEGORY;

export const WORKOUT_TYPES = Object.keys(WORKOUT_TYPE_CATEGORY) as WorkoutType[];

/**
 * The category for a workout type, including one written outside the vocabulary.
 *
 * The prefix fallbacks are deliberate and are the *same* three the API applies, so
 * a `bike_something_new` reaching the column before the vocabulary catches up is
 * classified identically on both sides rather than differently. Anything else is
 * `weights`, which is the API's historical default and stays the default here so
 * the two never diverge on the unknown case either.
 */
export function categoryForWorkoutType(
  workoutType: string | null | undefined,
): Exclude<DayCategory, 'rest'> {
  const value = (workoutType ?? '').trim().toLowerCase();
  const known = (WORKOUT_TYPE_CATEGORY as Record<string, Exclude<DayCategory, 'rest'>>)[value];
  if (known) return known;
  if (value.startsWith('bike_')) return 'cycle';
  if (value.startsWith('strength_')) return 'weights';
  if (value.startsWith('walk_')) return 'walk';
  return 'weights';
}

export function isKnownWorkoutType(value: string): value is WorkoutType {
  return value in WORKOUT_TYPE_CATEGORY;
}
