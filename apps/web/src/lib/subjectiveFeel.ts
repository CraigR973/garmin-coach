/** Shared feel vocabulary: the stored contract is the full 0-10
 *  `subjectiveScore`; the words are anchors so the app can still speak Mark's
 *  check-in back in human terms. */
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
