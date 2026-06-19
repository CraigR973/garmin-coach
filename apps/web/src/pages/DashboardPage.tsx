import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { formatInTimeZone } from 'date-fns-tz';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { isKnockoutStage, scoreLiveProvisionalPrediction, type Stage } from '@wc2026/shared';
import { apiFetch } from '../lib/api';
import { useAuth } from '../contexts/AuthContext';
import { UpcomingMatchesCarousel } from '../components/UpcomingMatchesCarousel';
import { ScoringGuide } from '../components/ScoringGuide';
import { PointsBreakdownRow } from '../components/PointsBreakdownRow';
import { useCountdown } from '../hooks/useCountdown';
import { Skeleton } from '../components/ui/skeleton';
import type {
  CrossLeagueSummary,
  HomeResponse,
  KnockoutPredictionResponse,
  MatchResponse,
  PredictionResponse,
} from '../lib/types';


function SectionHeader({ id, children }: { id: string; children: ReactNode }) {
  return (
    <h2 id={id} className="mb-2 px-0.5 text-lg font-bold tracking-tight text-text-primary">
      {children}
    </h2>
  );
}

function formatCountdown(cd: {
  days: number;
  hours: number;
  minutes: number;
  seconds: number;
  expired: boolean;
}): string {
  if (cd.expired) return 'Kicked off';
  if (cd.days > 0) return `${cd.days}d ${cd.hours}h`;
  if (cd.hours > 0) return `${cd.hours}h ${cd.minutes}m`;
  return `${cd.minutes}m ${cd.seconds}s`;
}

type InlineSlot = { kind: 'next' | 'last'; match: MatchResponse };

function pickInlineSlot(matches: MatchResponse[]): InlineSlot | null {
  const completed = matches
    .filter((m) => m.status === 'completed')
    .sort((a, b) => b.kickoff_utc.localeCompare(a.kickoff_utc));
  if (completed[0]) return { kind: 'last', match: completed[0] };

  const upcoming = matches
    .filter((m) => m.status === 'scheduled' || m.status === 'locked')
    .sort((a, b) => a.kickoff_utc.localeCompare(b.kickoff_utc));
  if (upcoming[0]) return { kind: 'next', match: upcoming[0] };

  return null;
}

function chipTeam(team: MatchResponse['home_team'], placeholder: string | null) {
  return { flag: team?.flag_emoji ?? '', code: team?.code ?? placeholder ?? 'TBD' };
}

// Rollup rows carry the flag emoji on its own (the `home_label` also embeds it).
// Show flag + score only: the flag is the team identifier, and dropping the
// redundant 3-letter code keeps each row short enough that the away team isn't
// clipped in the deliberately-narrow points tile. Falls back to a short code for
// placeholder teams with no flag (not expected in a completed-matchday rollup).
function rollupTeam(flag: string | null, label: string): string {
  if (flag) return flag;
  return label.slice(0, 3).toUpperCase();
}

function formatElapsed(elapsed: number | null | undefined): string | null {
  if (elapsed == null) return null;
  return `${elapsed}'`;
}

function formatTileKickoff(kickoffUtc: string, timezone: string): string {
  return formatInTimeZone(new Date(kickoffUtc), timezone, 'EEE d MMM, HH:mm');
}

function getLivePriority(match: MatchResponse, prediction: PredictionResponse | undefined): number {
  const hasPrediction =
    prediction != null &&
    prediction.predicted_home !== null &&
    prediction.predicted_away !== null;

  return (hasPrediction ? 10_000 : 0) + (match.elapsed_minutes ?? 0);
}

