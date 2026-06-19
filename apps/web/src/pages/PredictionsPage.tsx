import { useEffect, useState } from 'react';
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
import { PredictionsSubNav } from '../components/PredictionsSubNav';
import { PredictionCard } from '../components/PredictionCard';
import { ScoringGuide } from '../components/ScoringGuide';
import { usePredictionEditor } from '../hooks/usePredictionEditor';
import { setPredictionsDirty } from '../lib/dirtyState';
import { canEdit } from '../lib/matchStatus';
import { STAGE_LONG } from '../lib/stages';
import { cn } from '../lib/utils';

type FilterValue = 'all' | 'needs-picks' | 'upcoming' | 'live-locked' | 'completed';

const ALL_MATCHES_QUERY_KEY = ['matches'] as const;

const FILTERS: ReadonlyArray<{ value: FilterValue; label: string }> = [
  { value: 'all', label: 'All' },
  { value: 'needs-picks', label: 'Needs picks' },
  { value: 'upcoming', label: 'Upcoming' },
  { value: 'live-locked', label: 'Live/locked' },
  { value: 'completed', label: 'Completed' },
];

function getPredictionValues(
  prediction: PredictionResponse | undefined,
  local: { home: string; away: string } | undefined,
) {
  return {
    home:
      local?.home ??
      (prediction?.predicted_home !== null && prediction?.predicted_home !== undefined
        ? String(prediction.predicted_home)
        : ''),
    away:
      local?.away ??
      (prediction?.predicted_away !== null && prediction?.predicted_away !== undefined
        ? String(prediction.predicted_away)
        : ''),
  };
}

function hasPrediction(
  prediction: PredictionResponse | undefined,
  local: { home: string; away: string } | undefined,
) {
  const values = getPredictionValues(prediction, local);
  return values.home !== '' && values.away !== '';
}

function getSectionLabel(match: MatchResponse) {
  if (match.group_name) return `Group ${match.group_name}`;
  return STAGE_LONG[match.stage] ?? match.stage.toUpperCase();
}

function getDateHeading(match: MatchResponse, timezone: string) {
  return formatInTimeZone(new Date(match.kickoff_utc), timezone, 'EEE d MMM yyyy');
}

