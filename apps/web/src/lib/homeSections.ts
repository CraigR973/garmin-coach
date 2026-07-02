import type { DailyPhase } from '@/hooks/useDailyPhase';

/**
 * The full set of Home sections (Batch 37 — collapse-not-remove).
 *
 * `afterRide`/`tomorrow` are the only data-gated members — they exist once a
 * ride has been analysed today; the rest are always present. Nothing is gated
 * by *phase* (that was the Batch 24 remove-model this supersedes — the
 * "read-first Home" of DECISIONS #91 / #97): off-phase sections are collapsed,
 * not absent.
 */
export type HomeSectionKey =
  | 'lastNight'
  | 'today'
  | 'afterRide'
  | 'tomorrow'
  | 'tonight'
  | 'bedroom';

/**
 * Which single section is primary (expanded) for each data state. Exactly one
 * section is expanded per load; every other section renders collapsed-but-
 * present. This keeps Batch 24's single-primary focus while paying back its
 * object-permanence cost.
 */
export const PRIMARY_BY_PHASE: Record<DailyPhase, HomeSectionKey> = {
  pre_ride: 'today',
  post_ride: 'afterRide',
  rest_day: 'lastNight',
};

/** Base chronological order of the full section set. */
const BASE_ORDER: HomeSectionKey[] = [
  'lastNight',
  'today',
  'afterRide',
  'tomorrow',
  'tonight',
  'bedroom',
];

/** Sections the evening clock nudge floats up ("bedroom-prep — what's next"). */
const EVENING_FLOAT: HomeSectionKey[] = ['tonight', 'bedroom'];

/** Local hour at/after which the evening ordering nudge applies. */
export const EVENING_HOUR = 20;

/**
 * Order the present sections for the current state.
 *
 * State (`phase`) is the only driver of *presence* and *which is primary*: the
 * primary section leads, the rest keep base order. The clock only *nudges
 * ordering* — after ~20:00 it floats the bedroom-prep sections up to just
 * behind the primary — and never adds, removes, or re-picks a section. So Home
 * is correct whether Mark rides at 06:00 or 18:00.
 */
export function orderedSections(
  phase: DailyPhase,
  { hasRide, isEvening }: { hasRide: boolean; isEvening: boolean },
): HomeSectionKey[] {
  const present = BASE_ORDER.filter((key) =>
    key === 'afterRide' || key === 'tomorrow' ? hasRide : true,
  );
  const primary = PRIMARY_BY_PHASE[phase];
  const lead = present.includes(primary) ? [primary] : [];
  const floated = isEvening
    ? present.filter((key) => EVENING_FLOAT.includes(key) && !lead.includes(key))
    : [];
  const remaining = present.filter((key) => !lead.includes(key) && !floated.includes(key));
  return [...lead, ...floated, ...remaining];
}

/** True at/after the evening hour in local time — the ordering-nudge trigger. */
export function isEveningNow(date = new Date()): boolean {
  return date.getHours() >= EVENING_HOUR;
}
