const KEY = 'coach_walk_read_seen_date';

/**
 * Per-day client flag: has Mark seen a generated walk read on Home for this
 * daily-loop subject date? Mirrors {@link import('./sleepReview').hasReviewedSleep}
 * and {@link import('./briefReview').hasReviewedBrief} — there is no server
 * "seen" signal for a walk read (unlike its pending check-in, which the server
 * clears once logged), so Home's Batch 132 walk rung completes off this flag
 * once `WalkReadList` has rendered, instead of floating the Today card forever.
 *
 * Keyed by the whole date (not a boolean) so a freshly generated walk read on a
 * new day always re-prompts without needing a reset. Storage failures (private
 * mode) degrade to "not seen" — the rung simply re-shows, which is the safe
 * direction.
 */
export function hasSeenWalkRead(subjectDate: string): boolean {
  try {
    return localStorage.getItem(KEY) === subjectDate;
  } catch {
    return false;
  }
}

export function markWalkReadSeen(subjectDate: string): void {
  try {
    localStorage.setItem(KEY, subjectDate);
  } catch {
    // Ignore storage failures — the rung just re-shows next render.
  }
}
