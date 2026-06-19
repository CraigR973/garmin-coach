import { useEffect } from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { formatInTimeZone } from 'date-fns-tz';
import { apiFetch } from '../lib/api';
import { useAuth } from '../contexts/AuthContext';
import type { GroupResponse, MatchResponse } from '../lib/types';
import { supabase } from '../lib/supabase';
import { Skeleton } from '../components/ui/skeleton';
import { Button } from '../components/ui/button';
import { EmptyState } from '../components/EmptyState';
import { PageHeader } from '../components/PageHeader';

// Returns true when no match in the group has been completed yet
function isPreTournament(group: GroupResponse): boolean {
  return group.standings.every((s) => s.played === 0);
}

function PreTournamentCard({
  group,
  groupMatches,
  timezone,
}: {
  group: GroupResponse;
  groupMatches: MatchResponse[];
  timezone: string;
}) {
  const scheduled = groupMatches
    .filter((m) => m.group_id === group.id && m.status === 'scheduled')
    .sort((a, b) => a.kickoff_utc.localeCompare(b.kickoff_utc));

  const first = scheduled[0] ?? null;

  return (
    <div className="rounded-lg border border-border bg-surface overflow-hidden">
      <div className="px-4 py-2 border-b border-border flex items-center justify-between">
        <h2 className="text-base font-semibold text-text-primary font-sans tracking-tight">
          Group {group.name}
        </h2>
        <Link
          to={`/groups/${group.name}`}
          className="text-xs text-text-muted hover:text-primary font-sans transition-colors"
        >
          Details →
        </Link>
      </div>

      {first ? (
        <div className="px-4 py-3">
          <p className="text-[10px] font-mono text-text-muted uppercase tracking-widest mb-2">
            First match
          </p>
          <div className="flex items-center gap-3">
            <span className="text-sm font-mono text-text-primary tabular-nums shrink-0">
              {formatInTimeZone(new Date(first.kickoff_utc), timezone, 'EEE d MMM, HH:mm')}
            </span>
            <span className="flex-1 text-sm text-text-secondary font-sans text-center">
              {first.home_team
                ? `${first.home_team.flag_emoji} ${first.home_team.name}`
                : (first.home_team_placeholder ?? '?')}
            </span>
            <span className="text-xs font-mono text-text-muted shrink-0">vs</span>
            <span className="flex-1 text-sm text-text-secondary font-sans text-center">
              {first.away_team
                ? `${first.away_team.flag_emoji} ${first.away_team.name}`
                : (first.away_team_placeholder ?? '?')}
            </span>
          </div>
        </div>
      ) : (
        <p className="px-4 py-3 text-xs text-text-muted font-sans">No matches scheduled yet.</p>
      )}

      {/* Ghost standings — teams visible but no stats */}
      <table className="w-full text-sm font-sans border-t border-border">
        <tbody>
          {group.standings.map((s) => (
            <tr
              key={s.team_id}
              className="border-b border-border/50 last:border-0"
            >
              <td className="py-1.5 pl-4 text-text-muted w-6">{s.position}</td>
              <td className="py-1.5">
                <span className="mr-1.5">{s.flag_emoji}</span>
                <span className="text-text-secondary">{s.team_name}</span>
              </td>
              <td className="py-1.5 pr-4 text-right text-text-muted text-xs font-mono">
                TBD
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function StandingsTable({ group }: { group: GroupResponse }) {
  return (
    <div className="rounded-lg border border-border bg-surface overflow-hidden">
      <div className="px-4 py-2 border-b border-border flex items-center justify-between">
        <h2 className="text-base font-semibold text-text-primary font-sans tracking-tight">
          Group {group.name}
        </h2>
        <Link
          to={`/groups/${group.name}`}
          className="text-xs text-text-muted hover:text-primary font-sans transition-colors"
        >
          Details →
        </Link>
      </div>
      <table className="w-full text-sm font-sans">
        <thead>
          <tr className="border-b border-border text-text-muted text-xs">
            <th className="py-2 pl-4 text-left w-6">#</th>
            <th className="py-2 text-left">Team</th>
            <th className="py-2 text-center w-8">P</th>
            <th className="py-2 text-center w-8">W</th>
            <th className="py-2 text-center w-8">D</th>
            <th className="py-2 text-center w-8">L</th>
            <th className="py-2 text-center w-10">GD</th>
            <th className="py-2 pr-4 text-center w-10 font-semibold">Pts</th>
          </tr>
        </thead>
        <tbody>
          {group.standings.map((s) => (
            <tr
              key={s.team_id}
              className="border-b border-border/50 last:border-0 hover:bg-surface-elevated transition-colors"
            >
              <td className="py-2 pl-4 text-text-muted">{s.position}</td>
              <td className="py-2">
                <span className="mr-1.5">{s.flag_emoji}</span>
                <span className="text-text-primary">{s.team_code}</span>
                <span className="text-text-muted ml-1 hidden sm:inline">{s.team_name}</span>
              </td>
              <td className="py-2 text-center text-text-secondary">{s.played}</td>
              <td className="py-2 text-center text-text-secondary">{s.won}</td>
              <td className="py-2 text-center text-text-secondary">{s.drawn}</td>
              <td className="py-2 text-center text-text-secondary">{s.lost}</td>
              <td className="py-2 text-center text-text-secondary">
                {s.gd > 0 ? `+${s.gd}` : s.gd}
              </td>
              <td className="py-2 pr-4 text-center font-semibold text-text-primary">
                {s.points}
              </td>
            </tr>
          ))}
          {group.standings.length === 0 && (
            <tr>
              <td colSpan={8} className="py-4 text-center text-text-muted text-xs">
                No results yet
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

export function GroupsPage() {
  const queryClient = useQueryClient();
  const { player } = useAuth();
  const timezone = player?.timezone ?? 'UTC';

  const { data, isLoading, error, refetch, isRefetching } = useQuery<GroupResponse[]>({
    queryKey: ['groups'],
    queryFn: () => apiFetch<GroupResponse[]>('/api/v1/groups'),
    staleTime: 30_000,
  });

  const { data: groupMatches = [] } = useQuery<MatchResponse[]>({
    queryKey: ['matches', 'group'],
    queryFn: () => apiFetch<MatchResponse[]>('/api/v1/matches?stage=group'),
    staleTime: 30_000,
  });

  // Supabase Realtime: invalidate groups query when any match is updated
  useEffect(() => {
    const channel = supabase
      .channel('matches-changes')
      .on(
        'postgres_changes',
        { event: '*', schema: 'public', table: 'matches' },
        () => {
          queryClient.invalidateQueries({ queryKey: ['groups'] });
          queryClient.invalidateQueries({ queryKey: ['matches', 'group'] });
        },
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [queryClient]);

  return (
    <div>
      <PageHeader title="Groups" eyebrow="Standings" />

      {isLoading && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4" aria-label="Loading group standings">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-[260px] w-full" />
          ))}
        </div>
      )}
      {error && (
        <EmptyState
          title="Couldn't load groups"
          description="There was a problem reaching the server. Try again in a moment."
          action={
            <Button variant="outline" size="sm" disabled={isRefetching} onClick={() => refetch()}>
              {isRefetching ? 'Retrying…' : 'Try again'}
            </Button>
          }
        />
      )}

      {!isLoading && !error && (data ?? []).length === 0 && (
        <EmptyState
          title="No groups configured"
          description="Group standings will appear once the draw is finalised."
        />
      )}

      {!isLoading && (data ?? []).length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {(data ?? []).map((group) =>
            isPreTournament(group) ? (
              <PreTournamentCard
                key={group.id}
                group={group}
                groupMatches={groupMatches}
                timezone={timezone}
              />
            ) : (
              <StandingsTable key={group.id} group={group} />
            ),
          )}
        </div>
      )}
    </div>
  );
}
