import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { formatInTimeZone } from 'date-fns-tz';
import { apiFetch } from '../lib/api';
import { useAuth } from '../contexts/AuthContext';
import type { MatchResponse, PredictionResponse } from '../lib/types';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Skeleton } from '../components/ui/skeleton';
import { EmptyState } from '../components/EmptyState';
import { PageHeader } from '../components/PageHeader';
import { KNOCKOUT_STAGES, STAGE_LONG } from '../lib/stages';
import { canEdit } from '../lib/matchStatus';
import { shortPlaceholder } from '../lib/matchTeam';
import { cn } from '../lib/utils';

type StatusVariant = 'default' | 'success' | 'error' | 'muted' | 'accent' | 'warning' | 'live';

const STATUS_LABEL: Record<MatchResponse['status'], string> = {
  scheduled: 'Scheduled',
  locked: 'Locked',
  live: 'Live',
  completed: 'FT',
  postponed: 'Postponed',
  cancelled: 'Cancelled',
};

const STATUS_VARIANT: Record<MatchResponse['status'], StatusVariant> = {
  scheduled: 'muted',
  locked: 'warning',
  live: 'live',
  completed: 'success',
  postponed: 'warning',
  cancelled: 'error',
};

function MatchCard({
  match,
  timezone,
  prediction,
  showDate = false,
}: {
  match: MatchResponse;
  timezone: string;
  prediction?: PredictionResponse;
  showDate?: boolean;
}) {
  const kickoffLocal = formatInTimeZone(new Date(match.kickoff_utc), timezone, 'HH:mm');
  const kickoffDate = formatInTimeZone(new Date(match.kickoff_utc), timezone, 'd MMM');

  const homeLabel = match.home_team
    ? `${match.home_team.flag_emoji} ${match.home_team.code}`
    : shortPlaceholder(match.home_team_placeholder);
  const awayLabel = match.away_team
    ? `${match.away_team.flag_emoji} ${match.away_team.code}`
    : shortPlaceholder(match.away_team_placeholder);
  const homeTitle = !match.home_team ? (match.home_team_placeholder ?? undefined) : undefined;
  const awayTitle = !match.away_team ? (match.away_team_placeholder ?? undefined) : undefined;

  const isResult =
    match.status === 'completed' &&
    match.actual_home_score !== null &&
    match.actual_away_score !== null;

  const isPostponedOrCancelled =
    match.status === 'postponed' || match.status === 'cancelled';

  const homeWon = isResult && match.actual_home_score! > match.actual_away_score!;
  const awayWon = isResult && match.actual_away_score! > match.actual_home_score!;
  const hasPrediction =
    prediction?.predicted_home !== null &&
    prediction?.predicted_home !== undefined &&
    prediction?.predicted_away !== null &&
    prediction?.predicted_away !== undefined;

  let personalStatus: { label: string; variant: StatusVariant } | null = null;
  if (hasPrediction) {
    personalStatus = {
      label: `Predicted ${prediction.predicted_home}-${prediction.predicted_away}`,
      variant: 'default',
    };
  } else if (canEdit(match.status)) {
    personalStatus = { label: 'Missing', variant: 'warning' };
  } else if (match.status === 'locked' || match.status === 'live' || match.status === 'completed') {
    personalStatus = { label: 'No entry', variant: 'muted' };
  }

  return (
    <Link
      to={`/matches/${match.id}`}
      className={cn(
        'rounded-lg border border-border bg-surface px-3 py-3 flex items-center gap-3',
        'hover:bg-surface-elevated transition-colors press-down focus-visible:outline-none focus-visible:shadow-glow',
        isPostponedOrCancelled && 'opacity-60',
      )}
    >
      <div className="w-12 text-center shrink-0">
        {showDate && (
          <p className="text-[10px] font-mono text-text-muted tabular-nums leading-tight">
            {kickoffDate}
          </p>
        )}
        <p className="text-sm font-mono text-text-primary font-medium tabular-nums tracking-tight">
          {kickoffLocal}
        </p>
        {match.status === 'live' && (
          <span className="text-[10px] font-mono text-live uppercase tracking-[0.2em] animate-pulse-live">
            Live
          </span>
        )}
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between gap-2">
          <span
            title={homeTitle}
            className={cn(
              'text-sm font-sans truncate',
              homeWon ? 'text-text-primary font-semibold' : 'text-text-secondary',
              homeTitle && 'italic text-text-muted font-mono text-xs',
            )}
          >
            {homeLabel}
          </span>

          {isResult ? (
            <span className="font-mono text-sm font-semibold text-text-primary tabular-nums shrink-0">
              {match.actual_home_score} – {match.actual_away_score}
            </span>
          ) : (
            <span className="text-[10px] text-text-muted font-mono shrink-0">vs</span>
          )}

          <span
            title={awayTitle}
            className={cn(
              'text-sm font-sans truncate text-right',
              awayWon ? 'text-text-primary font-semibold' : 'text-text-secondary',
              awayTitle && 'italic text-text-muted font-mono text-xs',
            )}
          >
            {awayLabel}
          </span>
        </div>

        <div className="flex items-center gap-2 mt-1">
          {match.group_name && (
            <span className="text-[10px] font-mono text-text-muted uppercase tracking-wider shrink-0">
              Group {match.group_name}
            </span>
          )}
          {match.venue && (
            <span className="text-xs text-text-muted font-sans truncate">{match.venue}</span>
          )}
          {match.penalties && (
            <span className="text-[10px] text-text-muted font-mono uppercase tracking-wider">
              pens
            </span>
          )}
          {match.extra_time && !match.penalties && (
            <span className="text-[10px] text-text-muted font-mono uppercase tracking-wider">
              aet
            </span>
          )}
        </div>
        {personalStatus && (
          <div className="mt-2">
            <Badge variant={personalStatus.variant}>{personalStatus.label}</Badge>
          </div>
        )}
      </div>

      <div className="shrink-0">
        <Badge variant={STATUS_VARIANT[match.status]}>{STATUS_LABEL[match.status]}</Badge>
      </div>
    </Link>
  );
}

