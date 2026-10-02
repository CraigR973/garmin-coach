/**
 * Batch 297: Home asks the symptom question when his check-in note may name a symptom.
 * The note can only add caution; his answer to the question governs. Wording signed off
 * by Craig on Mark's behalf (docs/drafts/2026-09-30-batch-297-wording.md).
 *
 * Batch 303: the question is answered on Home, in one tap, with the check-in's four
 * answers (`lib/symptoms.ts`). Its button used to open the check-in, where None is
 * already selected, and saving that form was "his answer". When the note may mean a chest
 * or heart symptom and a hard session is planned, that session is an easy ride until he
 * answers, and the card says so. Signed off 2 Oct 2026
 * (docs/drafts/2026-10-02-batch-303-wording.md). The server writes the same sentence
 * under the colour (`services/symptom_check.chest_question_line`); a test there holds
 * the two together.
 */
export const NOTES_ASK_TITLE = 'Any symptoms today?';
export const NOTES_ASK_UPDATING = 'Thanks. Updating today’s call.';

export function notesAskLine(words: string | null | undefined, eases = false): string {
  const quoted = words?.trim();
  if (eases) {
    const lead = quoted
      ? `Your note mentions “${quoted}”.`
      : 'Something in your note might be a symptom.';
    return `${lead} Until you answer, today’s hard session is an easy ride.`;
  }
  if (quoted) {
    return `Your note mentions “${quoted}”. If that’s a symptom, tell me, so today’s plan fits.`;
  }
  return 'Something in your note might be a symptom. If it is, tell me, so today’s plan fits.';
}
