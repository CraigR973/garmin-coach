const NUMBER_WORDS = ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten'];

/**
 * Batch 284: the coach's offer to test something Mark has said — Part 1c of the
 * 24 Sep wording sheet ("a proper side-by-side", the sheet's own correction of
 * "before-and-after"). It says "a few times now" only when more than one source
 * backs it, and "one full week an arm" only when the comparison needs seven nights.
 */
export function experimentOffer(experiment: {
  metricLabel: string;
  nightsPerGroup: number;
  evidenceCount: number;
}): string {
  const opening =
    experiment.evidenceCount > 1
      ? "You've said that a few times now, and it's the kind of thing we can actually test rather than argue about."
      : "You've said this, and it's the kind of thing we can actually test rather than argue about.";
  const nights = NUMBER_WORDS[experiment.nightsPerGroup] ?? String(experiment.nightsPerGroup);
  const week =
    experiment.nightsPerGroup === 7
      ? " — that's one full week an arm, because anything shorter compares a week against a different part of the same cycle"
      : '';
  return (
    `${opening} I can set it up as a proper side-by-side: your recovery weeks against your build weeks, ` +
    `on ${experiment.metricLabel}. It needs ${nights} nights in each before it'll say anything${week}.`
  );
}
