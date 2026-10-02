import type { DailyLoopData } from '@/hooks/useDailyLoop';

/**
 * Batch 302: a morning is stored when it is graded, and its brief is written into it.
 *
 * The colour, the medical notices, the plan lines and Today's actions are worked out
 * before the paid call, and used to be thrown away with it when it failed: on 21 Jul
 * 2026 Mark had no colour for nine and a half hours on a Red day. The envelope now
 * carries the morning either way — as `morningAnalysis` once its brief is written, as
 * `gradedMorning` until then — and every surface that shows the colour reads it here,
 * so none of them can wait on the brief by accident.
 */
export type StoredMorning = NonNullable<DailyLoopData['morningAnalysis']>;

type MorningFields = Pick<DailyLoopData, 'morningAnalysis' | 'gradedMorning' | 'briefGeneration'>;

/** The day's morning as graded: with its written brief when there is one, else without. */
export function storedMorning(
  daily: Pick<MorningFields, 'morningAnalysis' | 'gradedMorning'> | null | undefined,
): StoredMorning | null {
  return daily?.morningAnalysis ?? daily?.gradedMorning ?? null;
}

/** Where the written brief is, for a day whose morning is stored. `null`: no morning yet. */
export type BriefState = 'written' | 'writing' | 'failed';

export function briefState(daily: MorningFields | null | undefined): BriefState | null {
  if (daily?.morningAnalysis != null) return 'written';
  if (daily?.gradedMorning == null) return null;
  return daily.briefGeneration?.status === 'failed' ? 'failed' : 'writing';
}

/**
 * Was his note left unread? In a full Anthropic outage the notes reader fails with the
 * brief, so the colour is graded without his note. The written brief is where the app
 * said so; a morning without one has to say it itself.
 */
export function noteUnread(morning: StoredMorning | null | undefined): boolean {
  return morning?.notesReadingStatus === 'failed' || morning?.notesReadingStatus === 'not_read';
}

/** A brief is on its way, so a screen showing the day should keep looking for it. */
export function briefOnItsWay(daily: MorningFields | null | undefined): boolean {
  return daily?.morningAnalysis == null && daily?.briefGeneration?.status === 'generating';
}
