/**
 * Batch 335: what the app says about the ride Zwift holds when it is not the plan row's.
 *
 * On 10 Oct 2026 Home said "Sweet Spot … 58 min … Already in Zwift, ready to ride." while
 * Zwift held a 29-minute spin capped at 60%: an earlier morning's easing, carried by a swap.
 * The API now sends the live ride and how it stands against the day (`liveRide` on Home's
 * delivery, `zwiftRide` on Week's rows); these are the words for it.
 *
 * The words are Craig's to sign off (docs/drafts/2026-10-27-batch-335-wording.md); the tests
 * hold every line here to that file.
 */
import { reachesZwift, type ZwiftRail } from '@/lib/zwiftRail';

export type LiveRide = {
  state: string;
  title: string;
  durationMin?: number | null;
  topPowerPct?: number | null;
};

export const LIVE_RIDE_AS_PLANNED = 'as_planned';
export const LIVE_RIDE_CHANGED = 'changed';
export const LIVE_RIDE_NOT_THIS_DAY = 'not_this_day';

export const NOT_THIS_DAY_LINE = 'That is not the ride planned for this day.';
export const RESTORE_PLAN_RIDE_LABEL = 'Put the planned ride on Zwift';
export const CHOOSE_ONE_TITLE = 'Choose one';
export const CHOOSE_ONE_LINE =
  'Move it or ride the easier version today, not both. Taking one takes the other away.';
export const SWAP_OR_EASE_LINE =
  'Or ride the easier version below instead. Taking one takes the other away.';

/** True when the screen should name the ride on Zwift: it is not the plan row's. */
export function showsLiveRide(ride: LiveRide | null | undefined): ride is LiveRide {
  return Boolean(ride && ride.state !== LIVE_RIDE_AS_PLANNED);
}

/** "On Zwift: “Recovery substitution: Sweet Spot”, 29 min, up to 60% FTP." */
export function liveRideLine(ride: LiveRide, rail: ZwiftRail | null | undefined): string {
  const where = reachesZwift(rail) ? 'On Zwift' : 'Sent to intervals.icu';
  const parts = [`“${ride.title}”`];
  if (ride.durationMin) parts.push(`${ride.durationMin} min`);
  if (ride.topPowerPct) parts.push(`up to ${ride.topPowerPct}% FTP`);
  return `${where}: ${parts.join(', ')}.`;
}

export function restoredToast(rail: ZwiftRail | null | undefined): string {
  return reachesZwift(rail)
    ? 'The planned ride is on Zwift.'
    : 'The planned ride is sent to intervals.icu.';
}