function PointsTile({
  playerId,
  points,
  rollup,
  inlineSlot,
  timezone,
  isLoading,
}: {
  playerId: string | undefined;
  points: number;
  rollup: HomeResponse['rollup'];
  inlineSlot: InlineSlot | null;
  timezone: string;
  isLoading: boolean;
}) {
  if (isLoading) {
    return <Skeleton className="h-full min-h-[184px] rounded-[1.25rem]" />;
  }

  return (
    <Link
      to={playerId ? `/players/${playerId}` : '/leagues'}
      aria-label="Open your profile"
      className="flex h-full min-h-[184px] flex-col justify-between rounded-[1.25rem] border border-border bg-gradient-to-br from-surface-elevated via-surface to-surface p-4 shadow-sm transition-transform duration-150 hover:-translate-y-0.5 focus-visible:outline-none focus-visible:shadow-glow sm:p-5"
      data-testid="points-tile"
    >
      <div className="text-center">
        <p className="mt-2 font-mono text-4xl font-semibold leading-none tabular-nums text-primary sm:text-5xl">
          {points}
        </p>
        <p className="mt-2 font-mono text-[10px] uppercase tracking-[0.25em] text-text-muted">Points</p>
      </div>

      <div className="space-y-2 border-t border-border/60 pt-3">
        {rollup ? (
          <>
            <div className="flex items-baseline justify-between">
              <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-text-muted">
                {formatInTimeZone(new Date(rollup.matchday + 'T00:00:00Z'), timezone, 'EEE d MMM')}
              </p>
              <p className="font-mono text-[10px] font-semibold tabular-nums text-primary">
                +{rollup.points_gained} pts
              </p>
            </div>
            <div className="space-y-1">
              {rollup.matches.slice(0, 4).map((m) => (
                <div key={m.match_id} className="flex items-center justify-between gap-1">
                  <p className="min-w-0 truncate font-mono text-xs tabular-nums text-text-primary">
                    {rollupTeam(m.home_flag, m.home_label)} {m.actual_home ?? 0}–{m.actual_away ?? 0} {rollupTeam(m.away_flag, m.away_label)}
                  </p>
                  <p className={`shrink-0 font-mono text-xs tabular-nums font-medium ${(m.points_breakdown?.total ?? 0) > 0 ? 'text-primary' : 'text-text-muted'}`}>
                    {(m.points_breakdown?.total ?? 0) > 0 ? `+${m.points_breakdown!.total}` : '—'}
                  </p>
                </div>
              ))}
              {rollup.matches.length > 4 && (
                <p className="font-mono text-[10px] text-text-muted">+{rollup.matches.length - 4} more</p>
              )}
            </div>
          </>
        ) : (
          <>
            {inlineSlot?.kind === 'next' && (
              <div
                className="rounded-2xl border border-border/60 bg-surface/80 px-3 py-2.5"
                data-testid="points-tile-inline-next"
              >
                <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-text-muted">Next fixture</p>
                <p className="mt-1 font-mono text-sm tabular-nums text-text-primary">
                  {(() => {
                    const home = chipTeam(inlineSlot.match.home_team, inlineSlot.match.home_team_placeholder);
                    const away = chipTeam(inlineSlot.match.away_team, inlineSlot.match.away_team_placeholder);
                    return `${home.flag} ${home.code} v ${away.code} ${away.flag}`;
                  })()}
                </p>
              </div>
            )}
          </>
        )}
      </div>
    </Link>
  );
}

