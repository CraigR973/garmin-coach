import { describe, it, expect } from 'vitest';
import { dedupedLeaderboard, rankByPeriod } from '@/lib/leaderboard';
import type { LeaderboardEntry } from '@/lib/types';

const SLUG = 'steele-spreadsheet';

function makeEntry(overrides: Partial<LeaderboardEntry> & { player_id: string }): LeaderboardEntry {
  return {
    rank: 4,
    player_name: overrides.player_id,
    total_points: 0,
    match_points: 0,
    knockout_winner_points: 0,
    special_points: 0,
    is_active: true,
    last_match_points: 0,
    today_points: 0,
    round_points: 0,
    ...overrides,
  };
}

describe('dedupedLeaderboard', () => {
  it('deduplicates 9 dup rows for 3 players all at 0pts/rank4 → 3 rows all rank 1', () => {
    const entries: LeaderboardEntry[] = [
      ...Array(3).fill(null).map(() => makeEntry({ player_id: 'p1', total_points: 0, rank: 4 })),
      ...Array(3).fill(null).map(() => makeEntry({ player_id: 'p2', total_points: 0, rank: 4 })),
      ...Array(3).fill(null).map(() => makeEntry({ player_id: 'p3', total_points: 0, rank: 4 })),
    ];
    const result = dedupedLeaderboard(entries, SLUG);
    expect(result).toHaveLength(3);
    expect(result.every((e) => e.rank === 1)).toBe(true);
    expect(new Set(result.map((e) => e.player_id)).size).toBe(3);
  });

  it('handles empty input', () => {
    expect(dedupedLeaderboard([], SLUG)).toEqual([]);
  });

  it('assigns standard competition ranks (1-2-2-4 for tied second)', () => {
    const entries = [
      makeEntry({ player_id: 'p1', total_points: 30, rank: 1 }),
      makeEntry({ player_id: 'p2', total_points: 20, rank: 2 }),
      makeEntry({ player_id: 'p3', total_points: 20, rank: 2 }),
      makeEntry({ player_id: 'p4', total_points: 10, rank: 4 }),
    ];
    const result = dedupedLeaderboard(entries, SLUG);
    expect(result.map((e) => e.rank)).toEqual([1, 2, 2, 4]);
  });

  it('keeps first occurrence when deduplicating', () => {
    const entries = [
      makeEntry({ player_id: 'p1', total_points: 10, player_name: 'First' }),
      makeEntry({ player_id: 'p1', total_points: 10, player_name: 'Duplicate' }),
    ];
    const result = dedupedLeaderboard(entries, SLUG);
    expect(result).toHaveLength(1);
    expect(result[0].player_name).toBe('First');
  });

  it('sorts by total_points descending before ranking', () => {
    const entries = [
      makeEntry({ player_id: 'p2', total_points: 5, rank: 99 }),
      makeEntry({ player_id: 'p1', total_points: 15, rank: 99 }),
      makeEntry({ player_id: 'p3', total_points: 10, rank: 99 }),
    ];
    const result = dedupedLeaderboard(entries, SLUG);
    expect(result[0].player_id).toBe('p1');
    expect(result[0].rank).toBe(1);
    expect(result[1].rank).toBe(2);
    expect(result[2].rank).toBe(3);
  });
});

