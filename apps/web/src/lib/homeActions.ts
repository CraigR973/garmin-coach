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
  key: 'review-ride' | 'log-ride' | 'check-in' | 'protect-sleep' | 'all-set';
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

/**
 * Resolve the top action from the deterministic priority ladder:
 *
 * 1. a bike workout with a pending coach change → review it (expand `today`);
 * 2. a ride analysed today with no post-ride check-in → log it, named, (expand `afterRide`);
 * 3. no morning check-in captured today → the post-sleep check-in (`/check-in`);
 * 4. evening & tonight's sleep needs protecting → protect it (`/sleep`);
 * 5. nothing pending → a quiet "you're all set".
 *
 * Need comes before time-of-day: rungs 1–3 fire regardless of the clock, so an
 * unactioned adjustment surfaces at 18:00 just as at 07:00. Only the
 * protect-sleep rung is evening-gated.
 *
 * Rungs 2 and 3 are both "check-ins" but ask about different things — the
 * label names which one so Mark never confuses "how did the ride feel" with
 * the post-sleep morning entry.
 */
export function nextAction(data: DailyLoopData, { isEvening }: { isEvening: boolean }): NextAction {
  if (hasPendingCoachChange(data)) {
    return { key: 'review-ride', label: "Review today's eased ride", sectionKey: 'today', tone: 'warning' };
  }
  const unloggedRide = firstUnloggedRide(data);
  if (unloggedRide) {
    const rideName = unloggedRide.activityName ?? 'your ride';
    return {
      key: 'log-ride',
      label: `Log how ${rideName} felt`,
      sectionKey: 'afterRide',
      tone: 'warning',
    };
  }
  if (!data.manualEntry) {
    return { key: 'check-in', label: 'Morning check-in', to: '/check-in', tone: 'default' };
  }
  if (isEvening && data.sleepProjection?.tone === 'protect') {
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
