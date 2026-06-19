// Single source of truth for knockout stage labels.
//
// Shared by SchedulePage (filter pills + section headings) and
// KnockoutPredictionsPage (round pills) so the two surfaces read as one
// system. `short` is the compact chip label; `long` is the full heading.

export interface KnockoutStage {
  /** Matches `MatchResponse.stage`. */
  key: string;
  /** Compact pill/chip label, e.g. "R32". */
  short: string;
  /** Full heading label, e.g. "Round of 32". */
  long: string;
}

// Bracket order: R32 → Final.
export const KNOCKOUT_STAGES: readonly KnockoutStage[] = [
  { key: 'r32', short: 'R32', long: 'Round of 32' },
  { key: 'r16', short: 'R16', long: 'Round of 16' },
  { key: 'qf', short: 'QF', long: 'Quarter-Finals' },
  { key: 'sf', short: 'SF', long: 'Semi-Finals' },
  { key: 'third_place', short: '3rd place', long: 'Third-Place Play-off' },
  { key: 'final', short: 'Final', long: 'Final' },
];

/** stage key → long heading label, e.g. `third_place` → "Third-Place Play-off". */
export const STAGE_LONG: Record<string, string> = Object.fromEntries(
  KNOCKOUT_STAGES.map((s) => [s.key, s.long]),
);