function MatchTileLiveCard({
  match,
  prediction,
  knockoutPrediction,
  timezone,
}: {
  match: MatchResponse;
  prediction: PredictionResponse | undefined;
  knockoutPrediction: KnockoutPredictionResponse | undefined;
  timezone: string;
}) {
  const home = chipTeam(match.home_team, match.home_team_placeholder);
  const away = chipTeam(match.away_team, match.away_team_placeholder);
  // The football-data competition feed carries no in-play score (see
  // MatchResponse.elapsed_minutes in routers/matches.py), so during a live match
  // actual_*_score stay null until full-time. Only show a scoreline + provisional
  // "if it stands" points when a real score is present — otherwise we'd render a
  // fabricated 0–0 and misleading projected points. Forward-compatible: this lights
  // back up automatically the day a live-score source exists.
  const hasLiveScore =
    match.actual_home_score !== null && match.actual_away_score !== null;
  const minute = formatElapsed(match.elapsed_minutes);
  const hasPrediction =
    prediction != null &&
    prediction.predicted_home !== null &&
    prediction.predicted_away !== null;
  const provisionalBreakdown =
    hasLiveScore && hasPrediction
      ? scoreLiveProvisionalPrediction({
          prediction: {
            homeScore: prediction.predicted_home!,
            awayScore: prediction.predicted_away!,
          },
          actual: { homeScore: match.actual_home_score!, awayScore: match.actual_away_score! },
          stage: match.stage as Stage,
          homeTeamId: match.home_team?.id,
          awayTeamId: match.away_team?.id,
          predictedWinnerId: knockoutPrediction?.predicted_winner_id,
        })
      : null;
  const showProvisional =
    provisionalBreakdown != null && !provisionalBreakdown.match.noPrediction;

  return (
    <Link
      to={`/matches/${match.id}`}
      aria-label={`Open live match ${home.code} versus ${away.code}`}
      className="block rounded-[1.25rem] border border-live/40 bg-gradient-to-br from-live/10 via-surface to-surface p-4 shadow-sm transition-transform duration-150 hover:-translate-y-0.5 focus-visible:outline-none focus-visible:shadow-glow sm:p-5"
      data-testid="match-tile-live-card"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-success">
            Live{minute ? ` · ${minute}` : ''}
          </p>
          <p className="mt-1 text-xs text-text-muted">{formatTileKickoff(match.kickoff_utc, timezone)}</p>
        </div>
        <span className="rounded-full border border-live/40 bg-live/10 px-2 py-1 font-mono text-[10px] uppercase tracking-[0.15em] text-success">
          In play
        </span>
      </div>

      <div className="mt-5 flex items-center justify-between gap-3">
        <span className="min-w-0 font-mono text-base font-semibold text-text-primary sm:text-lg">
          {home.flag} {home.code}
        </span>
        {hasLiveScore ? (
          <span className="shrink-0 font-mono text-3xl font-semibold tabular-nums text-primary sm:text-[2rem]">
            {match.actual_home_score}–{match.actual_away_score}
          </span>
        ) : (
          <span className="shrink-0 font-mono text-sm font-medium uppercase tracking-[0.15em] text-text-muted">
            vs
          </span>
        )}
        <span className="min-w-0 text-right font-mono text-base font-semibold text-text-primary sm:text-lg">
          {away.code} {away.flag}
        </span>
      </div>

      <div className="mt-5 space-y-2 border-t border-border/60 pt-3">
        <p className="text-sm text-text-primary">
          {hasPrediction ? (
            <>
              <span className="text-text-muted">Your pick: </span>
              <span className="font-mono font-medium tabular-nums">
                {prediction.predicted_home}–{prediction.predicted_away}
              </span>
              {showProvisional && (
                <>
                  <span className="text-text-muted"> · </span>
                  <span className="font-mono font-semibold tabular-nums text-primary">
                    +{provisionalBreakdown.total} if it stands
                  </span>
                </>
              )}
            </>
          ) : (
            <span className="text-text-muted">No prediction on this one.</span>
          )}
        </p>
        {!hasLiveScore && (
          <p className="text-xs text-text-muted">
            {hasPrediction ? 'Result & points at full-time' : 'Result at full-time'}
          </p>
        )}
        {showProvisional && provisionalBreakdown.advancement.status !== 'not_applicable' && (
          <div
            className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-border/60 bg-surface/70 px-3 py-2 font-mono text-[11px] tabular-nums"
            data-testid="provisional-combined-breakdown"
          >
            <span className="text-text-muted">
              Match{' '}
              <span className="font-semibold text-text-primary">
                +{provisionalBreakdown.match.total}
              </span>
            </span>
            {provisionalBreakdown.advancement.status === 'determined' ? (
              <span className="text-text-muted">
                Advancement{' '}
                <span className="font-semibold text-text-primary">
                  +{provisionalBreakdown.advancement.points}
                </span>
              </span>
            ) : (
              <span className="text-live">Advancement undecided</span>
            )}
            <span className="ml-auto font-semibold text-primary">{provisionalBreakdown.total} pts</span>
          </div>
        )}
        {showProvisional && (
          <PointsBreakdownRow
            breakdown={{
              result: provisionalBreakdown.match.correctResult,
              goals: provisionalBreakdown.match.totalGoals,
              exact: provisionalBreakdown.match.exactScore,
              total: provisionalBreakdown.total,
            }}
          />
        )}
      </div>
    </Link>
  );
}

