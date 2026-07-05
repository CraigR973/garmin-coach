const KEY = 'coach_sleep_reviewed_date';

/**
 * Per-day client flag: has Mark opened the Sleep hub for this daily-loop subject
 * date? There is no server "seen last night" signal, so — mirroring the
 * client-only Ignore dismiss (#99) — the morning "Review last night's sleep"
 * action (`homeActions.nextAction`) completes off this flag and steps down to
 * the check-in, instead of nagging forever with nothing to mark it done.
 *
 * Keyed by the whole date (not a boolean) so a new day's sleep always re-prompts
 * without needing a reset. Storage failures (private mode) degrade to "not
 * reviewed" — the action simply re-shows, which is the safe direction.
 */
export function hasReviewedSleep(subjectDate: string): boolean {
  try {
    return localStorage.getItem(KEY) === subjectDate;
  } catch {
    return false;
  }
}

export function markSleepReviewed(subjectDate: string): void {
  try {
    localStorage.setItem(KEY, subjectDate);
  } catch {
    // Ignore storage failures — the sleep action just re-shows next render.
  }
}
