/**
 * Batch 326: what the app may say about Zwift. A ride reaches Zwift through intervals.icu,
 * and the app sees only its own leg; the day carries the newest reading of the
 * intervals.icu account (`zwiftRail`). On 7 Oct 2026 Mark found the Zwift folder empty
 * while Home said "Already in Zwift": intervals.icu had paused his account on 24 Sep.
 *
 * The words are Craig's to sign off (docs/drafts/2026-10-07-batch-326-wording.md); the
 * tests hold every line here to that file.
 */
import type { DailyLoopData } from '@/hooks/useDailyLoop';
import { sessionDay } from '@/lib/nextPlan';

export type ZwiftRail = NonNullable<DailyLoopData['zwiftRail']>;

export const ZWIFT_READY_LINE = 'Already in Zwift, ready to ride.';
export const ZWIFT_PAUSED_LINE =
  'Not reaching Zwift: intervals.icu has paused your account. Log in at intervals.icu once, then restart Zwift.';
export const ZWIFT_UNLINKED_LINE =
  "Not reaching Zwift: intervals.icu has lost its link to Zwift. Reconnect Zwift in intervals.icu's settings.";
export const ZWIFT_UNKNOWN_LINE =
  "Sent to intervals.icu. The app can't check that it reached Zwift.";

/**
 * Whether a ride sent to intervals.icu gets to Zwift. A day from an older server carries
 * no rail and keeps today's words; a state this app does not know is "can't check".
 */
export function reachesZwift(rail: ZwiftRail | null | undefined): boolean {
  if (rail == null) return true;
  return rail.state === 'ok' || rail.state === 'login_due';
}

/**
 * A known break in the rail, and its one fix. It heads any bike session's card, sent or
 * not, ahead of the coach's adjustment: whatever he approves will not arrive until it is
 * fixed.
 */
export function zwiftProblemLine(rail: ZwiftRail | null | undefined): string | null {
  if (rail?.state === 'paused') return ZWIFT_PAUSED_LINE;
  if (rail?.state === 'unlinked') return ZWIFT_UNLINKED_LINE;
  return null;
}

/** The Today card's line for a bike session already sent to intervals.icu. */
export function zwiftStatusLine(rail: ZwiftRail | null | undefined): string {
  if (reachesZwift(rail)) return ZWIFT_READY_LINE;
  return zwiftProblemLine(rail) ?? ZWIFT_UNKNOWN_LINE;
}

/** From 7 days before a free account would be paused, the date to log in by. */
export function zwiftLoginReminder(rail: ZwiftRail | null | undefined): string | null {
  if (!rail?.showLoginReminder || !rail.pauseDate) return null;
  return `Log in at intervals.icu before ${sessionDay(rail.pauseDate)} to keep your rides reaching Zwift.`;
}

export function adjustmentSentToast(rail: ZwiftRail | null | undefined): string {
  return reachesZwift(rail)
    ? "Coach's adjustment uploaded to Zwift"
    : "Coach's adjustment sent to intervals.icu";
}

export function intervalChangeSentToast(rail: ZwiftRail | null | undefined): string {
  return reachesZwift(rail)
    ? 'Interval change approved and uploaded to Zwift'
    : 'Interval change approved and sent to intervals.icu';
}

/** The tail of the coach's applied change: "…, and it's in Zwift." */
export function appliedChangeTail(rail: ZwiftRail | null | undefined): string {
  return reachesZwift(rail) ? 'and it’s in Zwift.' : 'and it’s sent to intervals.icu.';
}

/** Where an accepted plan's rides are going. */
export function acceptedRidesDestination(rail: ZwiftRail | null | undefined): string {
  return reachesZwift(rail) ? 'Zwift' : 'intervals.icu';
}