function ScheduleSection({
  label,
  matches,
  timezone,
  predByMatch,
  isRound = false,
}: {
  label: string;
  matches: MatchResponse[];
  timezone: string;
  predByMatch: Record<string, PredictionResponse>;
  isRound?: boolean;
}) {
  return (
    <section>
      <div className="sticky top-14 z-10 -mx-4 sm:-mx-0 px-4 sm:px-0 py-2 bg-surface-elevated/95 backdrop-blur-sm mb-2 first:pt-0">
        <h2
          className={cn(
            'text-[10px] font-mono uppercase tracking-[0.25em]',
            isRound ? 'text-primary' : 'text-text-muted',
          )}
        >
          {label}
        </h2>
      </div>
      <div className="flex flex-col gap-2">
        {matches.map((m) => (
          <MatchCard
            key={m.id}
            match={m}
            timezone={timezone}
            prediction={predByMatch[m.id]}
            showDate={isRound}
          />
        ))}
      </div>
    </section>
  );
}

// Filter pills: All + Group, then the knockout rounds from the shared stage
// table so the chips match the Knockout Picks round scroller exactly.
const STAGES = [
  { value: '', label: 'All' },
  { value: 'group', label: 'Group' },
  ...KNOCKOUT_STAGES.map((s) => ({ value: s.key, label: s.short })),
];

// Knockout matches are grouped under a round heading (the long stage label)
// instead of a date — a round spans several days, so the per-match date is
// shown on each card.

