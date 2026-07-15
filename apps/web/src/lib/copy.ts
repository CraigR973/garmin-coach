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
): string {
  const greeting = `${greetingForNow(date)}${displayName ? `, ${displayName}` : ''}.`;

  if (isRestOrHoliday) {
    return `${greeting} Today's a rest day — recovery is the plan, not training.`;
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