function MatchTileFixtureCard({
  kind,
  match,
  prediction,
  timezone,
}: {
  kind: 'next' | 'last';
  match: MatchResponse;
  prediction?: PredictionResponse;
  timezone: string;
}) {
  const countdown = useCountdown(match.kickoff_utc);
  const home = chipTeam(match.home_team, match.home_team_placeholder);
  const away = chipTeam(match.away_team, match.away_team_placeholder);

  const hasPrediction =
    kind === 'last' &&
    prediction != null &&
    prediction.predicted_home !== null &&
    prediction.predicted_away !== null;

  return (
    <Link
      to={`/matches/${match.id}`}
      aria-label={`Open ${kind === 'next' ? 'next' : 'last'} match ${home.code} versus ${away.code}`}
      className="flex h-full min-h-[184px] flex-col justify-between rounded-[1.25rem] border border-border bg-gradient-to-br from-surface-elevated via-surface to-surface p-4 shadow-sm transition-transform duration-150 hover:-translate-y-0.5 focus-visible:outline-none focus-visible:shadow-glow sm:p-5"
      data-testid={kind === 'next' ? 'match-tile-next' : 'match-tile-last'}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-text-muted">
            {kind === 'next' ? 'Next up' : 'Latest final'}
          </p>
          <p className="mt-1 text-xs text-text-muted">{formatTileKickoff(match.kickoff_utc, timezone)}</p>
        </div>
        <span className="rounded-full border border-border/60 bg-surface/80 px-2 py-1 font-mono text-[10px] uppercase tracking-[0.15em] text-text-muted">
          {kind === 'next' ? (countdown.expired ? 'Locked' : `in ${formatCountdown(countdown)}`) : 'Full time'}
        </span>
      </div>

      <div className="mt-5 flex items-center justify-between gap-3">
        <span className="min-w-0 font-mono text-base font-semibold text-text-primary sm:text-lg">
          {home.flag} {home.code}
        </span>
        <span className="shrink-0 font-mono text-3xl font-semibold tabular-nums text-primary sm:text-[2rem]">
          {kind === 'next'
            ? 'v'
            : `${match.actual_home_score ?? 0}–${match.actual_away_score ?? 0}`}
        </span>
        <span className="min-w-0 text-right font-mono text-base font-semibold text-text-primary sm:text-lg">
          {away.code} {away.flag}
        </span>
      </div>

      <div className="mt-5 border-t border-border/60 pt-3">
        {hasPrediction && prediction!.points_breakdown ? (
          <div className="space-y-1.5">
            <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-text-muted">
              Your pick:{' '}
              <span className="text-text-primary">
                {prediction!.predicted_home}–{prediction!.predicted_away}
              </span>
            </p>
            <PointsBreakdownRow breakdown={prediction!.points_breakdown} />
          </div>
        ) : (
          <p className="text-sm text-text-muted">
            {kind === 'next'
              ? 'Tap through to check the match detail and prediction form before lock.'
              : hasPrediction
                ? 'Tap through for the full result and your prediction outcome.'
                : 'Tap through for the full result.'}
          </p>
        )}
      </div>
    </Link>
  );
}

function LiveMatchCarousel({
  matches,
  predByMatch,
  knockoutPredByMatch,
  timezone,
}: {
  matches: MatchResponse[];
  predByMatch: Record<string, PredictionResponse>;
  knockoutPredByMatch: Record<string, KnockoutPredictionResponse>;
  timezone: string;
}) {
  const orderedMatches = [...matches].sort(
    (a, b) => getLivePriority(b, predByMatch[b.id]) - getLivePriority(a, predByMatch[a.id]),
  );
  const [activeIndex, setActiveIndex] = useState(0);
  const touchStartX = useRef<number | null>(null);
  const liveIds = orderedMatches.map((match) => match.id).join(',');

  useEffect(() => {
    setActiveIndex(0);
  }, [liveIds]);

  const canPage = orderedMatches.length > 1;
  const currentMatch = orderedMatches[activeIndex] ?? orderedMatches[0];

  const move = (delta: number) => {
    setActiveIndex((value) => {
      const nextValue = value + delta;
      if (nextValue < 0) return orderedMatches.length - 1;
      if (nextValue >= orderedMatches.length) return 0;
      return nextValue;
    });
  };

  return (
    <div
      className="flex h-full min-h-[184px] flex-col rounded-[1.25rem] border border-border bg-surface shadow-sm"
      data-testid="match-tile-live-carousel"
      onTouchStart={(event) => {
        touchStartX.current = event.changedTouches[0]?.clientX ?? null;
      }}
      onTouchEnd={(event) => {
        const startX = touchStartX.current;
        const endX = event.changedTouches[0]?.clientX ?? null;
        touchStartX.current = null;
        if (startX == null || endX == null) return;
        const deltaX = endX - startX;
        if (Math.abs(deltaX) < 40) return;
        move(deltaX < 0 ? 1 : -1);
      }}
    >
      <div className="flex items-center justify-between px-3 pt-3 sm:px-4 sm:pt-4">
        <div>
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-text-muted">Match hub</p>
          <p className="mt-1 text-sm text-text-muted">
            {orderedMatches.length} live {orderedMatches.length === 1 ? 'match' : 'matches'}
          </p>
        </div>
        {canPage && (
          <div className="hidden items-center gap-1 sm:flex">
            <button
              type="button"
              aria-label="Previous live match"
              onClick={() => move(-1)}
              className="rounded-full border border-border/60 bg-surface-elevated p-2 text-text-muted transition-colors hover:text-text-primary focus-visible:outline-none focus-visible:shadow-glow"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <button
              type="button"
              aria-label="Next live match"
              onClick={() => move(1)}
              className="rounded-full border border-border/60 bg-surface-elevated p-2 text-text-muted transition-colors hover:text-text-primary focus-visible:outline-none focus-visible:shadow-glow"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        )}
      </div>

      <div className="flex-1 px-2 pb-2 pt-2 sm:px-3 sm:pb-3">
        <MatchTileLiveCard
          key={currentMatch.id}
          match={currentMatch}
          prediction={predByMatch[currentMatch.id]}
          knockoutPrediction={knockoutPredByMatch[currentMatch.id]}
          timezone={timezone}
        />
      </div>

      {canPage && (
        <div className="flex items-center justify-center gap-2 px-3 pb-3">
          {orderedMatches.map((match, index) => (
            <button
              key={match.id}
              type="button"
              aria-label={`Show live match ${index + 1}`}
              aria-current={index === activeIndex}
              onClick={() => setActiveIndex(index)}
              className={`h-2.5 rounded-full transition-all focus-visible:outline-none focus-visible:shadow-glow ${
                index === activeIndex ? 'w-6 bg-primary' : 'w-2.5 bg-border'
              }`}
              data-testid="live-match-dot"
            />
          ))}
        </div>
      )}
    </div>
  );
}

