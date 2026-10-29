/**
 * Batch 340 (FC331-01): this week's Dumbbells A and B onto his watch, on his tap. Draft
 * words for Craig's sign-off (docs/drafts/2026-10-29-batch-340-wording.md).
 */
export const STRENGTH_ON_WATCH_BUTTON = "Put this week's dumbbells on your watch";
export const STRENGTH_ON_WATCH_FAILED = "Couldn't reach Garmin. Try again in a minute.";

export function strengthOnWatchToast(result: {
  placed: string[];
  alreadyThere: string[];
  failed: string[];
}): string {
  if (result.failed.length > 0) {
    return `Couldn't send ${result.failed.join(' and ')} to Garmin. Try again in a minute.`;
  }
  if (result.placed.length > 0) {
    return `On your watch after its next sync: ${result.placed.join(' and ')}.`;
  }
  return 'Already on your watch.';
}
