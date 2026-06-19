export type Stage = 'group' | 'r32' | 'r16' | 'qf' | 'sf' | 'third_place' | 'final';

export type MatchStatus = 'scheduled' | 'locked' | 'live' | 'completed' | 'postponed' | 'cancelled';

export type Role = 'admin' | 'player';

export interface PerLeagueRank {
  slug: string;
  name: string;
  rank: number | null;
  member_count: number;
}

export interface CrossLeagueSummary {
  avg_rank: number | null;
  total_points: number;
  leagues_count: number;
  per_league: PerLeagueRank[];
}