type PerLeagueEntry = CrossLeagueSummary['per_league'][number];


function rankColor(delta: number | null): string {
  if (delta === null || delta === 0) return 'text-text-muted';
  return delta > 0 ? 'text-success' : 'text-live';
}

function CompactLeagueCard({ entry }: { entry: PerLeagueEntry }) {
  const { rank, name, slug, rank_delta } = entry;

  return (
    <Link
      to={`/leagues/${slug}/leaderboard`}
      aria-label={`Open ${name} leaderboard`}
      className="flex items-center gap-2 rounded-lg border border-border bg-surface px-2.5 py-2.5 transition-colors hover:border-primary/50 hover:bg-surface-elevated focus-visible:outline-none focus-visible:shadow-glow"
      data-testid="league-row-link"
    >
      <span className="truncate font-sans text-sm font-semibold text-text-primary leading-tight flex-1">
        {name}
      </span>
      {rank !== null && (
        <span className={`shrink-0 font-mono text-xs tabular-nums font-semibold ${rankColor(rank_delta)}`}>
          #{rank}{rank_delta !== null && rank_delta !== 0 ? (rank_delta > 0 ? ' ↑' : ' ↓') : ''}
        </span>
      )}
      <ChevronRight className="h-3 w-3 shrink-0 text-text-muted" aria-hidden />
    </Link>
  );
}

