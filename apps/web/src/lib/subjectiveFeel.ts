/** Shared Batch 94 vocabulary: the morning feel input stays a one-tap word
 *  scale in the UI even though the stored contract remains `subjectiveScore`.
 *  Keep the mapping in one place so Check-in and Home can't drift. */
export const SUBJECTIVE_FEEL_OPTIONS: Array<{ label: string; value: number }> = [
  { label: 'Rough', value: 2 },
  { label: 'Meh', value: 4 },
  { label: 'OK', value: 6 },
  { label: 'Good', value: 8 },
  { label: 'Great', value: 10 },
];

export function subjectiveFeelLabel(score: number | null | undefined): string | null {
  if (score == null) return null;
  const nearest = SUBJECTIVE_FEEL_OPTIONS.reduce((best, option) =>
    Math.abs(option.value - score) < Math.abs(best.value - score) ? option : best,
  );
  return nearest.label;
}
