/**
 * Batch 320: the morning check-in asks, in one tap, whether he followed last night's
 * advice. The server's words (`services/tonight_advice.FOLLOW_QUESTION` and
 * `FOLLOW_LABELS`); a test there holds the two together. Draft for Craig's sign-off
 * (docs/drafts/2026-10-29-batch-320-wording.md).
 */
export const TONIGHT_ADVICE_QUESTION = "Last night's advice: did you manage it?";

export const TONIGHT_ADVICE_ANSWERS = [
  ['followed', 'Yes, I did'],
  ['not_followed', 'Not this time'],
] as const;
