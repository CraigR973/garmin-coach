import type { AcutePhysiology } from '@coach/shared';

/** The verdict headline on a morning that rules training out, on Home and the brief.
 *
 *  Batch 277 swapped the headline for "Take today off the bike" when an acute signal
 *  rules riding out. Batch 294 adds the wider case: a reported symptom that rules out
 *  training of any kind. Wording signed off by Craig on Mark's behalf, 28 Sep 2026. */
export function restHeadline(
  boundary: AcutePhysiology | null | undefined,
): { label: string; line: string } | null {
  if (boundary?.requiresTrainingRest === true) {
    return {
      label: 'No training today',
      line: "The symptoms you've reported rule out training today.",
    };
  }
  if (boundary?.requiresBikeRest === true) {
    return {
      label: 'Take today off the bike',
      line: 'An acute recovery signal rules out riding today.',
    };
  }
  return null;
}
