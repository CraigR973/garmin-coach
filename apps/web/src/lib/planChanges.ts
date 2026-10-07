import type { GeneratedBlockWorkout, PlanDays } from '@coach/shared';

/**
 * Batch 324: change anything in the proposed plan, and talk it through with the coach.
 *
 * The plan builder's controls, and the coach's offer card, in the words signed off on
 * Mark's behalf under Craig's delegation of 6 Oct 2026
 * (docs/drafts/2026-10-07-batch-324-wording.md); the tests hold every line here to that
 * draft. What each change says it did comes from the server, in the same draft's words.
 */
export const DAYS_HEADING = 'Your days';
export const DAYS_LINE = 'Which day each session is on, every week.';
export const CHANGE_DAYS = 'Change your days';
export const REBUILD = 'Rebuild with these days';
export const START_HEADING = 'Starts';
export const START_LINE = 'Everything moves with it, your changes too.';
export const CHANGE_START = 'Change the start';
export const NOTHING_PLANNED = 'Nothing planned';
export const CHANGE = 'Change';
export const MOVE = 'Move';
export const REMOVE = 'Remove';
export const ADD = 'Add';
export const NAME = 'Name';
export const MINUTES = 'Minutes';
export const REPS = 'Reps';
export const EFFORT_SECONDS = 'Effort (seconds)';
export const EFFORT_PCT = 'Effort (% of FTP)';
export const RECOVERY_SECONDS = 'Recovery (seconds)';
export const RECOVERY_PCT = 'Recovery (% of FTP)';
export const SAVE = 'Save';
export const CANCEL = 'Cancel';
export const MOVE_TO = 'Move to';
export const KEEP_IT = 'Keep it';
export const YOUR_CHANGES = 'Your changes';
export const COACH_SUGGESTION = "(the coach's suggestion)";
export const RESET = 'Back to the plan as proposed';
export const RESET_LINE = "This undoes every change you've made.";
export const RESET_CONFIRM = 'Undo my changes';
export const KEEP_THEM = 'Keep them';
export const WHY_AS_PROPOSED = 'Why this plan, as proposed';
export const TALK_TO_COACH = 'Talk it through with the coach';

export const OFFER_HEADING = 'Change to your next plan';
export const APPLY = 'Apply this change';
export const APPLYING = 'Applying…';
export const APPLIED =
  "Done: it's in your proposed plan. Nothing goes to Zwift until you accept the plan.";
export const SEE_PLAN = 'See the plan';

/** The order the builder lists his days in, and each one's name. */
export const DAY_KEYS = [
  'strengthA',
  'vo2',
  'zone2',
  'sweetSpot',
  'rest',
  'sprints',
  'strengthB',
  'longRide',
] as const satisfies readonly (keyof PlanDays)[];

export const DAY_LABELS: Record<keyof PlanDays, string> = {
  strengthA: 'Dumbbells A',
  vo2: 'VO₂',
  zone2: 'Zone 2',
  sweetSpot: 'Sweet spot',
  rest: 'Rest day',
  sprints: 'Sprint ride',
  strengthB: 'Dumbbells B',
  longRide: 'Long ride',
};

/** Monday 0, as the draft carries them. */
export const WEEKDAY_NAMES = [
  'Monday',
  'Tuesday',
  'Wednesday',
  'Thursday',
  'Friday',
  'Saturday',
  'Sunday',
];

/** What he can add to a day, and its default length (strength takes that week's dose). */
export const ADD_TYPES = [
  { type: 'zone2', label: 'Zone 2', minutes: 60 },
  { type: 'easy', label: 'Easy spin', minutes: 45 },
  { type: 'long', label: 'Long ride', minutes: 120 },
  { type: 'strength_a', label: 'Dumbbells A', minutes: null },
  { type: 'strength_b', label: 'Dumbbells B', minutes: null },
] as const;

export type AddType = (typeof ADD_TYPES)[number]['type'];

export function rebuildWarning(count: number): string {
  const plural = count === 1 ? 'change' : 'changes';
  return `Changing your days rebuilds the plan, so your ${count} ${plural} to single sessions will go.`;
}

/** "7 h 25", "7 h", "45 min". */
export function hoursAndMinutes(minutes: number): string {
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest === 0 ? `${hours} h` : `${hours} h ${String(rest).padStart(2, '0')}`;
}

/** "Week 2 · BUILD". */
export function weekHeading(weekNumber: number, label: string): string {
  return `Week ${weekNumber} · ${label}`;
}

export function overLongest(previousPlan: string, longestMin: number): string {
  return `Longer than your longest week of ${previousPlan} (${hoursAndMinutes(longestMin)}).`;
}

export function minutesLabel(min: number, max: number): string {
  return `${MINUTES} (${min} to ${max})`;
}

export function matchingSets(count: number): string {
  return `This ride has ${count} matching sets; they change together.`;
}

export function removeQuestion(title: string, day: string): string {
  return `Remove ${title} on ${day}?`;
}

export function addTo(day: string): string {
  return `Add to ${day}`;
}

/** The plan's dates, Monday to Sunday of each week, as ISO dates. */
export function weekDates(startDate: string): string[] {
  const [year, month, day] = startDate.split('-').map(Number);
  return Array.from({ length: 7 }, (_, offset) => {
    const value = new Date(Date.UTC(year, month - 1, day + offset));
    return value.toISOString().slice(0, 10);
  });
}

/** A ride, as the delivery rail sees one: Zwift takes one ride a day. */
export function isRide(workout: GeneratedBlockWorkout): boolean {
  return workout.structuredWorkout?.format === 'bike';
}