function StageFilter({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <nav className="-mx-4 sm:-mx-0 mb-5 overflow-x-auto" aria-label="Filter by stage">
      <div className="flex gap-1.5 px-4 sm:px-0 min-w-max">
        {STAGES.map((s) => (
          <button
            key={s.value}
            type="button"
            onClick={() => onChange(s.value)}
            aria-pressed={value === s.value}
            className={cn(
              'inline-flex items-center px-3.5 py-1.5 rounded-full text-xs font-medium font-sans whitespace-nowrap transition-colors press-down focus-visible:outline-none focus-visible:shadow-glow',
              value === s.value
                ? 'bg-primary/15 text-primary border border-primary/30'
                : 'bg-surface text-text-secondary hover:bg-surface-elevated border border-border',
            )}
          >
            {s.label}
          </button>
        ))}
      </div>
    </nav>
  );
}

export function SchedulePage() {
  const { player } = useAuth();
  const timezone = player?.timezone ?? 'UTC';

  const [stageFilter, setStageFilter] = useState('');

  const { data, isLoading, error, refetch, isRefetching } = useQuery<MatchResponse[]>({
    queryKey: ['matches', stageFilter],
    queryFn: () =>
      apiFetch<MatchResponse[]>(`/api/v1/matches${stageFilter ? `?stage=${stageFilter}` : ''}`),
    staleTime: 30_000,
  });
  const { data: predictions = [] } = useQuery<PredictionResponse[]>({
    queryKey: ['predictions', 'me'],
    queryFn: () => apiFetch<PredictionResponse[]>('/api/v1/predictions/me'),
    staleTime: 30_000,
  });

  const matches = data ?? [];
  const predByMatch = Object.fromEntries(predictions.map((p) => [p.match_id, p]));

  // Group-stage matches are bucketed by date; knockout matches by round.
  // The API returns matches in kickoff order, so group dates appear first and
  // knockout rounds follow in bracket order (R32 → … → Final).
  const sections = new Map<string, { matches: MatchResponse[]; isRound: boolean }>();
  for (const m of matches) {
    const isRound = m.stage !== 'group';
    const key = isRound
      ? (STAGE_LONG[m.stage] ?? m.stage)
      : formatInTimeZone(new Date(m.kickoff_utc), timezone, 'EEE d MMM yyyy');
    const bucket = sections.get(key) ?? { matches: [], isRound };
    bucket.matches.push(m);
    sections.set(key, bucket);
  }

  return (
    <div>
      <PageHeader title="Schedule" eyebrow="Fixtures" />
      <StageFilter value={stageFilter} onChange={setStageFilter} />

      {isLoading && (
        <div className="flex flex-col gap-6" aria-label="Loading matches">
          {[0, 1].map((s) => (
            <section key={s}>
              <Skeleton className="h-3 w-32 mb-3" />
              <div className="flex flex-col gap-2">
                {[0, 1, 2].map((i) => (
                  <Skeleton key={i} className="h-16 w-full rounded-lg" />
                ))}
              </div>
            </section>
          ))}
        </div>
      )}
      {error && (
        <EmptyState
          title="Couldn't load the schedule"
          description="There was a problem reaching the server. Check your connection and try again."
          action={
            <Button variant="outline" size="sm" disabled={isRefetching} onClick={() => refetch()}>
              {isRefetching ? 'Retrying…' : 'Try again'}
            </Button>
          }
        />
      )}

      {!isLoading && !error && sections.size === 0 && (
        <EmptyState
          title="No matches found"
          description={
            stageFilter
              ? 'Nothing matches this stage filter — try "All".'
              : 'The fixture list is empty.'
          }
        />
      )}

      <div className="flex flex-col gap-6">
        {Array.from(sections.entries()).map(([label, { matches: sectionMatches, isRound }]) => (
          <ScheduleSection
            key={label}
            label={label}
            matches={sectionMatches}
            timezone={timezone}
            predByMatch={predByMatch}
            isRound={isRound}
          />
        ))}
      </div>
    </div>
  );
}