export function DashboardPage() {
  const { player } = useAuth();
  const timezone = player?.timezone ?? 'UTC';
  const displayName = player?.displayName ?? 'there';

  const { data: summary, isLoading: summaryLoading } = useQuery<CrossLeagueSummary>({
    queryKey: ['cross-league-summary'],
    queryFn: () => apiFetch<CrossLeagueSummary>('/api/v1/me/cross-league-summary'),
    staleTime: 30_000,
  });

  const { data: home, isLoading: homeLoading } = useQuery<HomeResponse>({
    queryKey: ['me-home'],
    queryFn: () => apiFetch<HomeResponse>('/api/v1/me/home'),
    staleTime: 30_000,
  });

  const { data: matches = [] } = useQuery<MatchResponse[]>({
    queryKey: ['matches', 'all'],
    queryFn: () => apiFetch<MatchResponse[]>('/api/v1/matches'),
    staleTime: 30_000,
    refetchInterval: 60_000,
  });

  const { data: predictions = [] } = useQuery<PredictionResponse[]>({
    queryKey: ['predictions', 'me'],
    queryFn: () => apiFetch<PredictionResponse[]>('/api/v1/predictions/me'),
    staleTime: 30_000,
  });

  const liveHasKnockout = matches.some(
    (m) => m.status === 'live' && isKnockoutStage(m.stage as Stage),
  );
  const { data: knockoutPredictions = [] } = useQuery<KnockoutPredictionResponse[]>({
    queryKey: ['knockout-predictions', 'me'],
    queryFn: () => apiFetch<KnockoutPredictionResponse[]>('/api/v1/knockout-predictions/me'),
    enabled: liveHasKnockout,
    staleTime: 30_000,
  });

  const perLeague = summary?.per_league ?? [];
  const liveMatches = matches.filter((m) => m.status === 'live');
  const inlineSlot = pickInlineSlot(matches);
  const predByMatch: Record<string, PredictionResponse> = Object.fromEntries(
    predictions.map((prediction) => [prediction.match_id, prediction]),
  );
  const knockoutPredByMatch: Record<string, KnockoutPredictionResponse> = Object.fromEntries(
    knockoutPredictions.map((prediction) => [prediction.match_id, prediction]),
  );
  const points = summary?.total_points ?? 0;
  const loadingTopRow = summaryLoading || homeLoading;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="mb-3 px-0.5 text-3xl font-bold tracking-tight text-text-primary sm:text-4xl">
          {perLeague.length === 0 ? `Welcome, ${displayName}` : `Welcome back, ${displayName}`}
        </h1>
        <div
          className="grid grid-cols-[minmax(0,0.92fr)_minmax(0,1.48fr)] gap-3"
          data-testid="dashboard-top-row"
        >
          <div data-testid="dashboard-points-column">
            <PointsTile
              playerId={player?.id}
              points={points}
              rollup={home?.rollup ?? null}
              inlineSlot={inlineSlot}
              timezone={timezone}
              isLoading={loadingTopRow}
            />
          </div>
          <div>
            {liveMatches.length > 0 ? (
              <LiveMatchCarousel
                matches={liveMatches}
                predByMatch={predByMatch}
                knockoutPredByMatch={knockoutPredByMatch}
                timezone={timezone}
              />
            ) : inlineSlot ? (
              <MatchTileFixtureCard kind={inlineSlot.kind} match={inlineSlot.match} prediction={predByMatch[inlineSlot.match.id]} timezone={timezone} />
            ) : (
              <Skeleton className="h-full min-h-[184px] rounded-[1.25rem]" />
            )}
          </div>
        </div>
        <div className="mt-3" data-testid="dashboard-scoring-ref">
          <ScoringGuide storageKey="sss_scoring_guide_home_v2_open" defaultOpen={false} />
        </div>
      </div>

      <UpcomingMatchesCarousel />

      {summaryLoading ? (
        <section aria-labelledby="home-leagues-label">
          <SectionHeader id="home-leagues-label">My Leagues</SectionHeader>
          <Skeleton className="h-[80px] rounded-lg" />
        </section>
      ) : perLeague.length > 0 ? (
        <section aria-labelledby="home-leagues-label">
          <SectionHeader id="home-leagues-label">My Leagues</SectionHeader>
          <div className={`grid gap-2 ${perLeague.length === 1 ? 'grid-cols-1' : 'grid-cols-2'}`}>
            {perLeague.map((entry) => (
              <CompactLeagueCard key={entry.slug} entry={entry} />
            ))}
          </div>
        </section>
      ) : !summaryLoading ? (
        <section aria-labelledby="home-leagues-label">
          <SectionHeader id="home-leagues-label">My Leagues</SectionHeader>
          <div className="rounded-lg border border-border bg-surface px-4 py-4 text-center space-y-3">
            <p className="text-sm font-sans text-text-secondary">You&rsquo;re not in any leagues yet.</p>
            <div className="flex justify-center gap-2 flex-wrap">
              <Link to="/leagues/new" className="rounded-full border border-primary/40 bg-primary/10 px-3 py-1 text-xs font-sans text-primary hover:bg-primary/20 transition-colors">+ Create</Link>
              <Link to="/leagues/join" className="rounded-full border border-border px-3 py-1 text-xs font-sans text-text-secondary hover:bg-surface-elevated transition-colors">Join</Link>
              <Link to="/leagues/discover" className="rounded-full border border-border px-3 py-1 text-xs font-sans text-text-secondary hover:bg-surface-elevated transition-colors">Discover</Link>
            </div>
          </div>
        </section>
      ) : null}
    </div>
  );
}
