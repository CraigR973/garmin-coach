import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { apiFetch, DEFAULT_LEAGUE_SLUG } from '../lib/api';
import type { HistoryEntry } from '../lib/types';
import { Skeleton } from '../components/ui/skeleton';
import { Button } from '../components/ui/button';
import { EmptyState } from '../components/EmptyState';
import { PageHeader } from '../components/PageHeader';

// Distinct palette for up to 15 players. Primary green (#10B981/#22C55E)
// is reserved for brand surfaces, so player chips avoid the green band
// entirely — swapped in two slate neutrals instead.
const PALETTE = [
  '#94a3b8', '#3b82f6', '#f59e0b', '#ef4444', '#8b5cf6',
  '#06b6d4', '#ec4899', '#f97316', '#cbd5e1', '#a855f7',
  '#84cc16', '#0ea5e9', '#fb923c', '#d946ef', '#64748b',
];

type ChartPoint = { label: string; [playerName: string]: number | string };

function buildChartData(players: HistoryEntry[]): ChartPoint[] {
  // Collect all unique snapshot times in order
  const timesSet = new Set<string>();
  for (const p of players) {
    for (const s of p.snapshots) timesSet.add(s.snapshot_at);
  }
  const times = Array.from(timesSet).sort();

  // Build one data point per snapshot time
  return times.map((t, i) => {
    const point: ChartPoint = { label: `#${i + 1}` };
    for (const p of players) {
      const snap = p.snapshots.find((s) => s.snapshot_at === t);
      if (snap !== undefined) {
        point[p.player_name] = snap.rank;
      }
    }
    return point;
  });
}

export function LeaderboardHistoryPage() {
  const { slug = DEFAULT_LEAGUE_SLUG } = useParams<{ slug: string }>();
  const leagueSlug = slug;

  const { data = [], isLoading, error, refetch, isRefetching } = useQuery<HistoryEntry[]>({
    queryKey: ['leaderboard-history', leagueSlug],
    queryFn: () =>
      apiFetch<HistoryEntry[]>(`/api/v1/leagues/${leagueSlug}/leaderboard/history`),
    staleTime: 60_000,
  });

  const allNames = data.map((p) => p.player_name);
  const [hidden, setHidden] = useState<Set<string>>(new Set());

  function togglePlayer(name: string) {
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(name)) { next.delete(name); } else { next.add(name); }
      return next;
    });
  }

  const visibleData = data.filter((p) => !hidden.has(p.player_name));
  const chartData = buildChartData(visibleData);

  if (isLoading) {
    return (
      <div>
        <Skeleton className="h-8 w-48 mb-6" />
        <div className="flex flex-wrap gap-2 mb-6">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-7 w-20 rounded-full" />
          ))}
        </div>
        <Skeleton className="h-[380px] w-full" />
      </div>
    );
  }

  if (error) {
    return (
      <EmptyState
        title="Couldn't load rank history"
        description="There was a problem reaching the server. Refresh to try again."
        action={
          <Button variant="outline" size="sm" disabled={isRefetching} onClick={() => refetch()}>
            {isRefetching ? 'Retrying…' : 'Try again'}
          </Button>
        }
      />
    );
  }

  return (
    <div>
      <PageHeader
        title="Rank History"
        eyebrow="Standings"
        back={{ to: `/leagues/${leagueSlug}/leaderboard`, label: 'Leaderboard' }}
      />

      {data.length === 0 ? (
        <EmptyState
          title="No rank history yet"
          description="History will appear once the first match result is entered."
        />
      ) : (
        <>
          {/* Player toggle chips */}
          <div className="flex flex-wrap gap-2 mb-6">
            {allNames.map((name, i) => {
              const color = PALETTE[i % PALETTE.length];
              const isHidden = hidden.has(name);
              return (
                <button
                  key={name}
                  onClick={() => togglePlayer(name)}
                  className="px-3 py-1 rounded-full text-xs font-sans font-medium border transition-opacity"
                  style={{
                    borderColor: color,
                    color: isHidden ? '#6b7280' : color,
                    backgroundColor: isHidden ? 'transparent' : `${color}22`,
                    opacity: isHidden ? 0.5 : 1,
                  }}
                >
                  {name}
                </button>
              );
            })}
          </div>

          {/* Recharts line chart */}
          <div className="rounded-lg border border-border bg-surface p-4">
            <ResponsiveContainer width="100%" height={380}>
              <LineChart data={chartData} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis
                  dataKey="label"
                  tick={{ fill: '#94a3b8', fontSize: 11 }}
                  label={{
                    value: 'Result',
                    position: 'insideBottom',
                    offset: -4,
                    fill: '#94a3b8',
                    fontSize: 11,
                  }}
                />
                <YAxis
                  reversed
                  allowDecimals={false}
                  tick={{ fill: '#94a3b8', fontSize: 11 }}
                  label={{
                    value: 'Rank',
                    angle: -90,
                    position: 'insideLeft',
                    fill: '#94a3b8',
                    fontSize: 11,
                  }}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#0f172a',
                    borderColor: '#1e293b',
                    color: '#e2e8f0',
                    fontSize: 12,
                  }}
                  formatter={(value, name) => [`Rank ${value ?? '?'}`, String(name ?? '')]}
                />
                <Legend
                  wrapperStyle={{ fontSize: 11, color: '#94a3b8' }}
                  formatter={(value) => (
                    <span style={{ color: hidden.has(value) ? '#4b5563' : '#94a3b8' }}>
                      {value}
                    </span>
                  )}
                />
                {visibleData.map((player) => (
                  <Line
                    key={player.player_id}
                    type="monotone"
                    dataKey={player.player_name}
                    stroke={PALETTE[allNames.indexOf(player.player_name) % PALETTE.length]}
                    strokeWidth={2}
                    dot={{ r: 3 }}
                    activeDot={{ r: 5 }}
                    connectNulls={false}
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>

          <p className="text-text-muted text-xs font-sans mt-3 text-center">
            Each point = one match result. Lower rank = better position.
          </p>
        </>
      )}
    </div>
  );
}
