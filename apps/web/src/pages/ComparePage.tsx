import { useEffect, useMemo } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { apiFetch, DEFAULT_LEAGUE_SLUG } from '../lib/api';
import { useAuth } from '../contexts/AuthContext';
import { cn } from '../lib/utils';
import { Skeleton } from '../components/ui/skeleton';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { EmptyState } from '../components/EmptyState';
import { PageHeader } from '../components/PageHeader';
import type { H2HMatchEntry, H2HResponse, PlayerListItem } from '../lib/types';

const STAGE_LABEL: Record<string, string> = {
  group: 'Group',
  r32: 'R32',
  r16: 'R16',
  qf: 'QF',
  sf: 'SF',
  third_place: '3rd',
  final: 'Final',
};

function formatPick(home: number | null, away: number | null): string {
  if (home === null || away === null) return '—';
  return `${home}–${away}`;
}

function formatActual(home: number | null, away: number | null): string {
  if (home === null || away === null) return '—';
  return `${home}–${away}`;
}

function PlayerPicker({
  label,
  value,
  onChange,
  players,
  excludeId,
}: {
  label: string;
  value: string;
  onChange: (id: string) => void;
  players: PlayerListItem[];
  excludeId?: string;
}) {
  return (
    <div className="flex flex-col gap-1 flex-1 min-w-0">
      <span className="text-xs text-text-muted font-sans uppercase tracking-wide">{label}</span>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger aria-label={label}>
          <SelectValue placeholder="Select player…" />
        </SelectTrigger>
        <SelectContent>
          {players
            .filter((p) => p.id !== excludeId)
            .map((p) => (
              <SelectItem key={p.id} value={p.id}>
                {p.display_name}
                {p.is_deleted ? ' (inactive)' : ''}
              </SelectItem>
            ))}
        </SelectContent>
      </Select>
    </div>
  );
}

function SummaryBar({
  nameA,
  nameB,
  winsA,
  winsB,
  draws,
}: {
  nameA: string;
  nameB: string;
  winsA: number;
  winsB: number;
  draws: number;
}) {
  return (
    <div className="rounded-lg border border-border bg-surface overflow-hidden">
      <div className="grid grid-cols-3 text-center">
        <div className="py-4 border-r border-border">
          <p className="text-xs text-text-muted font-sans uppercase tracking-wide truncate px-2">
            {nameA}
          </p>
          <p className="font-display text-3xl text-primary mt-1">{winsA}</p>
          <p className="text-[10px] text-text-muted font-sans uppercase">wins</p>
        </div>
        <div className="py-4 border-r border-border">
          <p className="text-xs text-text-muted font-sans uppercase tracking-wide">Draws</p>
          <p className="font-display text-3xl text-text-secondary mt-1">{draws}</p>
          <p className="text-[10px] text-text-muted font-sans uppercase">level</p>
        </div>
        <div className="py-4">
          <p className="text-xs text-text-muted font-sans uppercase tracking-wide truncate px-2">
            {nameB}
          </p>
          <p className="font-display text-3xl text-primary mt-1">{winsB}</p>
          <p className="text-[10px] text-text-muted font-sans uppercase">wins</p>
        </div>
      </div>
    </div>
  );
}

function MatchRow({ m }: { m: H2HMatchEntry }) {
  const aWin = m.winner === 'a';
  const bWin = m.winner === 'b';
  return (
    <tr className="border-b border-border/50 last:border-0">
      <td className="py-2 pl-3 align-top">
        <span className="text-[10px] text-text-muted font-mono uppercase tracking-wide">
          {STAGE_LABEL[m.stage] ?? m.stage}
        </span>
        <div className="text-text-primary mt-0.5 text-sm leading-tight">
          {m.home_team_flag ?? ''} {m.home_team_name ?? '?'}
          <span className="text-text-muted"> v </span>
          {m.away_team_flag ?? ''} {m.away_team_name ?? '?'}
        </div>
        <div className="text-text-muted text-[11px] font-mono mt-0.5">
          actual {formatActual(m.actual_home, m.actual_away)}
        </div>
      </td>
      <td
        className={cn(
          'py-2 px-2 text-center align-top',
          aWin && 'bg-primary/10',
        )}
        data-testid="player-a-cell"
      >
        <div className="font-mono text-sm text-text-primary">
          {formatPick(m.player_a_predicted_home, m.player_a_predicted_away)}
        </div>
        <div
          className={cn(
            'font-bold text-base mt-0.5',
            aWin ? 'text-primary' : 'text-text-secondary',
          )}
        >
          {m.player_a_points}
          <span className="text-[10px] text-text-muted ml-1 font-sans">pts</span>
        </div>
      </td>
      <td
        className={cn(
          'py-2 px-2 text-center align-top',
          bWin && 'bg-primary/10',
        )}
        data-testid="player-b-cell"
      >
        <div className="font-mono text-sm text-text-primary">
          {formatPick(m.player_b_predicted_home, m.player_b_predicted_away)}
        </div>
        <div
          className={cn(
            'font-bold text-base mt-0.5',
            bWin ? 'text-primary' : 'text-text-secondary',
          )}
        >
          {m.player_b_points}
          <span className="text-[10px] text-text-muted ml-1 font-sans">pts</span>
        </div>
      </td>
      <td className="py-2 pr-3 text-center align-top text-text-muted text-xs font-mono">
        {m.winner === 'draw' ? '=' : m.winner === 'a' ? '◀' : '▶'}
      </td>
    </tr>
  );
}