export function PredictionsPage() {
  const { player } = useAuth();
  const timezone = player?.timezone ?? 'UTC';
  const [filter, setFilter] = useState<FilterValue>('upcoming');

  const { data: matches = [], isLoading: matchesLoading } = useQuery<MatchResponse[]>({
    queryKey: ALL_MATCHES_QUERY_KEY,
    queryFn: () => apiFetch<MatchResponse[]>('/api/v1/matches'),
    staleTime: 30_000,
    refetchInterval: 60_000,
  });

  const { data: predictions = [], isLoading: predsLoading } = useQuery<PredictionResponse[]>({
    queryKey: ['predictions', 'me'],
    queryFn: () => apiFetch<PredictionResponse[]>('/api/v1/predictions/me'),
    staleTime: 30_000,
  });

  const { local, highlightedMatchIds, handleHomeChange, handleAwayChange, handleSaveAll } =
    usePredictionEditor({
      predictions,
      matches,
      matchesQueryKey: ALL_MATCHES_QUERY_KEY,
    });

  useEffect(() => {
    const totalDirty = matches.filter((m) => local[m.id]?.dirty).length;
    setPredictionsDirty(totalDirty > 0);
  }, [local, matches]);

  useEffect(() => () => setPredictionsDirty(false), []);

  const predByMatch = Object.fromEntries(predictions.map((p) => [p.match_id, p]));

  const sortedMatches = [...matches].sort((a, b) => a.kickoff_utc.localeCompare(b.kickoff_utc));
  const filteredMatches = sortedMatches.filter((match) => {
    const predicted = hasPrediction(predByMatch[match.id], local[match.id]);

    if (filter === 'needs-picks') return canEdit(match.status) && !predicted;
    if (filter === 'upcoming') return match.status === 'scheduled';
    if (filter === 'live-locked') return match.status === 'live' || match.status === 'locked';
    if (filter === 'completed') return match.status === 'completed';
    return true;
  });

  const visibleDirtyMatches = filteredMatches.filter((match) => {
    const values = getPredictionValues(predByMatch[match.id], local[match.id]);
    return canEdit(match.status) && local[match.id]?.dirty && values.home !== '' && values.away !== '';
  });
  const visibleSavingAny = filteredMatches.some((match) => local[match.id]?.saving);

  const sections = new Map<string, MatchResponse[]>();
  for (const match of filteredMatches) {
    const key = getDateHeading(match, timezone);
    const bucket = sections.get(key) ?? [];
    bucket.push(match);
    sections.set(key, bucket);
  }

  const isLoading = matchesLoading || predsLoading;

  return (
    <div>
      <PageHeader title="My Predictions" eyebrow="All matches" />
      <PredictionsSubNav />
      <ScoringGuide storageKey="sss_scoring_guide_predict_all_open" defaultOpen={false} />

      {isLoading && (
        <div className="space-y-4" aria-label="Loading predictions">
          <div className="flex flex-wrap gap-1.5">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-8 w-24 rounded-full" />
            ))}
          </div>
          <Skeleton className="h-[280px] w-full rounded-lg" />
        </div>
      )}

      {!isLoading && matches.length === 0 && (
        <EmptyState
          title="No matches available yet"
          description="Predictions will appear here once the fixture list is ready."
        />
      )}

      {!isLoading && matches.length > 0 && (
        <>
          <nav className="-mx-4 sm:-mx-0 mb-5 overflow-x-auto" aria-label="Prediction filters">
            <div className="flex gap-1.5 px-4 sm:px-0 min-w-max">
              {FILTERS.map((item) => (
                <button
                  key={item.value}
                  type="button"
                  onClick={() => setFilter(item.value)}
                  aria-pressed={filter === item.value}
                  className={cn(
                    'inline-flex items-center px-3.5 py-1.5 rounded-full text-xs font-medium font-sans whitespace-nowrap transition-colors press-down focus-visible:outline-none focus-visible:shadow-glow',
                    filter === item.value
                      ? 'bg-primary/15 text-primary border border-primary/30'
                      : 'bg-surface text-text-secondary hover:bg-surface-elevated border border-border',
                  )}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </nav>

          <div className="mb-5 flex items-center justify-between gap-3">
            <p className="text-sm text-text-muted">
              {filteredMatches.length} {filteredMatches.length === 1 ? 'match' : 'matches'} in view
            </p>
            <Button
              size="sm"
              onClick={() => handleSaveAll(filteredMatches)}
              disabled={visibleSavingAny || visibleDirtyMatches.length === 0}
            >
              {visibleSavingAny ? 'Saving…' : 'Save visible changes'}
            </Button>
          </div>

          {filteredMatches.length === 0 ? (
            <EmptyState
              title="Nothing in this view right now"
              description="Try a different filter to see more matches."
            />
          ) : (
            <div className="flex flex-col gap-6">
              {Array.from(sections.entries()).map(([heading, sectionMatches]) => (
                <section key={heading}>
                  <div className="sticky top-14 z-10 -mx-4 sm:-mx-0 mb-2 bg-surface-elevated/95 px-4 py-2 backdrop-blur-sm sm:px-0">
                    <h2 className="text-[10px] font-mono uppercase tracking-[0.25em] text-text-muted">
                      {heading}
                    </h2>
                  </div>
                  <div className="flex flex-col gap-4">
                    {sectionMatches.map((match) => (
                      <div key={match.id} className="space-y-2">
                        <div className="flex items-center justify-between gap-3 px-0.5">
                          <div className="flex min-w-0 items-center gap-2">
                            <Badge variant={match.stage === 'group' ? 'muted' : 'default'}>
                              {getSectionLabel(match)}
                            </Badge>
                            {match.venue && (
                              <span className="truncate text-xs text-text-muted">{match.venue}</span>
                            )}
                          </div>
                          <span className="shrink-0 font-mono text-[10px] uppercase tracking-[0.2em] text-text-muted">
                            M{match.match_number}
                          </span>
                        </div>
                        <PredictionCard
                          match={match}
                          prediction={predByMatch[match.id]}
                          local={local[match.id]}
                          timezone={timezone}
                          highlighted={highlightedMatchIds.has(match.id)}
                          onHomeChange={handleHomeChange}
                          onAwayChange={handleAwayChange}
                        />
                      </div>
                    ))}
                  </div>
                </section>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
