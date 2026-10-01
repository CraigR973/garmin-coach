import type { SymptomAnswer } from '@coach/shared';
import symptomNotices from './symptomNotices.json';

/** Batch 294: the morning check-in's "Any symptoms today?", in the order it is shown.
 *  The wording was signed off by Craig on Mark's behalf on 28 Sep 2026
 *  (docs/drafts/2026-09-28-batch-294-wording.md). The server decides what each answer
 *  does to the day (`services/symptom_check.py`); this file only words the question. */
export const SYMPTOM_QUESTION = 'Any symptoms today?';

export const SYMPTOM_OPTIONS: ReadonlyArray<{
  value: SymptomAnswer;
  label: string;
  detail: string | null;
}> = [
  { value: 'none', label: 'None', detail: null },
  { value: 'head_cold', label: 'Head cold', detail: 'Runny or blocked nose, sneezing, sore throat' },
  {
    value: 'fever_aches',
    label: 'Fever or aches',
    detail: 'A temperature, aching muscles, or a chesty cough',
  },
  {
    value: 'chest_heart',
    label: 'Chest or heart',
    detail: 'Chest pain or tightness, a racing or irregular heartbeat, or feeling faint',
  },
];

/** None is preselected, so an ordinary morning costs him nothing. */
export const DEFAULT_SYMPTOM_ANSWER: SymptomAnswer = 'none';

export type FloorSymptomAnswer = Exclude<SymptomAnswer, 'none'>;

export interface SymptomNoticeText {
  /** The notice card's level, which sets its heading (Batch 293). */
  level: 'rest' | 'ease';
  notice: string;
}

/** Batch 301: the notice each floor answer sets, shown the moment he picks it and on a
 *  morning whose brief could not be written. Until then it reached him only inside the
 *  stored morning, which exists only after the paid brief succeeds, so in an Anthropic
 *  outage a "Chest or heart" answer showed no 999, 111 or GP advice at all.
 *
 *  The text is the server's (`services/symptom_check.SYMPTOM_FLOORS`), as Home shows it on
 *  a written morning. `symptomNotices.json` is a copy, and
 *  `apps/api/tests/test_batch_301_symptom_notice_parity.py` fails the moment the two
 *  differ, so this is never the place to reword a notice. */
export const SYMPTOM_NOTICES: Readonly<Record<FloorSymptomAnswer, SymptomNoticeText>> =
  symptomNotices as Record<FloorSymptomAnswer, SymptomNoticeText>;

/** The notice for an answer, or null for None and for no answer at all. */
export function symptomNotice(
  answer: SymptomAnswer | null | undefined,
): SymptomNoticeText | null {
  if (answer == null || answer === 'none') return null;
  return SYMPTOM_NOTICES[answer] ?? null;
}
