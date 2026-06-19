import type { LeaderboardEntry, LeagueDetail } from './types';

const num = (x: number | undefined): number => x ?? 0;

/**
 * Merit-cascade comparator (U38). Orders players level on points by, in turn:
 * exact scores → correct results → correct goals → specials correct →
 * knockout-winner picks correct. Returns <0 when `a` outranks `b`, >0 when `b`
 * outranks `a`, and exactly 0 only on a genuine all-axis tie — the case the
 * leaderboard marks as a shared position for admin settlement.
 *
 * Counts are coalesced to 0 so a stale cached payload that predates U38 still
 * sorts deterministically by points.
 */
export function cascadeCompare(a: LeaderboardEntry, b: LeaderboardEntry): number {
  return (
    b.total_points - a.total_points ||
    num(b.exact_count) - num(a.exact_count) ||
    num(b.correct_result_count) - num(a.correct_result_count) ||
    num(b.correct_goals_count) - num(a.correct_goals_count) ||
    num(b.specials_correct_count) - num(a.specials_correct_count) ||
    num(b.ko_winner_correct_count) - num(a.ko_winner_correct_count)
  );
}

/**
 * Deduplicate leaderboard entries by (player_id, leagueSlug) (keep first
 * occurrence) and recompute ranks locally using the U38 merit cascade with
 * standard competition ranking (1224 style). Two players share a rank only when
 * they tie on *every* cascade axis; this mirrors the backend snapshot rank, so
 * the table never disagrees with history or rank-change pushes. Run defensively
 * even though the backend already returns cascade-ordered ranks.
 *
 * Each response is already scoped to one league, so leagueSlug is constant for
 * a given call; threading it explicitly documents intent and guards a future
 * stacked-leagues view from collapsing the same player across leagues.
 */
export function dedupedLeaderboard(
  entries: LeaderboardEntry[],
  leagueSlug: string,
): LeaderboardEntry[] {
  const seen = new Set<string>();
  const unique: LeaderboardEntry[] = [];
  for (const e of entries) {
    const key = `${e.player_id}:${leagueSlug}`;
    if (!seen.has(key)) {
      seen.add(key);
      unique.push(e);
    }
  }

  // Sort by the full merit cascade so ranking is deterministic regardless of
  // the order the backend returned.
  unique.sort(cascadeCompare);

  // Standard competition ranking: a rank is shared only on a genuine all-axis
  // tie (cascadeCompare === 0); the next distinct entry skips ahead.
  let rank = 1;
  return unique.map((e, i) => {
    if (i > 0 && cascadeCompare(unique[i - 1], e) !== 0) {
      rank = i + 1;
    }
    return { ...e, rank };
  });
}

export type LeaderboardPeriod = 'today' | 'round' | 'total';

const PERIOD_FIELD: Record<Exclude<LeaderboardPeriod, 'total'>, keyof LeaderboardEntry> = {
  today: 'today_points',
  round: 'round_points',
};

/**
 * Re-sort (already-deduped) entries by the selected period and reassign standard
 * competition ranks for that period (U22.3). The `total` period reproduces the
 * default standings using the full U38 merit cascade, so it is idempotent with
 * `dedupedLeaderboard`. The temporal periods (`today` / `round`) are informational
 * snapshots, so they sort by that period's points and break ties by name for a
 * stable order. Returns new objects; never mutates the input.
 */
export function rankByPeriod(
  entries: LeaderboardEntry[],
  period: LeaderboardPeriod,
): LeaderboardEntry[] {
  if (period === 'total') {
    const sorted = [...entries].sort(cascadeCompare);
    let rank = 1;
    return sorted.map((e, i) => {
      if (i > 0 && cascadeCompare(sorted[i - 1], e) !== 0) {
        rank = i + 1;
      }
      return { ...e, rank };
    });
  }

  const field = PERIOD_FIELD[period];
  const sorted = [...entries].sort(
    (a, b) => (b[field] as number) - (a[field] as number) || a.player_name.localeCompare(b.player_name),
  );
  let rank = 1;
  return sorted.map((e, i) => {
    if (i > 0 && (e[field] as number) < (sorted[i - 1][field] as number)) {
      rank = i + 1;
    }
    return { ...e, rank };
  });
}

/**
 * U46.1: leagues should feel populated before the first result lands. The
 * backend may legitimately return no leaderboard snapshots yet, so fold in the
 * already-loaded league roster as default-zero entries and let the standard
 * ranking pipeline place everyone deterministically.
 */
export function withLeagueRoster(
  entries: LeaderboardEntry[],
  leagueSlug: string,
  leagueMembers: LeagueDetail['members'],
): LeaderboardEntry[] {
  if (!leagueMembers?.length) return dedupedLeaderboard(entries, leagueSlug);

  const knownPlayerIds = new Set(entries.map((entry) => entry.player_id));
  const missingMembers = leagueMembers
    .filter((member) => !knownPlayerIds.has(member.id))
    .map((member, index) => ({
      rank: entries.length + index + 1,
      player_id: member.id,
      player_name: member.display_name,
      total_points: 0,
      match_points: 0,
      knockout_winner_points: 0,
      special_points: 0,
      is_active: true,
      last_match_points: 0,
      today_points: 0,
      round_points: 0,
      avatar_url: member.avatar_url ?? null,
    }));

  return dedupedLeaderboard([...entries, ...missingMembers], leagueSlug);
}
