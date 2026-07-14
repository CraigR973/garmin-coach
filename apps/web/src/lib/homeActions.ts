import type { DailyLoopData } from '@/hooks/useDailyLoop';
import { isBikeWorkout } from '@/hooks/useDailyPhase';
import type { HomeSectionKey } from '@/lib/homeSections';

/**
 * The single "what needs Mark next" action for Home (Batch 50 — action-first).
 *
 * Since Batch 45 the app is push-first: the morning verdict and every
 * post-workout read push the moment they land, so Mark arrives on Home to *act*.
 * This resolver turns the daily-loop payload into the one context-aware primary
 * action — driving both the "Next" strip under the verdict hero and (via
 * {@link actionSection}) which section is expanded, overriding the Batch 37/48
 * phase→primary selection so a pending item is never stranded in a collapsed
 * off-phase section.
 *
 * It is deliberately **payload-only and pure** (no clock read of its own — the
 * caller threads a single `isEvening`), so the whole priority ladder is
 * unit-testable. `sectionKey` marks an action that lives in a Home section (the
 * expansion override target); `to` marks one that navigates away.
 */
export type ActionTone = 'warning' | 'default' | 'muted';

export interface NextAction {
  /** Stable identifier for the firing rung (tests + React keys). */
  key: 'say-good-morning' | 'review-sleep' | 'review-ride' | 'log-ride' | 'protect-sleep' | 'all-set';
  label: string;
  /** Route to navigate to, for actions that leave Home. */
  to?: string;
  /** Home section to expand + scroll to, for actions that live on Home. */
  sectionKey?: HomeSectionKey;
  tone: ActionTone;
}

/** True when a bike session today was eased by the coach and still awaits a
 *  decision. Mirrors `WorkoutRow`'s `hasPendingChange` minus the client-only
 *  `ignored` dismiss (which isn't on the payload — Ignore is a per-view dismiss,
 *  #99, and the underlying change is still pending until approved). */
function hasPendingCoachChange(data: DailyLoopData): boolean {
  return data.plannedWorkouts.some(
    (workout) => Boolean(workout.delivery?.changed) && isBikeWorkout(workout.workoutType),
  );
}

/** The first ride analysed today whose "how did it feel" check-in is still
 *  empty, or `null` if every analysed ride has been logged. */
function firstUnloggedRide(data: DailyLoopData): DailyLoopData['postWorkoutAnalyses'][number] | null {
  return (data.postWorkoutAnalyses ?? []).find((analysis) => analysis.postRideCheckIn == null) ?? null;
}

function reviewRide(): NextAction {
  return { key: 'review-ride', label: "Review today's eased ride", sectionKey: 'today', tone: 'warning' };
}

function isHolidayAway(data: DailyLoopData): boolean {
  return data.holiday.isActive;
}

/**
 * Resolve the top action from the deterministic priority ladder.
 *
 * The morning check-in is **optional** (Batch 60, revising DECISIONS #127): it
 * captures subjective/BP data that enriches the read and can ease the ride, but
 * it is offered — on `/sleep` and the Today footer — never nagged, so it is no
 * longer a rung here. Reviewing last night is the one required morning step, and
 * "review last night" + "check in" collapse into that single step.
 *
 * The ordering is **time-of-day-shaped** in one place: the morning. Once Mark's
 * overnight metrics have synced he starts the day by reading last night, and
 * only then approves any eased ride — so in the `pre_training` / `rest_day`
 * phase (`isMorning`) the ladder is:
 *
 * 0. today's brief doesn't exist yet → say good morning (`/check-in`, Batch 95 —
 *    keeps this strip from contradicting the `GoodMorningCta` hero, which shows
 *    whenever `morningAnalysis` is null, with a stale "You're all set");
 * 1. metrics synced & sleep not yet opened today → review last night (`/sleep`);
 * 2. a bike workout with a pending coach change → review it (expand `today`).
 *
 * The rest of the day keeps the need-first order (the ride's Zwift consequence
 * makes it the top concern once he's up and about):
 *
 * 1. a bike workout with a pending coach change → review it (expand `today`);
 * 2. a ride analysed today with no post-ride check-in → log it, named.
 *
 * Both ladders share a tail: evening & tonight needs protecting → `/sleep`; else
 * a quiet "you're all set". Only protect-sleep is evening-gated.
 * `hasReviewedSleep` is a per-day client flag the caller threads (set when Mark
 * opens `/sleep`), so the sleep rung completes rather than nagging with no
 * completion signal.
 */
export function nextAction(
  data: DailyLoopData,
  {
    isEvening,
    isMorning = false,
    hasReviewedSleep = false,
  }: { isEvening: boolean; isMorning?: boolean; hasReviewedSleep?: boolean },
): NextAction {
  if (isMorning) {
    if (data.morningAnalysis == null) {
      return { key: 'say-good-morning', label: 'Say good morning', to: '/check-in', tone: 'default' };
    }
    if (!hasReviewedSleep) {
      return { key: 'review-sleep', label: "Review last night's sleep", to: '/sleep', tone: 'default' };
    }
    if (hasPendingCoachChange(data)) {
      return reviewRide();
    }
  } else {
    if (hasPendingCoachChange(data)) {
      return reviewRide();
    }
    const unloggedRide = firstUnloggedRide(data);
    if (unloggedRide) {
      const rideName = unloggedRide.activityName ?? 'your ride';
      return {
        key: 'log-ride',
        label: `Log how ${rideName} felt`,
        // Batch 60: a completed *planned* ride's check-in lives on its Today-card
        // row; only an unplanned ride keeps the standalone After-your-ride section.
        sectionKey: unloggedRide.plannedWorkoutId ? 'today' : 'afterRide',
        tone: 'warning',
      };
    }
  }
  if (isEvening && data.sleepProjection?.tone === 'protect') {
    if (isHolidayAway(data)) {
      return { key: 'all-set', label: "You're all set", tone: 'muted' };
    }
    return { key: 'protect-sleep', label: "Protect tonight's sleep", to: '/sleep', tone: 'warning' };
  }
  return { key: 'all-set', label: "You're all set", tone: 'muted' };
}

/**
 * The Home section an action wants expanded, or `null` for a navigate-away /
 * all-clear action. This is the Batch 50 override that beats the phase primary
 * in `homeSections` (`actionSection(nextAction) ?? primarySection(phase)`).
 */
export function actionSection(action: NextAction): HomeSectionKey | null {
  return action.sectionKey ?? null;
}
