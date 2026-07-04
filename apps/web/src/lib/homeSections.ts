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
 * Which single section is primary (expanded) for the current loop phase
 * (Batch 48 generalised model). Exactly one section is expanded per load;
 * every other section renders collapsed-but-present.
 *
 * `post_training` depends on whether the completed read was a *ride*: a ride's
 * read lives in its own `afterRide` section, whereas a strength/flexibility/walk
 * read renders inside the Today card — so a non-ride day leads with `today`.
 * The evening `wind_down` leads with `tonight` (sleep prep — Batch 46).
 */
export function primarySection(
  phase: DailyPhase,
  { hasRide }: { hasRide: boolean },
): HomeSectionKey {
  switch (phase) {
    case 'wind_down':
      return 'tonight';
    case 'post_training':
      return hasRide ? 'afterRide' : 'today';
    case 'rest_day':
      return 'lastNight';
    case 'pre_training':
      return 'today';
  }
}

/** Base chronological order of the full section set. */
const BASE_ORDER: HomeSectionKey[] = [
  'lastNight',
  'today',
  'afterRide',
  'tomorrow',
  'tonight',
  'bedroom',
];

/** Sections the evening `wind_down` floats up ("bedroom-prep — what's next"). */
const EVENING_FLOAT: HomeSectionKey[] = ['tonight', 'bedroom'];

/** Local hour at/after which the day tips into its wind-down phase. */
export const EVENING_HOUR = 20;

/**
 * Order the present sections for the current state.
 *
 * The primary section leads and the rest keep base order. In the evening
 * `wind_down` phase the bedroom-prep sections (`tonight` + `bedroom`) float up
 * right behind the primary. Presence is only ever gated by `hasRide` (the
 * ride-only sections), never by phase — so Home is correct whether Mark trains
 * at 06:00 or 18:00.
 *
 * The primary defaults to the phase's `primarySection`, but the caller may pass
 * an explicit `primary` to override it — the Batch 50 action-first rule, where
 * the section holding the top pending action leads and expands regardless of
 * phase (`actionSection(nextAction) ?? primarySection(phase)`). The ordering
 * algorithm and evening-float are otherwise unchanged.
 */
export function orderedSections(
  phase: DailyPhase,
  { hasRide, isEvening, primary }: { hasRide: boolean; isEvening: boolean; primary?: HomeSectionKey },
): HomeSectionKey[] {
  const present = BASE_ORDER.filter((key) =>
    key === 'afterRide' || key === 'tomorrow' ? hasRide : true,
  );
  const lead0 = primary ?? primarySection(phase, { hasRide });
  const lead = present.includes(lead0) ? [lead0] : [];
  const floated = isEvening
    ? present.filter((key) => EVENING_FLOAT.includes(key) && !lead.includes(key))
    : [];
  const remaining = present.filter((key) => !lead.includes(key) && !floated.includes(key));
  return [...lead, ...floated, ...remaining];
}

/** True at/after the evening hour in local time — the wind-down trigger. */
export function isEveningNow(date = new Date()): boolean {
  return date.getHours() >= EVENING_HOUR;
}

/**
 * Splits an already-ordered section list into the one lead (primary,
 * expanded) section and the rest, which recede under the Batch 54 "More
 * detail" grouping. Mirrors the same one-expanded rule `orderedSections` used
 * to place `primary` first — if `primary` isn't present in `order` (it always
 * is in practice), nothing is treated as lead, matching the pre-54 behaviour
 * where no section would be `defaultOpen`.
 */
export function splitPrimaryDetail(
  order: HomeSectionKey[],
  primary: HomeSectionKey,
): { lead: HomeSectionKey | null; detail: HomeSectionKey[] } {
  const lead = order.includes(primary) ? primary : null;
  const detail = order.filter((key) => key !== lead);
  return { lead, detail };
}

/**
 * Which desktop lane a section belongs to (Batch 51 — two-column dashboard,
 * `md+` only; mobile stays the single stacked column driven by `orderedSections`
 * alone). `act` = the do-something-now sections; `context` = the read-first
 * sleep/environment sections. `tomorrow` rides with `act` since it's the direct
 * forward continuation of a ride's `afterRide` read, not a standalone context card.
 */
export function sectionLane(key: HomeSectionKey): 'act' | 'context' {
  switch (key) {
    case 'today':
    case 'afterRide':
    case 'tomorrow':
      return 'act';
    case 'lastNight':
    case 'tonight':
    case 'bedroom':
      return 'context';
  }
}
