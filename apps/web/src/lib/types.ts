export interface TeamRef {
  id: string;
  name: string;
  code: string;
  flag_emoji: string;
}

export interface MatchResponse {
  id: string;
  match_number: number;
  stage: string;
  group_id: string | null;
  group_name: string | null;
  home_team: TeamRef | null;
  away_team: TeamRef | null;
  home_team_placeholder: string | null;
  away_team_placeholder: string | null;
  kickoff_utc: string;
  venue: string | null;
  status: 'scheduled' | 'locked' | 'live' | 'completed' | 'postponed' | 'cancelled';
  actual_home_score: number | null;
  actual_away_score: number | null;
  extra_time: boolean;
  penalties: boolean;
  postponed_reason: string | null;
  // U27.B1 — live elapsed minute. Currently always null (the result-fetcher's
  // upstream feed carries no per-match minute); the live hub omits the minute
  // when null. Optional so older cached payloads stay valid.
  elapsed_minutes?: number | null;
}

export interface TeamStanding {
  position: number;
  team_id: string;
  team_name: string;
  team_code: string;
  flag_emoji: string;
  played: number;
  won: number;
  drawn: number;
  lost: number;
  gf: number;
  ga: number;
  gd: number;
  points: number;
}

export interface GroupResponse {
  id: string;
  name: string;
  standings: TeamStanding[];
}

export interface PointsBreakdown {
  goals: number;
  result: number;
  exact: number;
  total: number;
  no_prediction: boolean;
}

export interface PredictionResponse {
  id: string;
  player_id: string;
  match_id: string;
  predicted_home: number | null;
  predicted_away: number | null;
  submitted_at: string | null;
  update_count: number;
  points_awarded: number | null;
  points_breakdown: PointsBreakdown | null;
  updated_at: string;
}

export interface MatchPredictionItem {
  player_id: string;
  player_name: string;
  predicted_home: number | null;
  predicted_away: number | null;
  points_awarded: number | null;
  points_breakdown: PointsBreakdown | null;
}

export interface MatchPredictionsResponse {
  match_id: string;
  predictions: MatchPredictionItem[];
}

export interface LeaderboardEntry {
  rank: number;
  player_id: string;
  player_name: string;
  total_points: number;
  match_points: number;
  knockout_winner_points: number;
  special_points: number;
  is_active: boolean;
  // U38 tiebreak counts — the merit cascade that separates players level on
  // points (exact → result → goals → specials → KO-winner). Optional so a stale
  // pre-U38 cached payload still type-checks; the cascade coalesces missing to 0.
  exact_count?: number;
  correct_result_count?: number;
  correct_goals_count?: number;
  specials_correct_count?: number;
  ko_winner_correct_count?: number;
  // True when this player shares a rank with another — a genuine all-axis tie
  // flagged for admin settlement (U38.4).
  tied?: boolean;
  // Temporal metrics (U22.2), derived server-side. Match-scoped points only.
  last_match_points: number;
  today_points: number;
  round_points: number;
  // Avatar (U23.1) — null when player hasn't uploaded a photo
  avatar_url?: string | null;
}

export interface SnapshotPoint {
  snapshot_at: string;
  total_points: number;
  rank: number;
}

export interface HistoryEntry {
  player_id: string;
  player_name: string;
  snapshots: SnapshotPoint[];
}

export interface RoundEntry {
  rank: number;
  player_id: string;
  player_name: string;
  avatar_url?: string | null;
  points: number;
  // U38 tiebreak counts, scoped to this stage. Specials are tournament-long, so
  // the round cascade stops at KO-winner picks.
  exact_count?: number;
  correct_result_count?: number;
  correct_goals_count?: number;
  ko_winner_correct_count?: number;
  tied?: boolean;
}

export interface KnockoutPredictionResponse {
  id: string;
  player_id: string;
  match_id: string;
  predicted_winner_id: string | null;
  submitted_at: string | null;
  update_count: number;
  points_awarded: number | null;
  updated_at: string;
}

