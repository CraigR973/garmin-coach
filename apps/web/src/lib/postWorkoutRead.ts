/**
 * A post-ride check-in that saved fine but whose coach read couldn't generate
 * (Batch 143). When a day-time Anthropic call fails, the backend still commits
 * his RPE/feel/notes and returns the daily-loop envelope 2xx with a non-fatal
 * `errors[]` note carrying this code — the activity then re-surfaces as a pending
 * read with the saved check-in, so re-submitting is the retry.
 */
export const POST_WORKOUT_READ_FAILED = 'post_workout_read_failed';

/**
 * Pull the post-workout-read failure message out of a daily-loop mutation
 * response, or `null` when the read succeeded — so the post-ride surfaces show an
 * honest "saved, couldn't read — try again" toast instead of a false success.
 */
export function postWorkoutReadFailure(result: unknown): string | null {
  if (!result || typeof result !== 'object') return null;
  const errors = (result as { errors?: unknown }).errors;
  if (!Array.isArray(errors)) return null;
  for (const raw of errors) {
    if (
      raw &&
      typeof raw === 'object' &&
      (raw as { code?: unknown }).code === POST_WORKOUT_READ_FAILED &&
      typeof (raw as { detail?: unknown }).detail === 'string'
    ) {
      return (raw as { detail: string }).detail;
    }
  }
  return null;
}
