import { useCallback, useRef, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { formatInTimeZone } from 'date-fns-tz';
import { toast } from 'sonner';
import { Camera, X } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogClose,
} from '../components/ui/dialog';
import { apiFetch } from '../lib/api';
import { useAuth } from '../contexts/AuthContext';
import { formatSubmitTime } from '../lib/format';
import { Skeleton } from '../components/ui/skeleton';
import { EmptyState } from '../components/EmptyState';
import { PageHeader } from '../components/PageHeader';
import { PointsBreakdownRow } from '../components/PointsBreakdownRow';
import { PointsBreakdownPopover } from '../components/PointsBreakdownPopover';
import { Avatar } from '../components/ui/avatar';
import {
  ALLOWED_AVATAR_TYPES,
  MAX_AVATAR_BYTES,
  resizeAvatar,
  uploadAvatarImage,
} from '../lib/image';
import type {
  HomeResponse,
  PlayerStats,
  ProfilePredictions,
  RecentPrediction,
  SpecialType,
} from '../lib/types';

const STAGE_LABEL: Record<string, string> = {
  group: 'Group Stage',
  r32: 'Round of 32',
  r16: 'Round of 16',
  qf: 'Quarter-Finals',
  sf: 'Semi-Finals',
  third_place: 'Third Place',
  final: 'Final',
};

const SPECIAL_LABEL: Record<SpecialType, string> = {
  tournament_winner: 'Tournament Winner',
  golden_boot: 'Golden Boot',
  top_scoring_team: 'Top Scoring Team',
  player_of_tournament: 'Player of the Tournament',
  young_player_of_tournament: 'Young Player of the Tournament',
  golden_glove: 'Golden Glove',
};

function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-lg border border-border bg-surface p-4 flex flex-col gap-2">
      <span className="text-[10px] font-mono text-text-muted uppercase tracking-[0.25em]">
        {label}
      </span>
      <span className="font-mono text-2xl font-semibold text-primary tabular-nums leading-none">
        {value}
      </span>
    </div>
  );
}

