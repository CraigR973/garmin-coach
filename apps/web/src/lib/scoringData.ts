/**
 * Shared scoring-data module — single source of truth for both ScoringGuide
 * (Predictions page) and AboutPage. Changes here propagate to both surfaces
 * automatically so they can never diverge.
 *
 * Numbers reconciled against the backend implementation in
 * apps/api/src/routers/specials.py (SPECIAL_POINTS dict) and
 * wc2026-architecture.md §7 (grand total ≈ 1,415).
 */

// ── Per-match scoring rows ────────────────────────────────────────────────────

export interface ScoringRow {
  label: string;
  note: string;
  pts: string;
  /** Visually accent this row (max / total). */
  accent?: boolean;
}

export const MATCH_SCORING_ROWS: ScoringRow[] = [
  {
    label: 'Correct combined goals',
    note: 'e.g. 2–1 vs 3–0: both = 3 goals',
    pts: '2',
  },
  {
    label: 'Correct result',
    note: 'Win / Draw / Loss',
    pts: '3',
  },
  {
    label: 'Exact scoreline',
    note: 'Both goals right',
    pts: '5',
  },
  {
    label: 'Maximum per match',
    note: 'All three stack',
    pts: '10',
    accent: true,
  },
];

// ── Worked-examples matrix ────────────────────────────────────────────────────

export interface WorkedExample {
  /** Total points for this scenario. One of the 5 achievable per-match totals. */
  total: 0 | 2 | 3 | 5 | 10;
  /** Your prediction (e.g. "2–1"). */
  predicted: string;
  /** Actual result (e.g. "3–0"). */
  actual: string;
  /** Human-readable points breakdown. */
  breakdown: string;
}

/**
 * One worked example for every achievable per-match total: 0, 2, 3, 5, 10.
 *
 * Verified against scoreMatchPrediction() in packages/shared/src/scoring.ts:
 *   - 0: wrong goals AND wrong result AND wrong score
 *   - 2: correct goals total only  (same combined total, wrong result)
 *   - 3: correct result only       (different goals, right W/D/L)
 *   - 5: correct result + goals    (no exact score)  → 2+3 = 5
 *   - 10: exact score              (implies goals + result)  → 2+3+5 = 10
 *
 * Note: 7 (goals + exact but wrong result) and 8 (result + exact but wrong goals)
 * are impossible — exact score always implies correct goals AND correct result.
 */
export const WORKED_EXAMPLES: WorkedExample[] = [
  {
    total: 10,
    predicted: '2–1',
    actual: '2–1',
    breakdown: 'Goals ✓ (2) + Result ✓ (3) + Exact ✓ (5) = 10 pts',
  },
  {
    total: 5,
    predicted: '2–1',
    actual: '3–0',
    breakdown: 'Goals ✓ (2) + Result ✓ (3) + Exact ✗ (0) = 5 pts',
  },
  {
    total: 3,
    predicted: '2–0',
    actual: '3–1',
    breakdown: 'Goals ✗ (0) + Result ✓ (3) + Exact ✗ (0) = 3 pts',
  },
  {
    total: 2,
    predicted: '2–1',
    actual: '1–2',
    breakdown: 'Goals ✓ (2) + Result ✗ (0) + Exact ✗ (0) = 2 pts',
  },
  {
    total: 0,
    predicted: '1–0',
    actual: '0–2',
    breakdown: 'Goals ✗ (0) + Result ✗ (0) + Exact ✗ (0) = 0 pts',
  },
];

// ── Special predictions ───────────────────────────────────────────────────────

export interface SpecialRow {
  prediction: string;
  pts: number;
}

/**
 * All 6 special prediction types and their point values, sourced directly from
 * apps/api/src/routers/specials.py (SPECIAL_POINTS dict).
 * Total: 20 + 15 + 15 + 10 + 10 + 10 = 80 pts.
 */
export const SPECIAL_ROWS: SpecialRow[] = [
  { prediction: 'Tournament Winner (pre-tournament)', pts: 20 },
  { prediction: 'Golden Boot (top scorer)', pts: 15 },
  { prediction: 'Player of the Tournament (Golden Ball)', pts: 15 },
  { prediction: 'Top Scoring Team', pts: 10 },
  { prediction: 'Young Player of the Tournament', pts: 10 },
  { prediction: 'Golden Glove (best goalkeeper)', pts: 10 },
];

export const SPECIALS_TOTAL = SPECIAL_ROWS.reduce((s, r) => s + r.pts, 0); // 80

// ── Knockout winner picks ─────────────────────────────────────────────────────

export interface KnockoutRoundRow {
  round: string;
  matches: number;
  pts: number;
  max: number;
}

export const KNOCKOUT_WINNER_ROWS: KnockoutRoundRow[] = [
  { round: 'Round of 32', matches: 16, pts: 5, max: 80 },
  { round: 'Round of 16', matches: 8, pts: 10, max: 80 },
  { round: 'Quarter-Finals', matches: 4, pts: 15, max: 60 },
  { round: 'Semi-Finals', matches: 2, pts: 20, max: 40 },
  { round: 'Third Place Play-off', matches: 1, pts: 10, max: 10 },
  { round: 'Final', matches: 1, pts: 25, max: 25 },
];

export const KNOCKOUT_WINNER_TOTAL = KNOCKOUT_WINNER_ROWS.reduce((s, r) => s + r.max, 0); // 295

// ── Grand total breakdown ─────────────────────────────────────────────────────

export interface GrandTotalRow {
  label: string;
  detail: string;
  pts: number;
}

/** 720 + 320 + 295 + 80 = 1,415 */
export const GRAND_TOTAL_ROWS: GrandTotalRow[] = [
  { label: 'Group stage', detail: '72 matches × 10 pts', pts: 720 },
  { label: 'Knockout score predictions', detail: '32 matches × 10 pts', pts: 320 },
  { label: 'Knockout winner picks', detail: 'All 32 matches across 6 rounds', pts: KNOCKOUT_WINNER_TOTAL },
  { label: 'Special predictions', detail: '6 specials', pts: SPECIALS_TOTAL },
];

export const GRAND_TOTAL = GRAND_TOTAL_ROWS.reduce((s, r) => s + r.pts, 0); // 1,415
