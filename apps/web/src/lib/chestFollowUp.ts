import type { ChestFollowUpAnswer } from '@coach/shared';

/**
 * Batch 315: after a chest or heart report, Home asks each morning whether the symptoms
 * have gone and whether he has spoken to his GP or 111, and a hard session is an easy ride
 * until he says both. "Still there" sets the chest-or-heart warning again that day.
 *
 * Wording signed off on Mark's behalf under Craig's delegation of 6 Oct 2026
 * (docs/drafts/2026-10-06-batch-315-wording.md). `apps/api/tests/test_batch_315_chest_follow_up.py`
 * holds every line here to that draft, so this is never the place to reword one.
 */
export function chestFollowUpTitle(weekday: string): string {
  return `Chest or heart symptoms on ${weekday}`;
}

export const CHEST_FOLLOW_UP_ASK =
  'Have they gone, and have you spoken to your GP or 111? Until you have, hard sessions are easy rides.';

export const CHEST_FOLLOW_UP_NOT_SEEN =
  "Thanks. Hard sessions stay easy rides until you've spoken to your GP or 111. I'll ask again tomorrow.";

export const CHEST_FOLLOW_UP_OPTIONS: ReadonlyArray<{
  value: ChestFollowUpAnswer;
  label: string;
}> = [
  { value: 'cleared', label: "Gone, and I've spoken to my GP or 111" },
  { value: 'not_seen', label: "Gone, but I haven't spoken to anyone yet" },
  { value: 'still_there', label: 'Still there' },
];

/** The card's line: the question, or, once he has said he has not spoken to anyone yet,
 *  what that means for today. The buttons stay, so he can say later that he has. */
export function chestFollowUpLine(answer: ChestFollowUpAnswer | null | undefined): string {
  return answer === 'not_seen' ? CHEST_FOLLOW_UP_NOT_SEEN : CHEST_FOLLOW_UP_ASK;
}
