import { describe, expect, it } from 'vitest';
import { POST_WORKOUT_READ_FAILED, postWorkoutReadFailure } from './postWorkoutRead';

describe('postWorkoutReadFailure', () => {
  it('returns the note detail when the envelope carries the read-failed code', () => {
    const result = {
      data: {},
      meta: {},
      errors: [
        { code: POST_WORKOUT_READ_FAILED, detail: 'The coach is briefly unavailable. Please try again in a moment.' },
      ],
    };
    expect(postWorkoutReadFailure(result)).toBe(
      'The coach is briefly unavailable. Please try again in a moment.',
    );
  });

  it('returns null when the read succeeded (no errors)', () => {
    expect(postWorkoutReadFailure({ data: {}, meta: {}, errors: [] })).toBeNull();
  });

  it('ignores unrelated error codes', () => {
    expect(postWorkoutReadFailure({ errors: [{ code: 'something_else', detail: 'x' }] })).toBeNull();
  });

  it('is null-safe for non-envelope input', () => {
    expect(postWorkoutReadFailure(undefined)).toBeNull();
    expect(postWorkoutReadFailure(null)).toBeNull();
    expect(postWorkoutReadFailure('nope')).toBeNull();
    expect(postWorkoutReadFailure({ errors: 'nope' })).toBeNull();
  });
});