export type SpecialType =
  | 'tournament_winner'
  | 'golden_boot'
  | 'top_scoring_team'
  | 'player_of_tournament'
  | 'young_player_of_tournament'
  | 'golden_glove';

export interface SpecialPredictionItem {
  id: string;
  prediction_type: SpecialType;
  predicted_team_id: string | null;
  predicted_player_name: string | null;
  predicted_player_id: string | null;
  submitted_at: string | null;
  points_awarded: number | null;
}

export interface SquadPlayerResult {
  id: string;
  full_name: string;
  known_as: string;
  position: 'GK' | 'DEF' | 'MID' | 'FWD';
  shirt_number: number | null;
  team_code: string;
  team_name: string;
  flag_emoji: string;
}

export interface MySpecialsResponse {
  is_locked: boolean;
  lock_at: string | null;
  predictions: SpecialPredictionItem[];
}

export interface PlayerSpecialsItem {
  player_id: string;
  player_name: string;
  predictions: SpecialPredictionItem[];
}

export interface GlobalSpecialsPick {
  answer: string;    // "🇧🇷 Brazil" or player name
  count: number;
  team_id: string | null;
}

export interface GlobalSpecialsResponse {
  total_players: number;
  by_type: Record<string, GlobalSpecialsPick[]>;
}

export interface PlayerStats {
  player_id: string;
  player_name: string;
  total_predictions_settled: number;
  accuracy_pct: number;
  exact_rate_pct: number;
  avg_pts_per_prediction: number;
  total_points: number;
  best_round: string | null;
  best_round_points: number | null;
  worst_round: string | null;
  worst_round_points: number | null;
  current_streak: number;
  avg_prediction_timing_mins: number | null;
  // U38 — the Match / Knockout / Special points decomposition (moved here from
  // the leaderboard) plus the deeper tiebreak counts shown on the profile.
  match_points?: number;
  knockout_winner_points?: number;
  special_points?: number;
  exact_count?: number;
  correct_result_count?: number;
  correct_goals_count?: number;
  specials_correct_count?: number;
  ko_winner_correct_count?: number;
  // Avatar (U23.1) — null when player hasn't uploaded a photo
  avatar_url?: string | null;
}

export interface PlayerListItem {
  id: string;
  display_name: string;
  role: string;
  timezone: string;
  is_deleted: boolean;
  created_at: string;
}

export interface H2HPlayerRef {
  id: string;
  name: string;
}

export interface H2HSummary {
  player_a_wins: number;
  player_b_wins: number;
  draws: number;
}

export interface H2HMatchEntry {
  match_id: string;
  stage: string;
  kickoff_utc: string;
  home_team_name: string | null;
  away_team_name: string | null;
  home_team_flag: string | null;
  away_team_flag: string | null;
  actual_home: number | null;
  actual_away: number | null;
  player_a_predicted_home: number | null;
  player_a_predicted_away: number | null;
  player_a_points: number;
  player_b_predicted_home: number | null;
  player_b_predicted_away: number | null;
  player_b_points: number;
  winner: 'a' | 'b' | 'draw';
}

export interface H2HResponse {
  player_a: H2HPlayerRef;
  player_b: H2HPlayerRef;
  summary: H2HSummary;
  matches: H2HMatchEntry[];
}

export interface LeagueSummary {
  slug: string;
  name: string;
  description: string | null;
  privacy: 'public_open' | 'public_request' | 'private';
  member_count: number;
  max_members: number | null;
  created_at: string;
}

/** Shape returned by GET /api/v1/leagues/{slug} — includes member list with roles. */
export interface LeagueDetail extends LeagueSummary {
  id: string;
  created_by: string;
  join_code: string | null;
  members: Array<{ id: string; display_name: string; role: 'player' | 'admin'; joined_at: string; avatar_url?: string | null }> | null;
}

