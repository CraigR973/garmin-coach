/**
 * Mark-facing copy — plain English, not engineer-speak.
 *
 * Centralised so the de-jargon pass stays consistent across screens. Mark (the
 * primary user) thinks in "Today's verdict / How did it go? / Last night's
 * sleep", not "Daily Loop / adherence / propose→approve→push".
 */

/** Batch 313: the morning's headline, line and chip are today's call, stored with the
 *  morning on the server (`todaysCall`), so Home, the brief page, the written brief and
 *  the coach chat read one copy. The colour helpers below serve the bedroom's own
 *  Green/Amber/Red room rating, which stays. */

/** Batch 313: Tomorrow's cue before the ride has given one (signed off 4 Oct 2026). */
export const TOMORROW_CALL_LINE = "Tomorrow's call comes from tomorrow morning's readings.";

/** Batch 302: the morning's colour, notices and plan are stored before the paid brief
 *  is written, so they show while it is being written and when it did not finish. These
 *  are the only new words; everything above them reads as on any other morning. Signed
 *  off by Craig on Mark's behalf, 2 Oct 2026
 *  (docs/drafts/2026-10-02-batch-302-wording.md). */
export const BRIEF_WRITING_TITLE = 'Writing your brief';
export const BRIEF_WRITING_LINE =
  "Today's call and your plan are ready above. The written brief lands in a moment.";
export const BRIEF_UNWRITTEN_TITLE = "Couldn't finish your written brief";
export const BRIEF_UNWRITTEN_LINE =
  "Today's call and your plan above are complete without it. Your check-in is saved.";
export const BRIEF_UNWRITTEN_CHECKIN_LINE =
  "Today's call and your plan are ready on Home. Your check-in is saved — tap to try again.";
export const BRIEF_UNWRITTEN_TOAST =
  "Today's call is ready — I couldn't finish the written brief";
export const BRIEF_RETRY_LABEL = 'Try again';
export const SEE_TODAY_LABEL = 'See today';
/** In a full outage the notes reader fails with the brief. The written brief is where
 *  the app said so; a morning without one says it here. */
export const NOTE_UNREAD_LINE =
  "I couldn't read your note this morning, so today's call comes from your numbers and your answers alone.";

export function verdictBadgeVariant(
  verdict: string | null | undefined,
): 'success' | 'warning' | 'error' | 'muted' {
  if (verdict === 'green') return 'success';
  if (verdict === 'amber') return 'warning';
  if (verdict === 'red') return 'error';
  return 'muted';
}

export function verdictToneLabel(verdict: string | null | undefined): string {
  if (verdict === 'green' || verdict === 'amber' || verdict === 'red') {
    return verdict.charAt(0).toUpperCase() + verdict.slice(1);
  }
  return 'Unknown';
}

/** Time-of-day greeting (the app is morning-centric, but Mark may open it any time). */
export function greetingForNow(date = new Date()): string {
  const h = date.getHours();
  if (h < 12) return 'Good morning';
  if (h < 18) return 'Good afternoon';
  return 'Good evening';
}
