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

/** Time-of-day greeting (the app is morning-centric, but Mark may open it any time). */
export function greetingForNow(date = new Date()): string {
  const h = date.getHours();
  if (h < 12) return 'Good morning';
  if (h < 18) return 'Good afternoon';
  return 'Good evening';
}
