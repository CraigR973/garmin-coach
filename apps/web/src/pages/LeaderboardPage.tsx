import { useEffect, useRef, useState } from 'react';
import { Link, NavLink, useNavigate, useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { motion, useReducedMotionConfig } from 'framer-motion';
import { TrendingUp, TrendingDown, Minus, Share2, X } from 'lucide-react';
import { apiFetch, DEFAULT_LEAGUE_SLUG } from '../lib/api';
import type { LeaderboardEntry, LeagueDetail } from '../lib/types';
import { supabase } from '../lib/supabase';
import { useAuth } from '../contexts/AuthContext';
import { useLongPress } from '../hooks/useLongPress';
import { rankByPeriod, type LeaderboardPeriod, withLeagueRoster } from '../lib/leaderboard';
import { Skeleton } from '../components/ui/skeleton';
import { Button } from '../components/ui/button';
import { EmptyState } from '../components/EmptyState';
import { PageHeader } from '../components/PageHeader';
import { Avatar } from '../components/ui/avatar';
import { buildInviteMessage, shareInvite } from '../lib/invite';
import { LeagueActionsMenu } from '../components/LeagueActionsMenu';
import { toast } from 'sonner';
import { cn } from '../lib/utils';

const HINT_DISMISSED_KEY = 'sss_leaderboard_hint_dismissed';

function shortenName(name: string): string {
  const parts = name.trim().split(/\s+/);
  if (parts.length <= 1) return name;
  return `${parts[0]} ${parts[parts.length - 1][0]}.`;
}

interface RankDelta {
  direction: 'up' | 'down' | 'flat';
  delta: number;
}

function rankDelta(prev: number | undefined, curr: number): RankDelta {
  if (prev === undefined || prev === curr) return { direction: 'flat', delta: 0 };
  return prev > curr
    ? { direction: 'up', delta: prev - curr }
    : { direction: 'down', delta: curr - prev };
}

function ArrowGlyph({
  rank,
  shouldPulse,
  reduceMotion,
}: {
  rank: RankDelta;
  shouldPulse: boolean;
  reduceMotion: boolean;
}) {
  const cls =
    rank.direction === 'up'
      ? 'text-success'
      : rank.direction === 'down'
        ? 'text-error'
        : 'text-text-muted';
  const Icon =
    rank.direction === 'up' ? TrendingUp : rank.direction === 'down' ? TrendingDown : Minus;
  const label =
    rank.direction === 'flat'
      ? 'No change'
      : rank.direction === 'up'
        ? `Up ${rank.delta}`
        : `Down ${rank.delta}`;

  // U5.3: pulse on rank change. `shouldPulse` is true only when prevRank
  // existed AND differs from current rank — never on initial mount. Pulse
  // is suppressed entirely under reduced motion.
  const pulse = shouldPulse && !reduceMotion;

  return (
    <motion.span
      className={cn('inline-flex items-center gap-1 shrink-0', cls)}
      aria-label={label}
      data-testid="rank-arrow"
      data-pulsing={pulse ? 'true' : 'false'}
      initial={false}
      animate={
        pulse
          ? { scale: [1, 1.25, 1], filter: ['brightness(1)', 'brightness(1.4)', 'brightness(1)'] }
          : { scale: 1, filter: 'brightness(1)' }
      }
      transition={{ duration: 0.24, ease: 'easeOut' }}
    >
      <Icon className="h-3.5 w-3.5" aria-hidden />
      {rank.delta > 0 && (
        <span className="font-mono text-[10px] tabular-nums">{rank.delta}</span>
      )}
    </motion.span>
  );
}

interface RowProps {
  entry: LeaderboardEntry;
  displayPoints: number;
  showArrow: boolean;
  prevRank: number | undefined;
  isMe: boolean;
  reduceMotion: boolean;
  shouldPulse: boolean;
  onOpenProfile: () => void;
  onLongPress: () => void;
}

function TiebreakHeader({
  pointsLabel,
}: {
  pointsLabel: string;
}) {
  return (
    <thead>
      <tr className="text-[9px] font-mono uppercase tracking-[0.22em] text-text-muted">
        <th rowSpan={2} className="py-2.5 pl-3 sm:pl-5 text-left w-7 align-bottom">
          #
        </th>
        <th rowSpan={2} className="py-2.5 pr-1 text-left align-bottom">
          Player
        </th>
        <th colSpan={3} className="px-0.5 sm:px-1 text-center align-bottom" />
        <th rowSpan={2} className="py-2.5 pr-3 sm:pr-5 pl-0.5 text-right w-12 align-bottom">
          {pointsLabel}
        </th>
      </tr>
      <tr className="border-b border-border text-[10px] font-mono uppercase tracking-[0.18em] text-text-muted">
        <th className="w-[1%] whitespace-nowrap py-2 px-3 sm:px-4 text-right" title="Exact scores">
          Ex
        </th>
        <th className="w-[1%] whitespace-nowrap py-2 px-3 sm:px-4 text-right" title="Correct results">
          Res
        </th>
        <th className="w-[1%] whitespace-nowrap py-2 px-3 sm:px-4 text-right" title="Correct goal totals">
          Gls
        </th>
      </tr>
    </thead>
  );
}

function LeaderboardRow({
  entry,
  displayPoints,
  showArrow,
  prevRank,
  isMe,
  reduceMotion,
  shouldPulse,
  onOpenProfile,
  onLongPress,
}: RowProps) {
  const rd = rankDelta(prevRank, entry.rank);
  const handlers = useLongPress({ onLongPress, onClick: onOpenProfile });

  return (
    <motion.tr
      layout={!reduceMotion}
      transition={{ type: 'spring', stiffness: 320, damping: 28 }}
      data-testid={`leaderboard-row-${entry.player_id}`}
      className={cn(
        'border-b border-border/50 last:border-0 cursor-pointer select-none',
        'hover:bg-surface-elevated transition-colors',
        isMe && 'bg-primary/10',
      )}
      {...handlers}
    >
      <td className="py-3.5 pl-3 sm:pl-5 w-7">
        <span className="text-text-muted font-mono text-sm tabular-nums">
          {entry.rank}
        </span>
      </td>
      <td className="py-3.5 pr-1 min-w-0">
        <div className="flex items-center gap-2 min-w-0">
          <Avatar name={entry.player_name} size="sm" src={entry.avatar_url} className="shrink-0" />
          {showArrow && (
            <span className="shrink-0">
              <ArrowGlyph rank={rd} shouldPulse={shouldPulse} reduceMotion={reduceMotion} />
            </span>
          )}
          <Link
            to={`/players/${entry.player_id}`}
            className={cn(
              'font-medium hover:text-primary transition-colors min-w-0 leading-tight whitespace-normal break-normal',
              isMe ? 'text-primary' : 'text-text-primary',
            )}
            onPointerDown={(e) => e.stopPropagation()}
            onClick={(e) => e.stopPropagation()}
          >
            {shortenName(entry.player_name)}
          </Link>
          {entry.tied && (
            <span
              className="text-[9px] font-mono uppercase tracking-[0.15em] text-amber-400 bg-amber-400/10 border border-amber-400/30 px-2 py-1 rounded-sm shrink-0"
              title="Level on every tiebreaker — awaiting admin settlement"
            >
              tied
            </span>
          )}
          {!entry.is_active && (
            <span className="text-[9px] font-mono uppercase tracking-[0.2em] text-text-muted bg-surface-elevated border border-border px-1.5 py-0.5 rounded-sm shrink-0">
              inactive
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
        {displayPoints}
      </td>
    </motion.tr>
  );
}

function SubNav({ slug }: { slug: string }) {
  const subNav = [
    { to: `/leagues/${slug}/leaderboard`, label: 'Overall', exact: true },
    { to: `/leagues/${slug}/leaderboard/round/group`, label: 'By round', exact: false },
    { to: `/leagues/${slug}/leaderboard/history`, label: 'History', exact: false },
    { to: `/leagues/${slug}/compare`, label: 'Compare', exact: false },
  ];
  return (
    <nav className="-mx-4 sm:-mx-0 mb-5 overflow-x-auto" aria-label="Leaderboard views">
      <div className="flex gap-1.5 px-4 sm:px-0 min-w-max">
        {subNav.map(({ to, label, exact }) => (
          <NavLink
            key={to}
            to={to}
            end={exact}
            className={({ isActive }) =>
              cn(
                'inline-flex items-center px-3.5 py-1.5 rounded-full text-xs font-medium font-sans whitespace-nowrap transition-colors press-down focus-visible:outline-none focus-visible:shadow-glow',
                isActive
                  ? 'bg-primary/15 text-primary border border-primary/30'
                  : 'bg-surface text-text-secondary hover:bg-surface-elevated border border-border',
              )
            }
          >
            {label}
          </NavLink>
        ))}
      </div>
    </nav>
  );
}

const PERIOD_LABELS: Record<LeaderboardPeriod, string> = {
  today: 'Today',
  round: 'Round',
  total: 'Total',
};

function periodPoints(entry: LeaderboardEntry, period: LeaderboardPeriod): number {
  if (period === 'today') return entry.today_points;
  if (period === 'round') return entry.round_points;
  return entry.total_points;
}

function PeriodToggle({
  period,
  onChange,
}: {
  period: LeaderboardPeriod;
  onChange: (p: LeaderboardPeriod) => void;
}) {
  return (
    <div
      role="tablist"
      aria-label="Points period"
      className="mb-4 inline-flex rounded-full border border-border bg-surface p-0.5 text-xs font-medium font-sans"
    >
      {(['today', 'round', 'total'] as const).map((p) => (
        <button
          key={p}
          type="button"
          role="tab"
          aria-selected={period === p}
          onClick={() => onChange(p)}
          className={cn(
            'px-3.5 py-1 rounded-full transition-colors press-down focus-visible:outline-none focus-visible:shadow-glow',
            period === p
              ? 'bg-primary/15 text-primary'
              : 'text-text-secondary hover:text-text-primary',
          )}
        >
          {PERIOD_LABELS[p]}
        </button>
      ))}
    </div>
  );
}

function LeagueLeaderboardHeader({ league, slug }: { league?: LeagueDetail; slug: string }) {
  const { player } = useAuth();
  const [shareStatus, setShareStatus] = useState<'idle' | 'copied'>('idle');

  const isLeagueAdmin =
    league?.members?.some((m) => m.id === player?.id && m.role === 'admin') ?? false;

  async function handleShare() {
    if (!league?.join_code) return;
    const message = buildInviteMessage({
      leagueName: league.name,
      joinCode: league.join_code,
      origin: window.location.origin,
    });
    try {
      const result = await shareInvite({ message });
      if (result === 'copied') {
        setShareStatus('copied');
        setTimeout(() => setShareStatus('idle'), 2000);
      }
    } catch {
      toast.error('Could not share invite');
    }
  }

  return (
    <div className="mb-5">
      <PageHeader
        title={league?.name ?? 'Leaderboard'}
        eyebrow="Standings"
        back={{ to: '/leagues', label: 'Leagues' }}
        wrapTitle
        className="mb-0"
      />
      {league?.description && (
        <p className="text-text-secondary font-sans text-sm mt-1">{league.description}</p>
      )}
      <div className="mt-3 flex items-start gap-2 flex-wrap">
        {league?.join_code && (
          <Button size="sm" variant="accent" onClick={handleShare} className="gap-1.5">
            <Share2 className="h-3.5 w-3.5" aria-hidden />
            {shareStatus === 'copied' ? 'Copied!' : 'Invite'}
          </Button>
        )}
        {isLeagueAdmin && (
          <Button asChild size="sm" variant="outline">
            <Link to={`/leagues/${slug}/admin/invites`}>Invites</Link>
          </Button>
        )}
        <LeagueActionsMenu slug={slug} leagueName={league?.name ?? 'League'} isAdmin={isLeagueAdmin} />
      </div>
    </div>
  );
}

export function LeaderboardPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { player: currentUser } = useAuth();
  const { slug = DEFAULT_LEAGUE_SLUG } = useParams<{ slug: string }>();
  const leagueSlug = slug;
  const prevDataRef = useRef<LeaderboardEntry[]>([]);
  const reduceMotion = useReducedMotionConfig() ?? false;
  const [hintDismissed, setHintDismissed] = useState<boolean>(
    () => localStorage.getItem(HINT_DISMISSED_KEY) === 'true',
  );
  // U5.3: player IDs whose rank just changed — held for ~260 ms so the
  // arrow has time to play its pulse. Empty on initial mount.
  const [pulsingIds, setPulsingIds] = useState<ReadonlySet<string>>(() => new Set());
  // U22.3: which points period the rows show. 'total' is the default standings.
  const [period, setPeriod] = useState<LeaderboardPeriod>('total');
  const { data: league } = useQuery<LeagueDetail>({
    queryKey: ['league', leagueSlug],
    queryFn: () => apiFetch<LeagueDetail>(`/api/v1/leagues/${leagueSlug}`),
  });

  const { data = [], isLoading, error, refetch, isRefetching } = useQuery<LeaderboardEntry[]>({
    queryKey: ['leaderboard', leagueSlug],
    queryFn: () =>
      apiFetch<LeaderboardEntry[]>(`/api/v1/leagues/${leagueSlug}/leaderboard`),
    staleTime: 15_000,
  });

  // `ranked` is the canonical total-order standings — it drives the rank-change
  // pulse so toggling period never pulses. `displayData` is what we render,
  // re-sorted for the active period (idempotent for 'total').
  const ranked = withLeagueRoster(data, leagueSlug, league?.members ?? null);
  const displayData = rankByPeriod(ranked, period);
  const showArrow = period === 'total';

  useEffect(() => {
    if (ranked.length === 0) return;
    const prev = prevDataRef.current;
    prevDataRef.current = ranked;

    // First render with data — never pulse. Just seed the ref.
    if (prev.length === 0) return;

    const prevByPlayer = Object.fromEntries(prev.map((e) => [e.player_id, e.rank]));
    const changed = new Set<string>();
    for (const e of ranked) {
      const pr = prevByPlayer[e.player_id];
      if (pr !== undefined && pr !== e.rank) changed.add(e.player_id);
    }
    if (changed.size === 0) return;

    setPulsingIds(changed);
    const id = setTimeout(() => setPulsingIds(new Set()), 260);
    return () => clearTimeout(id);
  }, [ranked]);

  useEffect(() => {
    const channel = supabase
      .channel('leaderboard-changes')
      .on(
        'postgres_changes',
        { event: 'INSERT', schema: 'public', table: 'leaderboard_snapshots' },
        () => {
          queryClient.invalidateQueries({ queryKey: ['leaderboard'] });
        },
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [queryClient]);

  function openCompare(playerId: string) {
    if (!currentUser?.id || currentUser.id === playerId) {
      navigate(`/leagues/${leagueSlug}/compare?b=${playerId}`);
      return;
    }
    navigate(`/leagues/${leagueSlug}/compare?a=${currentUser.id}&b=${playerId}`);
  }

  function dismissHint() {
    localStorage.setItem(HINT_DISMISSED_KEY, 'true');
    setHintDismissed(true);
  }

  const prevByPlayer = Object.fromEntries(
    prevDataRef.current.map((e) => [e.player_id, e.rank]),
  );

  if (isLoading) {
    return (
      <div>
        <LeagueLeaderboardHeader league={league} slug={leagueSlug} />
        {!hintDismissed && (
          <div className="mb-4 flex items-center justify-between gap-2 rounded-md border border-border bg-surface px-3 py-2 text-xs font-mono text-text-muted">
            <span>Long-press a row to compare</span>
            <button
              onClick={dismissHint}
              className="shrink-0 text-text-muted hover:text-text-primary transition-colors"
              aria-label="Dismiss hint"
            >
              <X className="h-3.5 w-3.5" aria-hidden />
            </button>
          </div>
        )}
        <SubNav slug={leagueSlug} />
        <div
          className="rounded-lg border border-border bg-surface overflow-hidden divide-y divide-border/50"
          aria-label="Loading leaderboard"
        >
          {Array.from({ length: 8 }).map((_, i) => (
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
        <LeagueLeaderboardHeader league={league} slug={leagueSlug} />
        <EmptyState
          title="Couldn't load the leaderboard"
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
      <LeagueLeaderboardHeader league={league} slug={leagueSlug} />

      {!hintDismissed && (
        <div className="mb-4 flex items-center justify-between gap-2 rounded-md border border-border bg-surface px-3 py-2 text-xs font-mono text-text-muted">
          <span>Long-press a row to compare</span>
          <button
            onClick={dismissHint}
            className="shrink-0 text-text-muted hover:text-text-primary transition-colors"
            aria-label="Dismiss hint"
          >
            <X className="h-3.5 w-3.5" aria-hidden />
          </button>
        </div>
      )}

      <SubNav slug={leagueSlug} />

      {displayData.length === 0 ? (
        <EmptyState
          title="No results entered yet"
          description="The leaderboard fills in as match results are confirmed. Check back after the first kickoff!"
        />
      ) : (
        <>
          <PeriodToggle period={period} onChange={setPeriod} />
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
              <TiebreakHeader pointsLabel={PERIOD_LABELS[period]} />
              <tbody>
                {displayData.map((entry) => {
                  const isMe = entry.player_id === currentUser?.id;
                  return (
                    <LeaderboardRow
                      key={entry.player_id}
                      entry={entry}
                      displayPoints={periodPoints(entry, period)}
                      showArrow={showArrow}
                      prevRank={showArrow ? prevByPlayer[entry.player_id] : undefined}
                      isMe={isMe}
                      reduceMotion={reduceMotion}
                      shouldPulse={showArrow && pulsingIds.has(entry.player_id)}
                      onOpenProfile={() => navigate(`/players/${entry.player_id}`)}
                      onLongPress={() => openCompare(entry.player_id)}
                    />
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