export function ComparePage() {
  const { player: currentUser } = useAuth();
  const { slug = DEFAULT_LEAGUE_SLUG } = useParams<{ slug: string }>();
  const leagueSlug = slug;
  const [searchParams, setSearchParams] = useSearchParams();

  const a = searchParams.get('a') ?? '';
  const b = searchParams.get('b') ?? '';

  // On first load, default A to current user if neither is set.
  useEffect(() => {
    if (!a && !b && currentUser?.id) {
      setSearchParams({ a: currentUser.id }, { replace: true });
    }
  }, [a, b, currentUser?.id, setSearchParams]);

  const { data: players = [], isLoading: playersLoading } = useQuery<PlayerListItem[]>({
    queryKey: ['players', leagueSlug],
    queryFn: () => apiFetch<PlayerListItem[]>(`/api/v1/leagues/${leagueSlug}/players`),
  });

  const setA = (id: string) => {
    const next = new URLSearchParams(searchParams);
    if (id) next.set('a', id);
    else next.delete('a');
    setSearchParams(next, { replace: true });
  };
  const setB = (id: string) => {
    const next = new URLSearchParams(searchParams);
    if (id) next.set('b', id);
    else next.delete('b');
    setSearchParams(next, { replace: true });
  };
  const swap = () => {
    const next = new URLSearchParams(searchParams);
    if (a) next.set('a', b);
    else next.delete('a');
    if (b) next.set('b', a);
    else next.delete('b');
    setSearchParams(next, { replace: true });
  };

  const bothSelected = Boolean(a && b && a !== b);

  const { data: h2h, isLoading: h2hLoading, error: h2hError } = useQuery<H2HResponse>({
    queryKey: ['compare', leagueSlug, a, b],
    queryFn: () =>
      apiFetch<H2HResponse>(`/api/v1/leagues/${leagueSlug}/compare/${a}/${b}`),
    enabled: bothSelected,
  });

  const playerLookup = useMemo(
    () => Object.fromEntries(players.map((p) => [p.id, p.display_name] as const)),
    [players],
  );

  const nameA = h2h?.player_a.name ?? playerLookup[a] ?? 'Player A';
  const nameB = h2h?.player_b.name ?? playerLookup[b] ?? 'Player B';

  return (
    <div className="space-y-6">
      <PageHeader
        title="Head-to-Head"
        eyebrow="Compare"
        back={{ to: `/leagues/${leagueSlug}/leaderboard`, label: 'Leaderboard' }}
      />

      <p className="text-text-muted text-sm font-sans">
        Pick two players to compare match-by-match. Long-press a row on the leaderboard to
        compare them against you.
      </p>

      <div className="flex flex-col sm:flex-row items-end gap-3">
        <PlayerPicker
          label="Player A"
          value={a}
          onChange={setA}
          players={players}
          excludeId={b || undefined}
        />
        <button
          type="button"
          onClick={swap}
          disabled={!a && !b}
          aria-label="Swap players"
          className="h-10 px-3 rounded-md border border-border bg-surface text-text-muted hover:text-primary hover:border-primary transition-colors disabled:opacity-30 disabled:hover:text-text-muted disabled:hover:border-border font-sans text-sm"
        >
          ⇄
        </button>
        <PlayerPicker
          label="Player B"
          value={b}
          onChange={setB}
          players={players}
          excludeId={a || undefined}
        />
      </div>

      {playersLoading && (
        <Skeleton className="h-10 w-full" aria-label="Loading players" />
      )}

      {!bothSelected && !playersLoading && (
        <EmptyState
          title="Select two players"
          description="Choose players above, or long-press a row on the leaderboard to set the comparison against yourself."
        />
      )}

      {bothSelected && h2hLoading && (
        <div className="space-y-4" aria-label="Loading comparison">
          <Skeleton className="h-[120px] w-full" />
          <Skeleton className="h-[160px] w-full" />
        </div>
      )}

      {bothSelected && h2hError && (
        <EmptyState
          title="Couldn't load comparison"
          description="Refresh the page or try a different pair of players."
        />
      )}

      {bothSelected && h2h && (
        <>
          <SummaryBar
            nameA={nameA}
            nameB={nameB}
            winsA={h2h.summary.player_a_wins}
            winsB={h2h.summary.player_b_wins}
            draws={h2h.summary.draws}
          />

          {h2h.matches.length > 0 ? (
            <div className="rounded-lg border border-border bg-surface overflow-x-auto">
              <table className="w-full text-sm font-sans">
                <thead>
                  <tr className="border-b border-border text-text-muted text-xs">
                    <th className="py-2 pl-3 text-left">Match</th>
                    <th className="py-2 px-2 text-center max-w-[6rem] truncate">{nameA}</th>
                    <th className="py-2 px-2 text-center max-w-[6rem] truncate">{nameB}</th>
                    <th className="py-2 pr-3 text-center w-8"></th>
                  </tr>
                </thead>
                <tbody>
                  {h2h.matches.map((m) => (
                    <MatchRow key={m.match_id} m={m} />
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState
              title="No settled matches in common yet"
              description="The match-by-match table fills in as both players' predictions are settled."
            />
          )}
        </>
      )}
    </div>
  );
}
