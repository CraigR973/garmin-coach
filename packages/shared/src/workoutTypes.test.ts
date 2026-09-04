import { describe, expect, it } from 'vitest';

import {
  categoryForWorkoutType,
  isKnownWorkoutType,
  WORKOUT_TYPE_CATEGORY,
  WORKOUT_TYPES,
} from './workoutTypes';

/**
 * Batch 253 (CR236-05). The vocabulary lives here; `services/workout_categories`
 * mirrors it. `test_workout_categories.py::test_the_two_languages_classify_the
 * _same_vocabulary_identically` reads this file and asserts entry-for-entry
 * agreement, so a value added on one side and not the other fails CI rather than
 * showing Mark an app and a coach that disagree about what kind of day it is.
 */
describe('workout type vocabulary', () => {
  it('classifies every known type', () => {
    for (const type of WORKOUT_TYPES) {
      expect(categoryForWorkoutType(type)).toBe(WORKOUT_TYPE_CATEGORY[type]);
    }
  });

  it('agrees with the API on the four values that used to diverge', () => {
    // flexibility and deliberate_walk read as weights in Python; a bare vo2 or
    // endurance read as cycle here and weights there.
    expect(categoryForWorkoutType('flexibility')).toBe('flexibility');
    expect(categoryForWorkoutType('deliberate_walk')).toBe('walk');
    expect(categoryForWorkoutType('vo2')).toBe('cycle');
    expect(categoryForWorkoutType('endurance')).toBe('cycle');
  });

  it('falls back on the same three prefixes the API uses', () => {
    expect(categoryForWorkoutType('bike_something_new')).toBe('cycle');
    expect(categoryForWorkoutType('strength_something_new')).toBe('weights');
    expect(categoryForWorkoutType('walk_something_new')).toBe('walk');
  });

  it('defaults an unknown value to weights, as the API does', () => {
    expect(categoryForWorkoutType('kayaking')).toBe('weights');
    expect(categoryForWorkoutType(null)).toBe('weights');
    expect(categoryForWorkoutType('')).toBe('weights');
  });

  it('normalises case and surrounding space', () => {
    expect(categoryForWorkoutType('  BIKE_VO2  ')).toBe('cycle');
  });

  it('knows what is in the vocabulary', () => {
    expect(isKnownWorkoutType('bike_vo2')).toBe(true);
    expect(isKnownWorkoutType('kayaking')).toBe(false);
  });
});