// U38: the Match / Knockout / Special points decomposition (moved here from the
// leaderboard) plus the deeper merit-cascade tiebreak counts.
function PointsBreakdownSection({ stats }: { stats: PlayerStats }) {
  const decomposition: [string, number][] = [
    ['Match', stats.match_points ?? 0],
    ['Knockout', stats.knockout_winner_points ?? 0],
    ['Special', stats.special_points ?? 0],
  ];
  const tiebreakers: [string, number][] = [
    ['Exact', stats.exact_count ?? 0],
    ['Result', stats.correct_result_count ?? 0],
    ['Goals', stats.correct_goals_count ?? 0],
    ['Specials', stats.specials_correct_count ?? 0],
    ['KO', stats.ko_winner_correct_count ?? 0],
  ];
  return (
    <div>
      <SectionTitle>How I Earned My Points</SectionTitle>
      <div className="rounded-lg border border-border bg-surface p-4 space-y-4">
        <p className="text-sm font-sans leading-relaxed text-text-secondary">
          Full points-source breakdown for this player. Leaderboards use the precision counts below
          to separate players who finish level on points.
        </p>
        <div className="grid grid-cols-3 gap-3 text-center">
          {decomposition.map(([label, value]) => (
            <div key={label} className="flex flex-col gap-1.5">
              <span className="text-[10px] font-mono text-text-muted uppercase tracking-[0.2em]">
                {label}
              </span>
              <span className="font-mono text-xl font-semibold text-primary tabular-nums leading-none">
                {value}
              </span>
            </div>
          ))}
        </div>
        <div className="border-t border-border/60 pt-3">
          <p className="text-[10px] font-mono text-text-muted uppercase tracking-[0.25em] mb-1.5">
            Precision tiebreakers
          </p>
          <p className="mb-3 text-xs font-sans leading-relaxed text-text-muted">
            Order used when points are tied: exact, result, goals, specials, then knockout-winner picks.
          </p>
          <div className="grid grid-cols-5 gap-2 text-center">
            {tiebreakers.map(([label, value]) => (
              <div key={label} className="flex flex-col gap-1">
                <span className="text-[9px] font-mono text-text-muted uppercase tracking-[0.15em]">
                  {label}
                </span>
                <span className="font-mono text-base font-semibold text-text-secondary tabular-nums leading-none">
                  {value}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function outcomeClass(pts: number | null, isUnfinished: boolean): string {
  if (isUnfinished || pts === null) return 'text-text-muted';
  if (pts === 0) return 'text-red-400';
  return 'text-green-400';
}

function isMatchUnfinished(p: RecentPrediction): boolean {
  return p.actual_home === null || p.actual_away === null;
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-base font-semibold text-text-primary font-sans tracking-tight mb-3">
      {children}
    </h2>
  );
}

function LatestMatchdaySection({
  rollup,
  timezone,
}: {
  rollup: NonNullable<HomeResponse['rollup']>;
  timezone: string;
}) {
  return (
    <div>
      <SectionTitle>Latest Matchday</SectionTitle>
      <div className="rounded-lg border border-border bg-surface p-4">
        <div className="flex flex-wrap items-end justify-between gap-3 border-b border-border/60 pb-3">
          <div>
            <p className="text-[10px] font-mono uppercase tracking-[0.2em] text-text-muted">
              Matchday recap
            </p>
            <p className="mt-1 text-sm text-text-muted">
              {formatInTimeZone(new Date(rollup.matchday + 'T00:00:00Z'), timezone, 'EEE d MMM')}
            </p>
          </div>
          <p className="font-mono text-2xl font-semibold tabular-nums text-primary">
            +{rollup.points_gained} pts
          </p>
        </div>

        <div className="mt-3 space-y-3">
          {rollup.matches.map((match) => (
            <Link
              key={match.match_id}
              to={`/matches/${match.match_id}`}
              className="block rounded-lg border border-border/50 bg-surface-elevated/40 px-3 py-3 transition-colors hover:bg-surface-elevated focus-visible:outline-none focus-visible:shadow-glow"
            >
              <div className="mb-1.5 flex items-baseline justify-between gap-2">
                <p className="min-w-0 truncate text-sm font-medium text-text-primary">
                  {match.home_label} <span className="font-normal text-text-muted">vs</span> {match.away_label}
                </p>
                <span className="shrink-0 font-mono text-[10px] tabular-nums text-text-muted">
                  {formatInTimeZone(new Date(match.kickoff_utc), timezone, 'd MMM, HH:mm')}
                </span>
              </div>
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <span className="font-mono text-base font-semibold tabular-nums text-text-primary">
                  {match.actual_home ?? '?'}–{match.actual_away ?? '?'}
                </span>
                {match.predicted_home !== null && match.predicted_away !== null && (
                  <span className="rounded-full border border-border bg-surface px-2 py-0.5 font-mono text-[10px] font-medium tabular-nums text-text-muted">
                    you {match.predicted_home}–{match.predicted_away}
                  </span>
                )}
              </div>
              {match.points_breakdown && <PointsBreakdownRow breakdown={match.points_breakdown} />}
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
}

// U24: locked group predictions (kicked-off matches). Mirrors the post-lock
// comparison styling used elsewhere — result, the player's pick, and points.
function GroupPredictionsSection({ data }: { data: ProfilePredictions['group'] }) {
  if (data.length === 0) return null;
  return (
    <div>
      <SectionTitle>Group Predictions</SectionTitle>
      <div className="rounded-lg border border-border bg-surface overflow-hidden">
        <table className="w-full text-sm font-sans">
          <thead>
            <tr className="border-b border-border text-text-muted text-xs">
              <th className="py-2 pl-4 text-left">Match</th>
              <th className="py-2 text-center">Result</th>
              <th className="py-2 text-center">Predicted</th>
              <th className="py-2 pr-4 text-center">Pts</th>
            </tr>
          </thead>
          <tbody>
            {data.map((p) => {
              const unfinished = p.actual_home === null || p.actual_away === null;
              return (
                <tr key={p.match_id} className="border-b border-border/50 last:border-0">
                  <td className="py-2 pl-4">
                    <span className="text-text-primary">
                      {p.home_team_flag} {p.home_team_name ?? '?'} vs {p.away_team_flag}{' '}
                      {p.away_team_name ?? '?'}
                    </span>
                    <span className="block text-xs text-text-muted">
                      {STAGE_LABEL[p.stage] ?? p.stage}
                    </span>
                  </td>
                  <td className="py-2 text-center text-text-secondary font-mono">
                    {p.actual_home ?? '?'}–{p.actual_away ?? '?'}
                  </td>
                  <td className="py-2 text-center text-text-secondary font-mono">
                    {p.predicted_home ?? '?'}–{p.predicted_away ?? '?'}
                  </td>
                  <td
                    className={`py-2 pr-4 text-center font-bold ${outcomeClass(p.points_awarded, unfinished)}`}
                  >
                    {p.points_awarded != null ? (
                      <PointsBreakdownPopover breakdown={p.points_breakdown}>
                        <span>{p.points_awarded}</span>
                      </PointsBreakdownPopover>
                    ) : (
                      '—'
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// U24: locked knockout predictions (per-match kickoff lock from U22.1) — the
// tie and who this player backed to advance.
function KnockoutPredictionsSection({ data }: { data: ProfilePredictions['knockout'] }) {
  if (data.length === 0) return null;
  return (
    <div>
      <SectionTitle>Knockout Predictions</SectionTitle>
      <div className="rounded-lg border border-border bg-surface overflow-hidden">
        <table className="w-full text-sm font-sans">
          <thead>
            <tr className="border-b border-border text-text-muted text-xs">
              <th className="py-2 pl-4 text-left">Tie</th>
              <th className="py-2 text-center">Pick</th>
              <th className="py-2 pr-4 text-center">Pts</th>
            </tr>
          </thead>
          <tbody>
            {data.map((p) => (
              <tr key={p.match_id} className="border-b border-border/50 last:border-0">
                <td className="py-2 pl-4">
                  <span className="text-text-primary">
                    {p.home_team_flag} {p.home_team_name ?? '?'} vs {p.away_team_flag}{' '}
                    {p.away_team_name ?? '?'}
                  </span>
                  <span className="block text-xs text-text-muted">
                    {STAGE_LABEL[p.stage] ?? p.stage}
                  </span>
                </td>
                <td className="py-2 text-center text-text-primary font-medium">
                  {p.predicted_winner_name ?? '—'}
                </td>
                <td
                  className={`py-2 pr-4 text-center font-bold ${outcomeClass(p.points_awarded, p.points_awarded === null)}`}
                >
                  {p.points_awarded ?? '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// U24: special predictions, revealed as a set once the tournament starts.
function SpecialPredictionsSection({
  revealed,
  data,
}: {
  revealed: boolean;
  data: ProfilePredictions['specials'];
}) {
  // Hidden until the tournament starts — show nothing rather than an empty
  // shell that could imply this player made no picks.
  if (!revealed || data.length === 0) return null;
  return (
    <div>
      <SectionTitle>Special Predictions</SectionTitle>
      <div className="rounded-lg border border-border bg-surface overflow-hidden">
        <table className="w-full text-sm font-sans">
          <thead>
            <tr className="border-b border-border text-text-muted text-xs">
              <th className="py-2 pl-4 text-left">Award</th>
              <th className="py-2 text-center">Pick</th>
              <th className="py-2 pr-4 text-center">Pts</th>
            </tr>
          </thead>
          <tbody>
            {data.map((p) => (
              <tr key={p.prediction_type} className="border-b border-border/50 last:border-0">
                <td className="py-2 pl-4 text-text-muted">
                  {SPECIAL_LABEL[p.prediction_type] ?? p.prediction_type}
                </td>
                <td className="py-2 text-center text-text-primary font-medium">
                  {p.predicted_team_name ?? p.predicted_player_name ?? '—'}
                </td>
                <td
                  className={`py-2 pr-4 text-center font-bold ${outcomeClass(p.points_awarded, p.points_awarded === null)}`}
                >
                  {p.points_awarded ?? '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function PlayerProfilePage() {
  const { id } = useParams<{ id: string }>();
  const { player: currentUser, updatePlayer } = useAuth();
  const isSelf = currentUser?.id === id;
  const timezone = currentUser?.timezone ?? 'UTC';
  const queryClient = useQueryClient();

  // Avatar upload state — only active when isSelf
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [avatarLightboxOpen, setAvatarLightboxOpen] = useState(false);

  const handleAvatarChange = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (fileRef.current) fileRef.current.value = '';
      if (!file) return;
      if (!ALLOWED_AVATAR_TYPES.includes(file.type)) {
        toast.error('Only JPEG, PNG, WebP, or GIF files are supported');
        return;
      }
      if (file.size > MAX_AVATAR_BYTES * 2) {
        toast.error('File too large. Please choose an image under 10 MB.');
        return;
      }
      setUploading(true);
      try {
        const blob = await resizeAvatar(file);
        if (blob.size > MAX_AVATAR_BYTES) {
          toast.error('Resized image is too large. Please choose a smaller photo.');
          return;
        }
        const newUrl = await uploadAvatarImage(blob);
        updatePlayer({ avatarUrl: newUrl });
        queryClient.invalidateQueries({ queryKey: ['stats', id] });
        queryClient.invalidateQueries({ queryKey: ['leaderboard'] });
        queryClient.invalidateQueries({ queryKey: ['league-members'] });
        toast.success('Avatar updated');
      } catch (err) {
        toast.error(err instanceof Error ? err.message : 'Upload failed');
      } finally {
        setUploading(false);
      }
    },
    [updatePlayer, queryClient, id],
  );

  const { data: stats, isLoading, error } = useQuery<PlayerStats>({
    queryKey: ['stats', id],
    queryFn: () => apiFetch<PlayerStats>(`/api/v1/stats/${id}`),
    enabled: !!id,
  });

  const { data: myStats } = useQuery<PlayerStats>({
    queryKey: ['stats', 'me'],
    queryFn: () => apiFetch<PlayerStats>('/api/v1/stats/me'),
    enabled: !isSelf,
  });

  const { data: recentPreds = [] } = useQuery<RecentPrediction[]>({
    queryKey: ['player-recent-preds', id],
    queryFn: () => apiFetch<RecentPrediction[]>(`/api/v1/players/${id}/predictions/recent`),
    enabled: !!id,
  });

  const { data: home } = useQuery<HomeResponse>({
    queryKey: ['me-home'],
    queryFn: () => apiFetch<HomeResponse>('/api/v1/me/home'),
    enabled: isSelf,
    staleTime: 30_000,
  });

  // U24: full reveal-gated board (group + knockout + specials). The backend
  // only ever returns predictions that have already locked, so every row here
  // is safe to render — the privacy gate lives server-side, not in this view.
  const { data: revealed } = useQuery<ProfilePredictions>({
    queryKey: ['player-profile-preds', id],
    queryFn: () => apiFetch<ProfilePredictions>(`/api/v1/players/${id}/profile-predictions`),
    enabled: !!id,
  });

  if (isLoading) {
    return (
      <div className="space-y-8">
        <div className="flex items-center justify-between">
          <div className="space-y-2">
            <Skeleton className="h-8 w-48" />
            <Skeleton className="h-4 w-32" />
          </div>
        </div>
        <div>
          <Skeleton className="h-5 w-16 mb-3" />
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-[88px]" />
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (error || !stats) {
    return (
      <EmptyState
        title="Player not found"
        description="This profile either doesn't exist or couldn't be loaded."
        action={
          <Link to="/leagues" className="text-primary text-sm font-sans hover:underline">
            ← Back to leaderboard
          </Link>
        }
      />
    );
  }

  const h2hTarget = isSelf ? null : myStats ?? null;

  // U3.5: streak — only show 🔥 when streak >= 2
  const streakDisplay =
    stats.current_streak >= 2
      ? `${stats.current_streak}🔥`
      : stats.current_streak === 0
        ? '—'
        : `${stats.current_streak}`;

  // U3.7: collapse best/worst when zero settled rounds and both are 0
  const hasRoundVariance =
    stats.total_predictions_settled > 0 &&
    (stats.best_round !== null || stats.worst_round !== null);
  const showBestWorstPlaceholder =
    !hasRoundVariance &&
    stats.total_predictions_settled === 0 &&
    (stats.best_round !== null || stats.worst_round !== null
      ? false
      : true);

  return (
    <div className="space-y-7">
      {/* Avatar lightbox — shown for both self and others when avatar is clicked */}
      <Dialog open={avatarLightboxOpen} onOpenChange={setAvatarLightboxOpen}>
        <DialogContent className="flex flex-col items-center gap-4 max-w-xs p-6">
          <DialogClose className="absolute right-3 top-3 rounded-sm opacity-70 hover:opacity-100 focus-visible:outline-none focus-visible:shadow-glow">
            <X className="h-4 w-4" aria-hidden />
            <span className="sr-only">Close</span>
          </DialogClose>
          {stats.avatar_url ? (
            <img
              src={stats.avatar_url}
              alt={stats.player_name}
              className="h-40 w-40 rounded-full object-cover"
            />
          ) : (
            <Avatar name={stats.player_name} size="lg" />
          )}
          <p className="text-sm font-semibold font-sans text-text-primary">{stats.player_name}</p>
          {isSelf && (
            <button
              type="button"
              disabled={uploading}
              onClick={() => { setAvatarLightboxOpen(false); fileRef.current?.click(); }}
              className="text-sm font-sans text-primary hover:underline disabled:opacity-50"
            >
              {uploading ? 'Uploading…' : 'Change photo'}
            </button>
          )}
        </DialogContent>
      </Dialog>

      <div className="flex items-center gap-4">
        {isSelf ? (
          /* Own profile — click opens lightbox; file input hidden for upload */
          <div className="relative shrink-0">
            <input
              ref={fileRef}
              type="file"
              accept={ALLOWED_AVATAR_TYPES.join(',')}
              className="sr-only"
              aria-label="Upload avatar photo"
              onChange={handleAvatarChange}
            />
            <button
              type="button"
              disabled={uploading}
              onClick={() => setAvatarLightboxOpen(true)}
              className="relative group rounded-full focus-visible:outline-none focus-visible:shadow-glow disabled:opacity-60"
              aria-label={uploading ? 'Uploading…' : 'View or change avatar photo'}
            >
              <Avatar name={stats.player_name} size="lg" src={stats.avatar_url} />
              <span
                aria-hidden
                className="absolute inset-0 flex items-center justify-center rounded-full bg-black/40 opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100 transition-opacity"
              >
                <Camera className="h-5 w-5 text-white" />
              </span>
            </button>
          </div>
        ) : (
          /* Other players — click opens lightbox */
          <button
            type="button"
            onClick={() => setAvatarLightboxOpen(true)}
            className="relative group rounded-full focus-visible:outline-none focus-visible:shadow-glow shrink-0"
            aria-label="View avatar photo"
          >
            <Avatar name={stats.player_name} size="lg" src={stats.avatar_url} />
            {stats.avatar_url && (
              <span
                aria-hidden
                className="absolute inset-0 flex items-center justify-center rounded-full bg-black/40 opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100 transition-opacity"
              />
            )}
          </button>
        )}
        <PageHeader
          title={stats.player_name}
          eyebrow={`${stats.total_predictions_settled} predictions settled`}
          back={{ label: 'Back' }}
        />
      </div>

      {/* Stat cards */}
      <div>
        <h2 className="text-base font-semibold text-text-primary font-sans tracking-tight mb-3">Stats</h2>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          <StatCard label="Total Points" value={stats.total_points} />
          <StatCard label="Accuracy" value={`${stats.accuracy_pct}%`} />
          <StatCard label="Exact Score" value={`${stats.exact_rate_pct}%`} />
          <StatCard label="Avg Pts / Match" value={stats.avg_pts_per_prediction} />
          <StatCard label="Current Streak" value={streakDisplay} />
          <StatCard
            label="Avg Submit Time"
            value={
              stats.avg_prediction_timing_mins !== null
                ? formatSubmitTime(stats.avg_prediction_timing_mins)
                : '—'
            }
          />
        </div>
      </div>

      {isSelf && home?.rollup && <LatestMatchdaySection rollup={home.rollup} timezone={timezone} />}

      {/* U38: points decomposition + tiebreaker counts */}
      <PointsBreakdownSection stats={stats} />

      {/* Best / worst round */}
      {hasRoundVariance ? (
        <div>
          <h2 className="text-base font-semibold text-text-primary font-sans tracking-tight mb-3">
            Best &amp; Worst Round
          </h2>
          <div className="grid grid-cols-2 gap-3">
            {stats.best_round && (
              <div className="rounded-lg border border-border bg-surface p-4">
                <span className="text-xs text-text-muted font-sans uppercase tracking-wide">
                  Best
                </span>
                <p className="text-text-primary font-medium mt-1">
                  {STAGE_LABEL[stats.best_round] ?? stats.best_round}
                </p>
                <p className="text-primary font-bold text-xl">{stats.best_round_points} pts</p>
              </div>
            )}
            {stats.worst_round && (
              <div className="rounded-lg border border-border bg-surface p-4">
                <span className="text-xs text-text-muted font-sans uppercase tracking-wide">
                  Worst
                </span>
                <p className="text-text-primary font-medium mt-1">
                  {STAGE_LABEL[stats.worst_round] ?? stats.worst_round}
                </p>
                <p className="text-primary font-bold text-xl">{stats.worst_round_points} pts</p>
              </div>
            )}
          </div>
        </div>
      ) : showBestWorstPlaceholder ? (
        <div className="rounded-lg border border-dashed border-border bg-surface/40 px-4 py-3 text-center">
          <p className="text-sm font-sans text-text-muted">No round results yet</p>
        </div>
      ) : null}

      {/* Head-to-head mini table (only shown when viewing another player) */}
      {h2hTarget && (
        <div>
          <h2 className="text-base font-semibold text-text-primary font-sans tracking-tight mb-3">
            You vs {stats.player_name}
          </h2>
          <div className="rounded-lg border border-border bg-surface overflow-hidden">
            <table className="w-full text-sm font-sans">
              <thead>
                <tr className="border-b border-border text-text-muted text-xs">
                  <th className="py-2 pl-4 text-left">Metric</th>
                  <th className="py-2 text-center">You</th>
                  <th className="py-2 pr-4 text-center">{stats.player_name}</th>
                </tr>
              </thead>
              <tbody>
                {(
                  [
                    ['Total Points', h2hTarget.total_points, stats.total_points],
                    [
                      'Accuracy',
                      `${h2hTarget.accuracy_pct}%`,
                      `${stats.accuracy_pct}%`,
                    ],
                    [
                      'Exact Rate',
                      `${h2hTarget.exact_rate_pct}%`,
                      `${stats.exact_rate_pct}%`,
                    ],
                    ['Streak', h2hTarget.current_streak, stats.current_streak],
                    [
                      'Avg Pts',
                      h2hTarget.avg_pts_per_prediction,
                      stats.avg_pts_per_prediction,
                    ],
                  ] as [string, string | number, string | number][]
                ).map(([label, me, them]) => (
                  <tr key={label} className="border-b border-border/50 last:border-0">
                    <td className="py-2 pl-4 text-text-muted">{label}</td>
                    <td className="py-2 text-center font-medium text-text-primary">{me}</td>
                    <td className="py-2 pr-4 text-center font-medium text-text-primary">{them}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Recent predictions */}
      {recentPreds.length > 0 && (
        <div>
          <h2 className="text-base font-semibold text-text-primary font-sans tracking-tight mb-3">
            Recent Predictions
          </h2>
          <div className="rounded-lg border border-border bg-surface overflow-hidden">
            <table className="w-full text-sm font-sans">
              <thead>
                <tr className="border-b border-border text-text-muted text-xs">
                  <th className="py-2 pl-4 text-left">Match</th>
                  <th className="py-2 text-center">Result</th>
                  <th className="py-2 text-center">Predicted</th>
                  <th className="py-2 pr-4 text-center">Pts</th>
                </tr>
              </thead>
              <tbody>
                {recentPreds.map((p) => {
                  const unfinished = isMatchUnfinished(p);
                  return (
                    <tr
                      key={p.match_id}
                      className="border-b border-border/50 last:border-0"
                    >
                      <td className="py-2 pl-4">
                        <span className="text-text-primary">
                          {p.home_team_flag} {p.home_team_name ?? '?'} vs{' '}
                          {p.away_team_flag} {p.away_team_name ?? '?'}
                        </span>
                        <span className="block text-xs text-text-muted">
                          {STAGE_LABEL[p.stage] ?? p.stage}
                        </span>
                      </td>
                      <td className="py-2 text-center text-text-secondary font-mono">
                        {p.actual_home ?? '?'}–{p.actual_away ?? '?'}
                      </td>
                      <td className="py-2 text-center text-text-secondary font-mono">
                        {p.predicted_home ?? '?'}–{p.predicted_away ?? '?'}
                      </td>
                      <td className={`py-2 pr-4 text-center font-bold ${outcomeClass(p.points_awarded, unfinished)}`}>
                        {unfinished ? '—' : (
                          p.points_awarded != null ? (
                            <PointsBreakdownPopover breakdown={p.points_breakdown}>
                              <span>{p.points_awarded}</span>
                            </PointsBreakdownPopover>
                          ) : '—'
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* U24: reveal-gated prediction board — group, knockout, specials. Each
          section self-hides when empty; the backend only returns locked rows. */}
      {revealed && <GroupPredictionsSection data={revealed.group} />}
      {revealed && <KnockoutPredictionsSection data={revealed.knockout} />}
      {revealed && (
        <SpecialPredictionsSection
          revealed={revealed.specials_revealed}
          data={revealed.specials}
        />
      )}

      {recentPreds.length === 0 &&
        stats.total_predictions_settled === 0 &&
        (!revealed ||
          (revealed.group.length === 0 &&
            revealed.knockout.length === 0 &&
            revealed.specials.length === 0)) && (
          <EmptyState
            title="No predictions to show yet"
            description="A player's picks appear here once each match locks at kickoff."
          />
        )}
    </div>
  );
}
