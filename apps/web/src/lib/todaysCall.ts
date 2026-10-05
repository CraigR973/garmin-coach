import type { TodaysCall } from '@coach/shared';

/**
 * Batch 313: what the web needs to know about today's call besides its words, which the
 * server stores with each morning (`todaysCall`, picked by `services/todays_call`).
 */

/** State 16: nothing planned, and the day is outside every plan week. */
export const NO_SESSION_PLANNED_STATE = 16;

/** State 17: the one call with no stored morning behind it. */
export const NOT_READY_CALL: TodaysCall = {
  state: 17,
  key: 'not_ready',
  headline: 'Not ready yet',
  line: "Today's call lands once your overnight data has synced.",
  reading: 'waiting',
  readingWords: 'Waiting for data',
  look: 'neutral',
};

/** Home greets in front of every call but the health warnings, whose line is unchanged
 *  from before (signed off 28 Sep 2026), and the not-ready call, which is not a morning. */
export function greetsCall(call: TodaysCall | null | undefined): boolean {
  return call != null && call.look !== 'warning' && call.state !== NOT_READY_CALL.state;
}
