/**
 * Batch 323: his next plan, proposed in the app for him to accept, change or decline.
 *
 * Home shows a card from his taper week (the last week of a plan) and on any day no plan
 * covers, while a drafted plan waits for him; it leads to the plan builder, where he can
 * change any day, accept the plan (it goes into his plan and its rides to Zwift) or
 * decline it (nothing changes). Wording signed off on Mark's behalf under Craig's
 * delegation of 6 Oct 2026 (docs/drafts/2026-10-07-batch-323-wording.md); the tests hold
 * every line here to that draft.
 */
export const NEXT_PLAN_TITLE = 'Your next plan is ready';
export const NEXT_PLAN_BUTTON = 'Review it';
export const WHY_THIS_PLAN = 'Why this plan';
export const ACCEPT_PLAN = 'Accept this plan';
export const DECLINE_PLAN = 'Decline';
export const DECLINED = 'Plan declined. Nothing in your plan has changed.';
export const MAKE_PLAN_TITLE = 'Make your next plan';
export const MAKE_PLAN_LINE = 'Builds the next 13 weeks from your last plan.';
export const MAKE_PLAN_BUTTON = 'Make the plan';
export const MADE = 'Your next plan is ready to review.';

const WEEKDAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
const MONTHS = [
  'January',
  'February',
  'March',
  'April',
  'May',
  'June',
  'July',
  'August',
  'September',
  'October',
  'November',
  'December',
];
const SHORT_WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const SHORT_MONTHS = MONTHS.map((month) => month.slice(0, 3));

function parts(isoDate: string): { weekday: number; day: number; month: number } {
  const [year, month, day] = isoDate.split('-').map(Number);
  const value = new Date(Date.UTC(year, month - 1, day));
  return { weekday: value.getUTCDay(), day: value.getUTCDate(), month: value.getUTCMonth() };
}

/** "Monday 19 October". */
export function longDate(isoDate: string): string {
  const { weekday, day, month } = parts(isoDate);
  return `${WEEKDAYS[weekday]} ${day} ${MONTHS[month]}`;
}

/** "Tue 20 Oct", for each session in the builder. */
export function sessionDay(isoDate: string): string {
  const { weekday, day, month } = parts(isoDate);
  return `${SHORT_WEEKDAYS[weekday]} ${day} ${SHORT_MONTHS[month]}`;
}

/** "19 Oct → 17 Jan". */
export function planSpan(startDate: string, endDate: string): string {
  const start = parts(startDate);
  const end = parts(endDate);
  return `${start.day} ${SHORT_MONTHS[start.month]} → ${end.day} ${SHORT_MONTHS[end.month]}`;
}

/** Home's line: when it starts, or, once that day has come, that it is ready to start. */
export function nextPlanLine(planName: string, startDate: string, today: string): string {
  const when =
    startDate > today ? `starts ${longDate(startDate)}` : 'is ready to start';
  return `${planName} ${when}. Review it, change any day you like, then accept it.`;
}

/** Batch 326: `destination` is intervals.icu while rides are not reaching Zwift. */
export function acceptedLine(planName: string, destination: string = 'Zwift'): string {
  return `${planName} is in your plan, and its rides are on their way to ${destination}.`;
}

export function lockedTitle(planName: string): string {
  return `${planName} is in your plan`;
}
