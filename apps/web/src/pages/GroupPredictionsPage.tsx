import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { apiFetch } from '../lib/api';
import { useAuth } from '../contexts/AuthContext';
import type { MatchResponse, GroupResponse, PredictionResponse } from '../lib/types';
import { Button } from '../components/ui/button';
import { Skeleton } from '../components/ui/skeleton';
import { EmptyState } from '../components/EmptyState';
import { PageHeader } from '../components/PageHeader';
import { PredictionsSubNav } from '../components/PredictionsSubNav';
import { ScoringGuide } from '../components/ScoringGuide';
import { PredictionCard } from '../components/PredictionCard';
import { usePredictionEditor, type LocalPredictions } from '../hooks/usePredictionEditor';
import { canEdit } from '../lib/matchStatus';
import { setPredictionsDirty } from '../lib/dirtyState';
import { cn } from '../lib/utils';

const GROUP_MATCHES_QUERY_KEY = ['matches', 'group'] as const;

function GroupPanel({
  group,
  matches,
  predictions,
  local,
  timezone,
  highlightedMatchIds,
  onHomeChange,
  onAwayChange,
  onSaveAll,
}: {
  group: GroupResponse;
  matches: MatchResponse[];
  predictions: PredictionResponse[];
  local: LocalPredictions;
  timezone: string;
  highlightedMatchIds: Set<string>;
  onHomeChange: (matchId: string, value: string) => void;
  onAwayChange: (matchId: string, value: string) => void;
  onSaveAll: (groupMatches: MatchResponse[]) => void;
}) {
  const predByMatch = Object.fromEntries(predictions.map((p) => [p.match_id, p]));
  const groupMatches = matches.filter((m) => m.group_id === group.id);
  const dirtyCount = groupMatches.filter((m) => local[m.id]?.dirty).length;
  const savingAny = groupMatches.some((m) => local[m.id]?.saving);
  const editableMatches = groupMatches.filter((m) => canEdit(m.status));

  return (
    <div>
      <div className="flex flex-col gap-3">
        {groupMatches.length === 0 ? (
          <p className="text-text-muted font-sans text-sm">No matches for this group.</p>
        ) : (
          groupMatches.map((m) => (
            <PredictionCard
              key={m.id}
              match={m}
              prediction={predByMatch[m.id]}
              local={local[m.id]}
              timezone={timezone}
              highlighted={highlightedMatchIds.has(m.id)}
              onHomeChange={onHomeChange}
              onAwayChange={onAwayChange}
            />
          ))
        )}
      </div>

      {editableMatches.length > 0 && (
        <div className="mt-5 flex items-center justify-end gap-3">
          {dirtyCount > 0 && (
            <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-text-muted">
              {dirtyCount} unsaved {dirtyCount === 1 ? 'change' : 'changes'}
            </span>
          )}
          <Button
            size="sm"
            onClick={() => onSaveAll(editableMatches)}
            disabled={savingAny || dirtyCount === 0}
          >
            {savingAny ? 'Saving…' : `Save Group ${group.name}`}
          </Button>
        </div>
      )}
    </div>
  );
}

export function GroupPredictionsPage() {
  const { player } = useAuth();
  const timezone = player?.timezone ?? 'UTC';

  const [activeGroup, setActiveGroup] = useState(0);

  const { data: groups = [], isLoading: groupsLoading } = useQuery<GroupResponse[]>({
    queryKey: ['groups'],
    queryFn: () => apiFetch<GroupResponse[]>('/api/v1/groups'),
    staleTime: 60_000,
  });

  const { data: matches = [], isLoading: matchesLoading } = useQuery<MatchResponse[]>({
    queryKey: GROUP_MATCHES_QUERY_KEY,
    queryFn: () => apiFetch<MatchResponse[]>('/api/v1/matches?stage=group'),
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
      matchesQueryKey: GROUP_MATCHES_QUERY_KEY,
    });

  useEffect(() => {
    const totalDirty = matches.filter((m) => local[m.id]?.dirty).length;
    setPredictionsDirty(totalDirty > 0);
  }, [local, matches]);

  useEffect(() => () => setPredictionsDirty(false), []);

  const isLoading = groupsLoading || matchesLoading || predsLoading;
  const sortedGroups = [...groups].sort((a, b) => a.name.localeCompare(b.name));

  return (
    <div>
      <PageHeader title="My Predictions" eyebrow="Group stage" />
      <PredictionsSubNav />
      <ScoringGuide storageKey="sss_scoring_guide_predict_open" defaultOpen={false} />

      {isLoading && (
        <div className="space-y-4" aria-label="Loading predictions">
          <div className="flex flex-wrap gap-1.5 pb-3">
            {Array.from({ length: 8 }).map((_, i) => (
              <Skeleton key={i} className="h-8 w-20 rounded-full" />
            ))}
          </div>
          <Skeleton className="h-[260px] w-full rounded-lg" />
        </div>
      )}

      {!isLoading && sortedGroups.length === 0 && (
        <EmptyState
          title="No groups available yet"
          description="Predictions open once the group draw is finalised and matches are scheduled."
        />
      )}

      {!isLoading && sortedGroups.length > 0 && (
        <>
          <nav
            className="-mx-4 sm:-mx-0 mb-5 overflow-x-auto"
            role="tablist"
            aria-label="Tournament groups"
          >
            <div className="flex gap-1.5 px-4 sm:px-0 min-w-max">
              {sortedGroups.map((g, i) => {
                const active = activeGroup === i;
                return (
                  <button
                    key={g.id}
                    role="tab"
                    aria-selected={active}
                    aria-label={`Group ${g.name}`}
                    onClick={() => setActiveGroup(i)}
                    className={cn(
                      'inline-flex items-center px-3.5 py-1.5 rounded-full text-xs font-medium font-sans whitespace-nowrap transition-colors press-down focus-visible:outline-none focus-visible:shadow-glow',
                      active
                        ? 'bg-primary/15 text-primary border border-primary/30'
                        : 'bg-surface text-text-secondary hover:bg-surface-elevated border border-border',
                    )}
                  >
                    Group {g.name}
                  </button>
                );
              })}
            </div>
          </nav>

          {sortedGroups[activeGroup] && (
            <GroupPanel
              group={sortedGroups[activeGroup]}
              matches={matches}
              predictions={predictions}
              local={local}
              timezone={timezone}
              highlightedMatchIds={highlightedMatchIds}
              onHomeChange={handleHomeChange}
              onAwayChange={handleAwayChange}
              onSaveAll={handleSaveAll}
            />
          )}
        </>
      )}
    </div>
  );
}
