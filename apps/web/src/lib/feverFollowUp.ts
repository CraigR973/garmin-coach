import type { FeverFollowUpAnswer } from '@coach/shared';

/**
 * Batch 364 (HS361-02): after a fever, aches or a chest infection, Home asks each morning
 * whether it has gone for a full day without paracetamol or ibuprofen. Until he says so,
 * riding stays easy and strength is gentle mobility; his "Gone" starts the two easy days
 * back. "Still there" sets the fever warning again that day.
 *
 * Drafts for Craig's sign-off (docs/drafts/2026-11-02-batch-364-wording.md).
 * `apps/api/tests/test_batch_364_no_data_morning.py` holds the buttons to the server's
 * labels, so this is never the place to reword one.
 */
export function feverFollowUpTitle(weekday: string): string {
  return `Fever, aches or a chest infection on ${weekday}`;
}

export const FEVER_FOLLOW_UP_ASK =
  'Has it gone for a full day, without paracetamol or ibuprofen? Until it has, riding stays easy.';

export const FEVER_FOLLOW_UP_OPTIONS: ReadonlyArray<{
  value: FeverFollowUpAnswer;
  label: string;
}> = [
  { value: 'cleared', label: 'Gone for a full day, without paracetamol or ibuprofen' },
  { value: 'still_there', label: 'Still there' },
];
