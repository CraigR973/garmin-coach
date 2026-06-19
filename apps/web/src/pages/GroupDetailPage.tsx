import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { apiFetch } from '../lib/api';
import type { GroupResponse } from '../lib/types';
import { supabase } from '../lib/supabase';
import { Skeleton } from '../components/ui/skeleton';
import { EmptyState } from '../components/EmptyState';
import { PageHeader } from '../components/PageHeader';

export function GroupDetailPage() {
  const { name } = useParams<{ name: string }>();
  const queryClient = useQueryClient();
  const [showFull, setShowFull] = useState(false);

  const { data, isLoading, error } = useQuery<GroupResponse>({
    queryKey: ['group', name],
    queryFn: () => apiFetch<GroupResponse>(`/api/v1/groups/${name}`),
    staleTime: 30_000,
    enabled: !!name,
  });

  // Supabase Realtime: invalidate this group's query on any match change
  useEffect(() => {
    const channel = supabase
      .channel(`group-${name}-changes`)
      .on(
        'postgres_changes',
        { event: '*', schema: 'public', table: 'matches' },
        () => {
          queryClient.invalidateQueries({ queryKey: ['group', name] });
        },
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [name, queryClient]);

  if (isLoading) {
    return (
      <div>
        <Skeleton className="h-8 w-48 mb-6" />
        <Skeleton className="h-[280px] w-full" />
      </div>
    );
  }
  if (error || !data) {
    return (
      <EmptyState
        title="Group not found"
        description="This group either doesn't exist or couldn't be loaded."
        action={
          <Link to="/groups" className="text-primary text-sm font-sans hover:underline">
            ← Back to groups
          </Link>
        }
      />
    );
  }

  // Columns hidden on < 480 px by default; revealed by toggle or landscape mode.
  // min-[480px]:table-cell and [@media(orientation:landscape)]:table-cell make
  // them auto-visible when screen is wider or in landscape.
  const extendedColCls = showFull
    ? 'table-cell'
    : 'hidden min-[480px]:table-cell [@media(orientation:landscape)]:table-cell';

  return (
    <div>
      <PageHeader
        title={`Group ${data.name}`}
        eyebrow="Standings"
        back={{ to: '/groups', label: 'Groups' }}
      />

      <div className="rounded-lg border border-border bg-surface overflow-hidden">
        <table className="w-full text-sm font-sans">
          <thead>
            <tr className="border-b border-border text-text-muted text-xs bg-surface-elevated">
              <th className="py-3 pl-4 text-left w-8">#</th>
              <th className="py-3 text-left">Team</th>
              <th className="py-3 text-center w-10">P</th>
              <th className="py-3 text-center w-10">W</th>
              <th className="py-3 text-center w-10">D</th>
              <th className="py-3 text-center w-10">L</th>
              <th className={`py-3 text-center w-12 ${extendedColCls}`}>GF</th>
              <th className={`py-3 text-center w-12 ${extendedColCls}`}>GA</th>
              <th className={`py-3 text-center w-12 ${extendedColCls}`}>GD</th>
              <th className="py-3 pr-4 text-center w-12 font-semibold">Pts</th>
            </tr>
          </thead>
          <tbody>
            {data.standings.map((s, idx) => (
              <tr
                key={s.team_id}
                className={`border-b border-border/50 last:border-0 transition-colors hover:bg-surface-elevated ${
                  idx < 2 ? 'border-l-2 border-l-primary' : ''
                }`}
              >
                <td className="py-3 pl-4 text-text-muted font-mono">{s.position}</td>
                <td className="py-3">
                  <span className="mr-2 text-base">{s.flag_emoji}</span>
                  <span className="text-text-primary font-medium">{s.team_name}</span>
                </td>
                <td className="py-3 text-center text-text-secondary">{s.played}</td>
                <td className="py-3 text-center text-text-secondary">{s.won}</td>
                <td className="py-3 text-center text-text-secondary">{s.drawn}</td>
                <td className="py-3 text-center text-text-secondary">{s.lost}</td>
                <td className={`py-3 text-center text-text-secondary ${extendedColCls}`}>{s.gf}</td>
                <td className={`py-3 text-center text-text-secondary ${extendedColCls}`}>{s.ga}</td>
                <td className={`py-3 text-center text-text-secondary ${extendedColCls}`}>
                  {s.gd > 0 ? `+${s.gd}` : s.gd}
                </td>
                <td className="py-3 pr-4 text-center font-bold text-text-primary text-base">
                  {s.points}
                </td>
              </tr>
            ))}
            {data.standings.length === 0 && (
              <tr>
                <td colSpan={10} className="py-8 text-center text-text-muted text-sm">
                  No results yet — check back after matches are played.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {data.standings.length > 0 && (
        <p className="text-xs text-text-muted font-sans mt-3">
          Top 2 teams (highlighted) advance to the Round of 32.
        </p>
      )}

      {/* Show full stats toggle — only visible on small screens (portrait) */}
      <div className="mt-3 flex justify-center min-[480px]:hidden [@media(orientation:landscape)]:hidden">
        <button
          type="button"
          onClick={() => setShowFull((v) => !v)}
          className="text-xs font-sans text-text-muted hover:text-primary transition-colors"
        >
          {showFull ? 'Hide extra stats' : 'Show full stats'}
        </button>
      </div>
    </div>
  );
}
