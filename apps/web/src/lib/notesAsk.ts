/**
 * Batch 297: Home asks the symptom question when his check-in note may name a symptom.
 * The note can only add caution; his answer to the question governs. Wording for Craig
 * to sign off on Mark's behalf (docs/drafts/2026-09-30-batch-297-wording.md).
 */
export const NOTES_ASK_TITLE = 'Any symptoms today?';
export const NOTES_ASK_BUTTON = 'Answer';

export function notesAskLine(words: string | null | undefined): string {
  const quoted = words?.trim();
  if (quoted) {
    return `Your note mentions “${quoted}”. If that’s a symptom, tell me, so today’s plan fits.`;
  }
  return 'Something in your note might be a symptom. If it is, tell me, so today’s plan fits.';
}
