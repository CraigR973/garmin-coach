/** Batch 366 (UX362-02): a switch for each kind of push. Settings offered only on or
 *  off for every push (161 in 25 days); missing-data alerts answer to no switch. */
export type PushKind = 'push_reads' | 'push_bedroom' | 'push_reviews';
export type Preferences = Record<PushKind, boolean>;

export const PUSH_KIND_ROWS: { kind: PushKind; title: string; detail: string }[] = [
  {
    kind: 'push_reads',
    title: 'Morning brief and workout reads',
    detail: 'When your brief is ready, and one check-in a day after a session.',
  },
  {
    kind: 'push_bedroom',
    title: 'Bedroom and tonight’s sleep',
    detail: 'Tonight’s sleep read at 20:00, and a bedroom alert only when the room is too warm or too cold.',
  },
  {
    kind: 'push_reviews',
    title: 'Weekly review',
    detail: 'When Sunday’s review is ready.',
  },
];
export const PUSH_KINDS_FOOTNOTE = 'Alerts that your watch or bedroom data has stopped arriving always come through.';
