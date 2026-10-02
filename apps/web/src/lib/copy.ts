/**
 * Mark-facing copy — plain English, not engineer-speak.
 *
 * Centralised so the de-jargon pass stays consistent across screens. Mark (the
 * primary user) thinks in "Today's verdict / How did it go? / Last night's
 * sleep", not "Daily Loop / adherence / propose→approve→push".
 */

export type Verdict = 'green' | 'amber' | 'red';

export const verdictCopy: Record<Verdict, { label: string; line: string }> = {
  green: { label: 'Good to go', line: 'Train as planned today.' },
  amber: { label: 'Take it easier', line: 'Ease back — shorter, and drop the hard stuff.' },
  red: { label: 'Rest or substitute', line: 'Your body needs recovery today.' },
};

/** Batch 296: the headline when the colour came from the graded verdict. Green with
 *  the targets held has its own headline, and the graded Amber eases only the hard
 *  work. Signed off by Craig on Mark's behalf, 29 Sep 2026. A read the ladder decided
 *  keeps the defaults above. */
export const HELD_LABEL = 'Good to go — hold your targets';
export const HELD_LINE =
  'One thing is a little off: ride as planned, and hold your targets rather than pushing past them.';
export const GRADED_AMBER_LINE = 'Ease the hard work; easy riding stays as planned.';

/** Batch 298: in a light week (W12 consolidation, W13 taper) a concern holds the
 *  session, and Home said "Take it a bit easier" beside a plan line that kept it. The
 *  headline now says the session stands, and names the week as his plan does. Signed
 *  off by Craig on Mark's behalf, 1 Oct 2026. */
export const LIGHT_WEEK_AMBER_LABEL = 'Ride as planned — hold your targets';
export function lightWeekHoldLine(week: string): string {
  return `It's your ${week} week, so today's session stays as planned: hold your targets.`;
}

/** The line on a rest or holiday day, on Home and (since Batch 298) the brief page. */
export const REST_DAY_LINE = "Today's a rest day — recovery is the plan, not training.";

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

function lightWeekHolds(
  verdict: string | null | undefined,
  held: boolean | null | undefined,
  engine: string | null | undefined,
  lightWeekHold: string | null | undefined,
): lightWeekHold is string {
  return (
    typeof lightWeekHold === 'string' &&
    lightWeekHold.length > 0 &&
    engine === 'graded' &&
    (verdict === 'amber' || (verdict === 'green' && held === true))
  );
}

export function gradedVerdictCopy(
  verdict: string | null | undefined,
  held: boolean | null | undefined,
  engine: string | null | undefined,
  lightWeekHold?: string | null,
): { label?: string; line?: string } {
  if (lightWeekHolds(verdict, held, engine, lightWeekHold)) {
    return {
      label: verdict === 'amber' ? LIGHT_WEEK_AMBER_LABEL : HELD_LABEL,
      line: lightWeekHoldLine(lightWeekHold),
    };
  }
  if (verdict === 'green' && held === true) return { label: HELD_LABEL, line: HELD_LINE };
  if (verdict === 'amber' && engine === 'graded') return { line: GRADED_AMBER_LINE };
  return {};
}

export function verdictLabel(verdict: string | null | undefined): string {
  if (verdict === 'green' || verdict === 'amber' || verdict === 'red') {
    return verdictCopy[verdict].label;
  }
  return 'Not ready yet';
}

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

function timeContextForNow(date = new Date()): string {
  const h = date.getHours();
  if (h < 12) return 'this morning';
  if (h < 18) return 'this afternoon';
  return 'tonight';
}

export function personalStatusLine(
  verdict: string | null | undefined,
  displayName?: string | null,
  date = new Date(),
  isRestOrHoliday = false,
  held = false,
  graded: { engine?: string | null; lightWeekHold?: string | null } = {},
): string {
  const greeting = `${greetingForNow(date)}${displayName ? `, ${displayName}` : ''}.`;

  if (isRestOrHoliday) {
    return `${greeting} ${REST_DAY_LINE}`;
  }

  // Batch 298: the same words as the brief page and the plan line.
  if (lightWeekHolds(verdict, held, graded.engine, graded.lightWeekHold)) {
    return `${greeting} ${lightWeekHoldLine(graded.lightWeekHold)}`;
  }
  if (verdict === 'amber' && graded.engine === 'graded') {
    return `${greeting} Ease the hard work ${timeContextForNow(date)}; easy riding stays as planned.`;
  }

  if (verdict === 'green' && held) {
    return `${greeting} Ride as planned ${timeContextForNow(date)}, and hold your targets.`;
  }
  if (verdict === 'green') {
    return `${greeting} You're good to go ${timeContextForNow(date)}.`;
  }
  if (verdict === 'amber') {
    return `${greeting} Take it a bit easier ${timeContextForNow(date)}.`;
  }
  if (verdict === 'red') {
    return `${greeting} Recovery is the right call ${timeContextForNow(date)}.`;
  }
  return `${greeting} Your brief will land once today's read is ready.`;
}
