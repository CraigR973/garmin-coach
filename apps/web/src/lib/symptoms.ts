import type { SymptomAnswer } from '@coach/shared';

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