describe('dedupedLeaderboard merit cascade (U38)', () => {
  // Each case: two players level on points, separated by exactly one cascade
  // axis (the higher value must win even when a *lower* axis favours the other).
  const cases: {
    axis: string;
    a: Partial<LeaderboardEntry>;
    b: Partial<LeaderboardEntry>;
  }[] = [
    {
      axis: 'exact',
      a: { exact_count: 2, correct_result_count: 0 },
      b: { exact_count: 1, correct_result_count: 9 },
    },
    {
      axis: 'result',
      a: { exact_count: 1, correct_result_count: 3, correct_goals_count: 0 },
      b: { exact_count: 1, correct_result_count: 2, correct_goals_count: 9 },
    },
    {
      axis: 'goals',
      a: { exact_count: 1, correct_result_count: 2, correct_goals_count: 5, specials_correct_count: 0 },
      b: { exact_count: 1, correct_result_count: 2, correct_goals_count: 3, specials_correct_count: 9 },
    },
    {
      axis: 'specials',
      a: { exact_count: 1, correct_result_count: 1, correct_goals_count: 1, specials_correct_count: 2, ko_winner_correct_count: 0 },
      b: { exact_count: 1, correct_result_count: 1, correct_goals_count: 1, specials_correct_count: 1, ko_winner_correct_count: 9 },
    },
    {
      axis: 'ko-winner',
      a: { exact_count: 1, correct_result_count: 1, correct_goals_count: 1, specials_correct_count: 1, ko_winner_correct_count: 2 },
      b: { exact_count: 1, correct_result_count: 1, correct_goals_count: 1, specials_correct_count: 1, ko_winner_correct_count: 1 },
    },
  ];

  it.each(cases)('separates equal points by $axis', ({ a, b }) => {
    // Feed b first so a only leads if the cascade (not input order) decides it.
    const entries = [
      makeEntry({ player_id: 'b', total_points: 10, ...b }),
      makeEntry({ player_id: 'a', total_points: 10, ...a }),
    ];
    const result = dedupedLeaderboard(entries, SLUG);
    expect(result.map((e) => e.player_id)).toEqual(['a', 'b']);
    expect(result.map((e) => e.rank)).toEqual([1, 2]);
  });

  it('shares a rank only on a genuine all-axis tie', () => {
    const axes = {
      exact_count: 1,
      correct_result_count: 1,
      correct_goals_count: 1,
      specials_correct_count: 1,
      ko_winner_correct_count: 1,
    };
    const entries = [
      makeEntry({ player_id: 'a', total_points: 10, ...axes }),
      makeEntry({ player_id: 'b', total_points: 10, ...axes }),
    ];
    const result = dedupedLeaderboard(entries, SLUG);
    expect(result.map((e) => e.rank)).toEqual([1, 1]);
  });

  it('points still dominate every tiebreak axis', () => {
    const entries = [
      makeEntry({ player_id: 'low', total_points: 9, exact_count: 99 }),
      makeEntry({ player_id: 'high', total_points: 10, exact_count: 0 }),
    ];
    const result = dedupedLeaderboard(entries, SLUG);
    expect(result[0].player_id).toBe('high');
    expect(result.map((e) => e.rank)).toEqual([1, 2]);
  });
});

describe('rankByPeriod', () => {
  // Same three players; the leader differs per period.
  const entries = [
    makeEntry({ player_id: 'p1', total_points: 30, today_points: 0, round_points: 5 }),
    makeEntry({ player_id: 'p2', total_points: 20, today_points: 8, round_points: 5 }),
    makeEntry({ player_id: 'p3', total_points: 10, today_points: 3, round_points: 12 }),
  ];

  it('re-sorts and re-ranks by today points', () => {
    const result = rankByPeriod(entries, 'today');
    expect(result.map((e) => e.player_id)).toEqual(['p2', 'p3', 'p1']);
    expect(result.map((e) => e.rank)).toEqual([1, 2, 3]);
  });

  it('re-sorts and re-ranks by round points (ties share a rank)', () => {
    const result = rankByPeriod(entries, 'round');
    // p3 (12) leads; p1 & p2 tie at 5 → both rank 2, competition style.
    expect(result[0].player_id).toBe('p3');
    expect(result.map((e) => e.rank)).toEqual([1, 2, 2]);
  });

  it('reproduces the total ordering for the total period (idempotent)', () => {
    const result = rankByPeriod(entries, 'total');
    expect(result.map((e) => e.player_id)).toEqual(['p1', 'p2', 'p3']);
    expect(result.map((e) => e.rank)).toEqual([1, 2, 3]);
  });

  it('does not mutate the input array', () => {
    const before = entries.map((e) => e.player_id);
    rankByPeriod(entries, 'today');
    expect(entries.map((e) => e.player_id)).toEqual(before);
  });
});
