import { Link, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Globe } from 'lucide-react';
import { apiFetch } from '../lib/api';
import type { LeaderboardEntry } from '../lib/types';
import { useAuth } from '../contexts/AuthContext';
import { Avatar } from '../components/ui/avatar';
import { Skeleton } from '../components/ui/skeleton';
import { Button } from '../components/ui/button';
import { EmptyState } from '../components/EmptyState';
import { PageHeader } from '../components/PageHeader';
import { cn } from '../lib/utils';

// ---------------------------------------------------------------------------
// Table sub-components (global-only; simpler than per-league — no rank arrows,
// no period toggle, no compare, no rank-shift pulse)
// ---------------------------------------------------------------------------

function TiebreakHeader() {
  return (
    <thead>
      <tr className="text-[9px] font-mono uppercase tracking-[0.22em] text-text-muted">
        <th rowSpan={2} className="py-2.5 pl-3 sm:pl-5 text-left w-7 align-bottom">#</th>
        <th rowSpan={2} className="py-2.5 pr-1 text-left align-bottom">Player</th>
        <th colSpan={3} className="px-0.5 sm:px-1 text-center align-bottom" />
        <th rowSpan={2} className="py-2.5 pr-3 sm:pr-5 pl-0.5 text-right w-12 align-bottom">Pts</th>
      </tr>
      <tr className="border-b border-border text-[10px] font-mono uppercase tracking-[0.18em] text-text-muted">
        <th className="w-[1%] whitespace-nowrap py-2 px-3 sm:px-4 text-right" title="Exact scores">Ex</th>
        <th className="w-[1%] whitespace-nowrap py-2 px-3 sm:px-4 text-right" title="Correct results">Res</th>
        <th className="w-[1%] whitespace-nowrap py-2 px-3 sm:px-4 text-right" title="Correct goal totals">Gls</th>
      </tr>
    </thead>
  );
}

function GlobalRow({
  entry,
  isMe,
  onOpenProfile,
}: {
  entry: LeaderboardEntry;
  isMe: boolean;
  onOpenProfile: () => void;
}) {
  return (
    <tr
      className={cn(
        'border-b border-border/50 last:border-0 cursor-pointer select-none',
        'hover:bg-surface-elevated transition-colors',
        isMe && 'bg-primary/10',
      )}
      onClick={onOpenProfile}
    >
      <td className="py-3.5 pl-3 sm:pl-5 w-7">
        <span className="text-text-muted font-mono text-sm tabular-nums">{entry.rank}</span>
      </td>
      <td className="py-3.5 pr-1 min-w-0">
        <div className="flex items-center gap-2 min-w-0">
          <Avatar name={entry.player_name} size="sm" src={entry.avatar_url} className="shrink-0" />
          <Link
            to={`/players/${entry.player_id}`}
            className={cn(
              'font-medium hover:text-primary transition-colors min-w-0 leading-tight whitespace-normal break-normal',
              isMe ? 'text-primary' : 'text-text-primary',
            )}
            onPointerDown={(e) => e.stopPropagation()}
            onClick={(e) => e.stopPropagation()}
          >
            {entry.player_name}
          </Link>
          {entry.tied && (
            <span className="text-[9px] font-mono uppercase tracking-[0.15em] text-amber-400 bg-amber-400/10 border border-amber-400/30 px-2 py-1 rounded-sm shrink-0">
              tied
            </span>
          )}
        </div>
      </td>
      <td className="w-[1%] whitespace-nowrap py-3.5 px-3 sm:px-4 text-right font-mono text-[11px] text-text-secondary tabular-nums">
        {entry.exact_count ?? 0}
      </td>
      <td className="w-[1%] whitespace-nowrap py-3.5 px-3 sm:px-4 text-right font-mono text-[11px] text-text-secondary tabular-nums">
        {entry.correct_result_count ?? 0}
      </td>
      <td className="w-[1%] whitespace-nowrap py-3.5 px-3 sm:px-4 text-right font-mono text-[11px] text-text-secondary tabular-nums">
        {entry.correct_goals_count ?? 0}
      </td>
      <td className="py-3.5 pr-3 sm:pr-5 pl-0.5 text-right font-mono text-base font-semibold text-primary tabular-nums w-12">
        {entry.total_points}
      </td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export function GlobalLeaderboardPage() {
  const navigate = useNavigate();
  const { player: currentUser } = useAuth();

  const { data = [], isLoading, error, refetch, isRefetching } = useQuery<LeaderboardEntry[]>({
    queryKey: ['leaderboard', 'global'],
    queryFn: () => apiFetch<LeaderboardEntry[]>('/api/v1/leaderboard/global'),
    staleTime: 30_000,
  });

  const myEntry = data.find((e) => e.player_id === currentUser?.id);

  if (isLoading) {
    return (
      <div>
        <div className="mb-5">
          <PageHeader
            title="Global Standings"
            eyebrow="All leagues"
            back={{ to: '/leagues', label: 'Leagues' }}
          />
        </div>
        <div className="rounded-lg border border-border bg-surface overflow-hidden divide-y divide-border/50" aria-label="Loading leaderboard">
          {Array.from({ length: 10 }).map((_, i) => (
            <div key={i} className="flex items-center gap-3 px-4 sm:px-5 py-3.5">
              <Skeleton className="h-4 w-6" />
              <Skeleton className="h-4 flex-1 max-w-[160px]" />
              <Skeleton className="h-4 w-10" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div>
        <PageHeader title="Global Standings" eyebrow="All leagues" back={{ to: '/leagues', label: 'Leagues' }} />
        <EmptyState
          title="Couldn't load global standings"
          description="Refresh the page or check your connection."
          action={
            <Button variant="outline" size="sm" disabled={isRefetching} onClick={() => refetch()}>
              {isRefetching ? 'Retrying…' : 'Try again'}
            </Button>
          }
        />
      </div>
    );
  }

  return (
    <div>
      <div className="mb-5">
        <PageHeader
          title="Global Standings"
          eyebrow="All leagues"
          back={{ to: '/leagues', label: 'Leagues' }}
          wrapTitle
          className="mb-0"
        />
        <p className="text-text-secondary font-sans text-sm mt-1">
          Every player across all leagues — {data.length} total.
        </p>
      </div>

      {/* "Your rank" callout — only shown when the player isn't in the top 10 */}
      {myEntry && myEntry.rank > 10 && (
        <div className="mb-4 flex items-center gap-3 rounded-lg border border-primary/30 bg-primary/5 px-4 py-3">
          <Globe className="h-4 w-4 text-primary shrink-0" aria-hidden />
          <span className="font-sans text-sm text-text-primary">
            You are ranked{' '}
            <span className="font-semibold text-primary">#{myEntry.rank}</span>
            {' '}of {data.length} globally with{' '}
            <span className="font-semibold text-primary">{myEntry.total_points} pts</span>
          </span>
        </div>
      )}

      {data.length === 0 ? (
        <EmptyState
          title="No results entered yet"
          description="The global leaderboard fills in as match results are confirmed."
        />
      ) : (
        <div className="rounded-lg border border-border bg-surface overflow-hidden">
          <table className="w-full table-fixed text-sm font-sans">
            <colgroup>
              <col className="w-8" />
              <col />
              <col className="w-7" />
              <col className="w-7" />
              <col className="w-7" />
              <col className="w-12" />
            </colgroup>
            <TiebreakHeader />
            <tbody>
              {data.map((entry) => (
                <GlobalRow
                  key={entry.player_id}
                  entry={entry}
                  isMe={entry.player_id === currentUser?.id}
                  onOpenProfile={() => navigate(`/players/${entry.player_id}`)}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
