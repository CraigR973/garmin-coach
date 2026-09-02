import { BriefFailedCta } from '@/components/BriefFailedCta';
import { BriefGeneratingCta } from '@/components/BriefGeneratingCta';
import { GoodMorningCta } from '@/components/GoodMorningCta';
import type { DailyLoopData } from '@/hooks/useDailyLoop';
import { friendlyDate } from '@/lib/dailyFlow';
import { overnightDataReady } from '@/lib/homeActions';

export type BriefPendingState = 'failed' | 'generating' | 'not-checked-in';

/**
 * Which of the three pre-brief states today is in.
 *
 * Batch 248 (UX241-02). This lived as a ternary chain inside `DashboardPage`,
 * and `/brief` — the page the "brief is ready" push actually opens — had no
 * equivalent at all: it rendered one "No morning brief yet" card for `failed`,
 * `generating` and `not-checked-in` alike. The three captures were byte-identical.
 *
 * So on a morning when generation failed, Mark was told on the app's most
 * important page to wait for something that was never coming, with no retry and
 * no hint that anything had gone wrong — the 2026-07-21 credit-outage experience
 * Batch 141 existed to end, ended on one screen out of two.
 *
 * Exported as one function used by both pages rather than copied, because a rule
 * paraphrased in two places is the defect class this whole wave is about.
 */
export function briefPendingState(daily: DailyLoopData): BriefPendingState {
  // Batch 141: a failure outranks the generating state — a failure always has a
  // check-in behind it, so `manualEntry` is set in both cases and testing it
  // first would show a spinner for a brief that already gave up.
  if (daily.briefGeneration?.status === 'failed') return 'failed';
  if (daily.manualEntry != null) return 'generating';
  return 'not-checked-in';
}

/** The hero slot for a day whose brief does not exist yet, in any of its three states. */
export function BriefPendingCta({ daily }: { daily: DailyLoopData }) {
  const dateLabel = friendlyDate(daily.subjectDate);
  switch (briefPendingState(daily)) {
    case 'failed':
      return <BriefFailedCta dateLabel={dateLabel} />;
    case 'generating':
      return <BriefGeneratingCta dateLabel={dateLabel} />;
    default:
      return <GoodMorningCta dateLabel={dateLabel} overnightDataReady={overnightDataReady(daily)} />;
  }
}