export interface LeagueMember {
  player_id: string;
  display_name: string;
  league_display_name: string | null;
  role: 'player' | 'admin';
  joined_at: string;
  // Avatar (U23.1) — null when player hasn't uploaded a photo
  avatar_url?: string | null;
}

export interface JoinRequest {
  id: string;
  player_id: string;
  display_name: string;
  requested_at: string;
  status: 'pending' | 'approved' | 'rejected';
  note: string | null;
}

export interface LeagueInvite {
  id: string;
  token: string;
  created_by_display_name: string;
  created_at: string;
  expires_at: string | null;
  used_at: string | null;
  invitee_email: string | null;
}

export interface CrossLeagueSummary {
  avg_rank: number | null;
  total_points: number;
  leagues_count: number;
  per_league: Array<{
    slug: string;
    name: string;
    rank: number | null;
    member_count: number;
    rank_delta: number | null;
    triggered_by_match_id: string | null;
  }>;
}

export interface HomeNextMatch {
  id: string;
  kickoff_utc: string;
  home_label: string;
  away_label: string;
  predicted: boolean;
}

export interface HomeTodo {
  specials_submitted: boolean;
  specials_count: number;
  specials_lock_at: string | null;
  upcoming_unpredicted: number;
  next_match: HomeNextMatch | null;
  opening_match_predicted: boolean;
}

export interface HomeRollupMatch {
  match_id: string;
  kickoff_utc: string; // U27.B2 — drives the date/time shown per rollup row
  home_label: string;
  away_label: string;
  home_flag: string | null;
  away_flag: string | null;
  actual_home: number | null;
  actual_away: number | null;
  predicted_home: number | null;
  predicted_away: number | null;
  points_breakdown: PointsBreakdown | null;
}

export interface HomeRollup {
  matchday: string;
  points_gained: number;
  match_count: number;
  matches: HomeRollupMatch[];
}

export interface HomeResponse {
  todo: HomeTodo;
  rollup: HomeRollup | null;
}

export interface RecentPrediction {
  match_id: string;
  stage: string;
  kickoff_utc: string;
  home_team_name: string | null;
  away_team_name: string | null;
  home_team_flag: string | null;
  away_team_flag: string | null;
  actual_home: number | null;
  actual_away: number | null;
  predicted_home: number | null;
  predicted_away: number | null;
  points_awarded: number | null;
  points_breakdown: PointsBreakdown | null;
}

// U24 — reveal-gated player-profile prediction board. Every item the backend
// returns has already passed the shared reveal gate (group/knockout: that
// match has kicked off; specials: the tournament has started), so these are
// safe to render unconditionally.
export interface GroupProfilePrediction {
  match_id: string;
  stage: string;
  kickoff_utc: string;
  home_team_name: string | null;
  away_team_name: string | null;
  home_team_flag: string | null;
  away_team_flag: string | null;
  actual_home: number | null;
  actual_away: number | null;
  predicted_home: number | null;
  predicted_away: number | null;
  points_awarded: number | null;
  points_breakdown: PointsBreakdown | null;
}

export interface KnockoutProfilePrediction {
  match_id: string;
  stage: string;
  kickoff_utc: string;
  home_team_name: string | null;
  away_team_name: string | null;
  home_team_flag: string | null;
  away_team_flag: string | null;
  predicted_winner_id: string | null;
  predicted_winner_name: string | null;
  points_awarded: number | null;
}

export interface SpecialProfilePrediction {
  prediction_type: SpecialType;
  predicted_team_id: string | null;
  predicted_team_name: string | null;
  predicted_player_name: string | null;
  points_awarded: number | null;
}

export interface ProfilePredictions {
  // false ⇒ specials are still hidden (tournament not started); the list is [].
  specials_revealed: boolean;
  group: GroupProfilePrediction[];
  knockout: KnockoutProfilePrediction[];
  specials: SpecialProfilePrediction[];
}
