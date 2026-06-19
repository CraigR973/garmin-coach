import { useNavigate, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { apiFetch, DEFAULT_LEAGUE_SLUG } from '../lib/api';
import type { RoundEntry } from '../lib/types';
import { Skeleton } from '../components/ui/skeleton';
import { Button } from '../components/ui/button';
import { EmptyState } from '../components/EmptyState';
import { PageHeader } from '../components/PageHeader';
import { Avatar } from '../components/ui/avatar';
import { cn } from '../lib/utils';

const STAGES = [
  { value: 'group', label: 'Group Stage' },
  { value: 'r32', label: 'Round of 32' },
  { value: 'r16', label: 'Round of 16' },
  { value: 'qf', label: 'Quarter-finals' },
  { value: 'sf', label: 'Semi-finals' },
  { value: 'third_place', label: 'Third Place' },
  { value: 'final', label: 'Final' },
];

const MEDAL: Record<number, string> = { 1: '🥇', 2: '🥈', 3: '🥉' };

function RoundTiebreakHeader() {
  return (
    <thead>
      <tr className="border-b border-border/60 text-[9px] font-mono uppercase tracking-[0.22em] text-text-muted">
        <th rowSpan={2} className="py-2.5 pl-3 sm:pl-4 text-left w-8 align-bottom">
          #
        </th>
        <th rowSpan={2} className="py-2.5 text-left align-bottom">
          Player
        </th>
        <th colSpan={3} className="px-1 text-center align-bottom">
          Tiebreakers
        </th>
        <th rowSpan={2} className="py-2.5 pr-3 sm:pr-4 text-center w-14 align-bottom">
          Pts
        </th>
      </tr>
      <tr className="border-b border-border text-[10px] font-mono uppercase tracking-[0.18em] text-text-muted">
        <th className="py-2 px-1.5 sm:px-2 text-center" title="Exact scores this round">
          Ex
        </th>
        <th className="py-2 px-1.5 sm:px-2 text-center" title="Correct results this round">
          Res
        </th>
        <th className="py-2 px-1.5 sm:px-2 text-center" title="Correct goal totals this round">
          Gls
        </th>
      </tr>
    </thead>
  );
}

export function RoundLeaderboardPage() {
  const { slug = DEFAULT_LEAGUE_SLUG, stage = 'group' } = useParams<{ slug: string; stage: string }>();
  const leagueSlug = slug;
  const navigate = useNavigate();

  const { data = [], isLoading, error, refetch, isRefetching } = useQuery<RoundEntry[]>({
    queryKey: ['leaderboard-round', leagueSlug, stage],
    queryFn: () =>
      apiFetch<RoundEntry[]>(
        `/api/v1/leagues/${leagueSlug}/leaderboard/round/${stage}`,
      ),
    staleTime: 30_000,
  });

  return (
    <div>
      <PageHeader
        title="Round Leaderboard"
        eyebrow="Standings"
        back={{ to: `/leagues/${leagueSlug}/leaderboard`, label: 'Overall' }}
      />

      {/* Stage pill scroller */}
      <nav className="-mx-4 sm:-mx-0 mb-5 overflow-x-auto" aria-label="Tournament stage">
        <div className="flex gap-1.5 px-4 sm:px-0 min-w-max">
          {STAGES.map((s) => {
            const active = stage === s.value;
            return (
              <button
                key={s.value}
                onClick={() => navigate(`/leagues/${leagueSlug}/leaderboard/round/${s.value}`)}
                className={cn(
                  'inline-flex items-center px-3.5 py-1.5 rounded-full text-xs font-medium font-sans whitespace-nowrap transition-colors press-down focus-visible:outline-none focus-visible:shadow-glow',
                  active
                    ? 'bg-primary/15 text-primary border border-primary/30'
                    : 'bg-surface text-text-secondary hover:bg-surface-elevated border border-border',
                )}
              >
                {s.label}
              </button>
            );
          })}
        </div>
      </nav>

      {isLoading ? (
        <div
          className="rounded-lg border border-border bg-surface overflow-hidden divide-y divide-border/50"
          aria-label="Loading round leaderboard"
        >
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="flex items-center gap-3 px-4 py-3">
              <Skeleton className="h-4 w-6" />
              <Skeleton className="h-4 flex-1 max-w-[160px]" />
              <Skeleton className="h-4 w-10" />
            </div>
          ))}
        </div>
      ) : error ? (
        <EmptyState
          title="Couldn't load round leaderboard"
          description="Refresh the page or check your connection."
          action={
            <Button variant="outline" size="sm" disabled={isRefetching} onClick={() => refetch()}>
              {isRefetching ? 'Retrying…' : 'Try again'}
            </Button>
          }
        />
      ) : data.length === 0 || data.every((e) => e.points === 0) ? (
        <EmptyState
          title="No points scored in this round yet"
          description="Once results are entered for this round, the per-round standings will appear here."
        />
      ) : (
        <div className="rounded-lg border border-border bg-surface overflow-hidden">
          <table className="w-full table-fixed text-sm font-sans">
            <RoundTiebreakHeader />
            <tbody>
              {data.map((entry) => (
                <tr
                  key={entry.player_id}
                  className="border-b border-border/50 last:border-0 hover:bg-surface-elevated transition-colors"
                >
                  <td className="py-3 pl-3 sm:pl-4 text-text-muted font-mono text-xs">
                    {MEDAL[entry.rank] ?? entry.rank}
                  </td>
                  <td className="py-3 min-w-0">
                    <div className="flex min-w-0 items-center gap-2">
                      <Avatar name={entry.player_name} size="sm" src={entry.avatar_url} className="shrink-0" />
                      <span className="truncate text-text-primary font-medium">
                        {entry.player_name}
                      </span>
                      {entry.tied && (
                        <span
                          className="shrink-0 text-[9px] font-mono uppercase tracking-[0.15em] text-amber-400 bg-amber-400/10 border border-amber-400/30 px-2 py-1 rounded-sm"
                          title="Level on every tiebreaker this round"
                        >
                          tied
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="py-3 px-1.5 sm:px-2 text-center font-mono text-[11px] text-text-secondary tabular-nums">
                    {entry.exact_count ?? 0}
                  </td>
                  <td className="py-3 px-1.5 sm:px-2 text-center font-mono text-[11px] text-text-secondary tabular-nums">
                    {entry.correct_result_count ?? 0}
                  </td>
                  <td className="py-3 px-1.5 sm:px-2 text-center font-mono text-[11px] text-text-secondary tabular-nums">
                    {entry.correct_goals_count ?? 0}
                  </td>
                  <td className="py-3 pr-3 sm:pr-4 text-center font-bold text-primary tabular-nums">
                    {entry.points}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
