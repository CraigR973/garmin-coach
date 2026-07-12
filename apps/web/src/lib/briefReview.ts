const KEY = 'coach_brief_reviewed_date';

/**
 * Per-day client flag: has Mark opened the morning brief for this daily-loop
 * subject date? Mirrors {@link import('./sleepReview').hasReviewedSleep} —
 * there is no server "seen the brief" signal, so Home's Batch 96 unviewed-brief
 * CTA completes off this flag once he opens `/brief`, instead of nagging after
 * he's already read it.
 *
 * Keyed by the whole date (not a boolean) so a freshly generated brief on a new
 * day always re-prompts without needing a reset. Storage failures (private
 * mode) degrade to "not reviewed" — the CTA simply re-shows, which is the safe
 * direction.
 */
export function hasReviewedBrief(subjectDate: string): boolean {
  try {
    return localStorage.getItem(KEY) === subjectDate;
  } catch {
    return false;
  }
}

export function markBriefReviewed(subjectDate: string): void {
  try {
    localStorage.setItem(KEY, subjectDate);
  } catch {
    // Ignore storage failures — the CTA just re-shows next render.
  }
}
