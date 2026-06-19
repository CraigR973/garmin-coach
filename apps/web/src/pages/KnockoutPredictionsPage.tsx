import { useState, useEffect, useRef } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { motion, useReducedMotion } from 'framer-motion';
import { formatInTimeZone } from 'date-fns-tz';
import { Lock } from 'lucide-react';
import { toast } from 'sonner';
import { apiFetch } from '../lib/api';
import { useAuth } from '../contexts/AuthContext';
import { supabase } from '../lib/supabase';
import type { MatchResponse, KnockoutPredictionResponse } from '../lib/types';
import { Badge } from '../components/ui/badge';
import { Skeleton } from '../components/ui/skeleton';
import { BracketTeaser } from '../components/BracketTeaser';
import { PageHeader } from '../components/PageHeader';
import { PredictionsSubNav } from '../components/PredictionsSubNav';
import { useCountdown } from '../hooks/useCountdown';
import { KNOCKOUT_STAGES, type KnockoutStage } from '../lib/stages';
import { shortPlaceholder } from '../lib/matchTeam';
import { cn } from '../lib/utils';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

// Round labels come from the shared stage table (../lib/stages) so the round
// pills here match the Schedule filter chips exactly.

/**
 * Index of the round to open by default — the earliest round the player can
 * actually act on: still open (every match scheduled) and with at least one
 * real-team tie. Pre-tournament (all placeholders) falls back to the first
 * round; a finished bracket falls back to the last (the Final).
 */
function defaultStageIndex(
  stages: readonly KnockoutStage[],
  knockoutMatches: MatchResponse[],
): number {
  for (let i = 0; i < stages.length; i++) {
    const roundMatches = knockoutMatches.filter((m) => m.stage === stages[i].key);
    const open = roundMatches.every((m) => m.status === 'scheduled');
    const hasRealTeams = roundMatches.some((m) => m.home_team && m.away_team);
    if (open && hasRealTeams) return i;
  }
  const allDone = knockoutMatches.every(
    (m) => m.status === 'completed' || m.status === 'cancelled',
  );
  return allDone ? Math.max(0, stages.length - 1) : 0;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

type StatusVariant = 'default' | 'success' | 'error' | 'muted' | 'warning' | 'live';

function statusVariant(status: MatchResponse['status']): StatusVariant {
  const map: Record<MatchResponse['status'], StatusVariant> = {
    scheduled: 'muted',
    locked: 'warning',
    live: 'live',
    completed: 'success',
    postponed: 'warning',
    cancelled: 'error',
  };
  return map[status];
}

function statusLabel(status: MatchResponse['status']): string {
  const map: Record<MatchResponse['status'], string> = {
    scheduled: 'Open',
    locked: 'Locked',
    live: 'Live',
    completed: 'FT',
    postponed: 'Postponed',
    cancelled: 'Voided',
  };
  return map[status];
}

function isRoundLocked(matches: MatchResponse[]): boolean {
  return matches.some((m) => m.status !== 'scheduled');
}

function firstScheduledKickoff(matches: MatchResponse[]): string | null {
  const scheduled = matches.filter((m) => m.status === 'scheduled');
  if (scheduled.length === 0) return null;
  return scheduled.reduce(
    (min, m) => (m.kickoff_utc < min ? m.kickoff_utc : min),
    scheduled[0].kickoff_utc,
  );
}

function formatCountdown(parts: {
  days: number;
  hours: number;
  minutes: number;
  seconds: number;
  expired: boolean;
}): string {
  if (parts.expired) return 'Started';
  if (parts.days > 0) return `${parts.days}d ${parts.hours}h`;
  if (parts.hours > 0) return `${parts.hours}h ${parts.minutes}m`;
  return `${parts.minutes}m ${parts.seconds}s`;
}

// ---------------------------------------------------------------------------
// Points badge with count-up animation
// ---------------------------------------------------------------------------

function PointsBadge({ points }: { points: number }) {
  const [displayed, setDisplayed] = useState(0);

  useEffect(() => {
    if (points === 0) {
      setDisplayed(0);
      return;
    }
    setDisplayed(0);
    const steps = points;
    const intervalMs = Math.max(30, Math.min(120, 600 / steps));
    let current = 0;
    const id = setInterval(() => {
      current++;
      setDisplayed(current);
      if (current >= steps) clearInterval(id);
    }, intervalMs);
    return () => clearInterval(id);
  }, [points]);

  return (
    <Badge variant={points > 0 ? 'success' : 'muted'}>
      {displayed} {displayed === 1 ? 'pt' : 'pts'}
    </Badge>
  );
}

// ---------------------------------------------------------------------------
// Round lock countdown banner
// ---------------------------------------------------------------------------

function RoundLockBanner({ matches }: { matches: MatchResponse[] }) {
  const locked = isRoundLocked(matches);
  const firstKickoff = firstScheduledKickoff(matches);
  const countdown = useCountdown(firstKickoff ?? new Date(0).toISOString());

  if (locked) {
    return (
      <div className="flex items-center gap-2 px-3 py-2 rounded-md bg-warning/10 border border-warning/30 text-warning text-sm font-sans mb-4">
        <Lock size={14} aria-hidden="true" />
        <span>This round is locked — picks can no longer be changed.</span>
      </div>
    );
  }

  if (!firstKickoff) return null;

  const isDeadlineSoon =
    !countdown.expired && countdown.days === 0 && countdown.hours === 0;

  return (
    <div
      className={`flex items-center gap-2 px-3 py-2 rounded-md border text-sm font-sans mb-4 ${
        isDeadlineSoon
          ? 'bg-warning/10 border-warning/30 text-warning'
          : 'bg-surface border-border text-text-muted'
      }`}
    >
      <Lock size={14} aria-hidden="true" />
      <span>
        Round locks in <span className="font-medium">{formatCountdown(countdown)}</span> — when
        the first match kicks off.
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Knockout match card
// ---------------------------------------------------------------------------

function KnockoutCard({
  match,
  localWinnerId,
  pointsAwarded,
  saving,
  error,
  timezone,
  highlighted,
  roundLocked,
  onPick,
}: {
  match: MatchResponse;
  localWinnerId: string | null;
  pointsAwarded: number | null | undefined;
  saving: boolean;
  error: boolean;
  timezone: string;
  highlighted: boolean;
  roundLocked: boolean;
  onPick: (matchId: string, winnerId: string) => void;
}) {
  const kickoffLocal = formatInTimeZone(
    new Date(match.kickoff_utc),
    timezone,
    'EEE d MMM, HH:mm',
  );
  const countdown = useCountdown(match.kickoff_utc);
  const prefersReducedMotion = useReducedMotion();

  const isCompleted = match.status === 'completed';
  const isLocked = match.status === 'locked';
  const isVoided = match.status === 'cancelled' || match.status === 'postponed';
  const isDeadlineWarning =
    match.status === 'scheduled' &&
    !countdown.expired &&
    countdown.days === 0 &&
    countdown.hours === 0;

  const homeId = match.home_team?.id ?? null;
  const awayId = match.away_team?.id ?? null;
  const homeLabel = match.home_team
    ? `${match.home_team.flag_emoji} ${match.home_team.name}`
    : shortPlaceholder(match.home_team_placeholder);
  const awayLabel = match.away_team
    ? `${match.away_team.flag_emoji} ${match.away_team.name}`
    : shortPlaceholder(match.away_team_placeholder);
  const homeTitle = !match.home_team ? (match.home_team_placeholder ?? undefined) : undefined;
  const awayTitle = !match.away_team ? (match.away_team_placeholder ?? undefined) : undefined;

  const pickedHome = localWinnerId !== null && localWinnerId === homeId;
  const pickedAway = localWinnerId !== null && localWinnerId === awayId;
  const hasPick = pickedHome || pickedAway;
  const canPick = !roundLocked && !isVoided;

  // Determine actual winner from result
  let actualWinnerId: string | null = null;
  if (isCompleted && match.actual_home_score !== null && match.actual_away_score !== null) {
    if (match.actual_home_score > match.actual_away_score) actualWinnerId = homeId;
    else if (match.actual_away_score > match.actual_home_score) actualWinnerId = awayId;
    // Draws resolved by penalty_winner_id but we don't have it in MatchResponse — leave null
  }

  return (
    <motion.div
      className={`rounded-lg border bg-surface p-3 transition-all ${
        isVoided ? 'opacity-50' : ''
      } ${
        isDeadlineWarning
          ? 'border-warning/60'
          : highlighted
            ? 'border-primary'
            : 'border-border'
      }`}
      data-testid={`knockout-card-${match.id}`}
      animate={highlighted && !prefersReducedMotion ? { scale: [1, 1.02, 1] } : {}}
      transition={{ duration: 0.4 }}
    >
      {/* Header */}
      <div className="flex items-center justify-between gap-2 mb-3">
        <span
          className={`text-xs font-mono ${
            isDeadlineWarning ? 'text-warning font-semibold' : 'text-text-muted'
          }`}
        >
          {kickoffLocal}
          {isDeadlineWarning && (
            <span className="ml-1.5">· {formatCountdown(countdown)} left</span>
          )}
        </span>
        <div className="flex items-center gap-2">
          {saving && (
            <span className="text-xs font-sans text-text-muted animate-pulse">Saving…</span>
          )}
          {error && <span className="text-xs font-sans text-error">Save failed</span>}
          {!hasPick && !roundLocked && match.status === 'scheduled' && (
            <Badge variant="muted">No pick yet</Badge>
          )}
          <Badge variant={statusVariant(match.status)}>{statusLabel(match.status)}</Badge>
        </div>
      </div>

      {/* Team buttons */}
      <div className="flex items-stretch gap-2">
        <TeamButton
          label={homeLabel}
          teamId={homeId}
          picked={pickedHome}
          correct={actualWinnerId !== null && actualWinnerId === homeId}
          wrong={isCompleted && pickedHome && actualWinnerId !== null && actualWinnerId !== homeId}
          disabled={!canPick || saving || homeId === null}
          title={homeTitle}
          onClick={() => homeId && onPick(match.id, homeId)}
        />

        <div className="flex items-center justify-center shrink-0 w-8 text-text-muted font-mono text-sm select-none">
          {isCompleted && match.actual_home_score !== null
            ? `${match.actual_home_score}–${match.actual_away_score}`
            : 'vs'}
        </div>

        <TeamButton
          label={awayLabel}
          teamId={awayId}
          picked={pickedAway}
          correct={actualWinnerId !== null && actualWinnerId === awayId}
          wrong={isCompleted && pickedAway && actualWinnerId !== null && actualWinnerId !== awayId}
          disabled={!canPick || saving || awayId === null}
          title={awayTitle}
          onClick={() => awayId && onPick(match.id, awayId)}
        />
      </div>

      {/* Lock indicator for individually locked matches */}
      {(isLocked || (roundLocked && match.status === 'scheduled')) && !isCompleted && (
        <div className="mt-2 flex items-center justify-center gap-1.5 text-xs font-sans text-warning">
          <Lock size={12} aria-hidden="true" />
          <span>
            {match.status === 'scheduled' ? 'Round locked' : `Kicks off in ${formatCountdown(countdown)}`}
          </span>
        </div>
      )}

      {/* Points (completed) */}
      {isCompleted && localWinnerId !== null && pointsAwarded != null && (
        <div className="mt-2 flex justify-center">
          <PointsBadge points={pointsAwarded} />
        </div>
      )}

      {/* Penalties / AET note */}
      {isCompleted && (match.penalties || match.extra_time) && (
        <div className="mt-2 text-center text-xs font-mono text-text-muted">
          {match.penalties ? '(pens)' : '(aet)'}
        </div>
      )}
    </motion.div>
  );
}

// ---------------------------------------------------------------------------
// Team button
// ---------------------------------------------------------------------------

function TeamButton({
  label,
  teamId,
  picked,
  correct,
  wrong,
  disabled,
  title,
  onClick,
}: {
  label: string;
  teamId: string | null;
  picked: boolean;
  correct: boolean;
  wrong: boolean;
  disabled: boolean;
  title?: string;
  onClick: () => void;
}) {
  let cls =
    'flex-1 rounded-md border px-2 py-2.5 text-sm font-sans text-center transition-all leading-snug ';

  if (correct) {
    cls += 'border-success/60 bg-success/10 text-success font-medium';
  } else if (wrong) {
    cls += 'border-error/40 bg-error/5 text-text-muted line-through';
  } else if (picked) {
    cls += 'border-primary bg-primary/10 text-text-primary font-medium';
  } else if (disabled) {
    cls += 'border-border bg-surface text-text-muted cursor-not-allowed opacity-60';
  } else {
    cls += 'border-border bg-surface text-text-secondary hover:border-primary/50 hover:bg-surface-elevated cursor-pointer';
  }

  return (
    <button type="button" className={cls} disabled={disabled} title={title} onClick={onClick}>
      {teamId === null ? (
        <span className="text-text-muted italic font-mono">{label}</span>
      ) : (
        label
      )}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Round panel
// ---------------------------------------------------------------------------

function RoundPanel({
  matches,
  predictions,
  localWinners,
  saving,
  errors,
  timezone,
  highlightedMatchIds,
  onPick,
}: {
  matches: MatchResponse[];
  predictions: KnockoutPredictionResponse[];
  localWinners: Record<string, string | null>;
  saving: Record<string, boolean>;
  errors: Record<string, boolean>;
  timezone: string;
  highlightedMatchIds: Set<string>;
  onPick: (matchId: string, winnerId: string) => void;
}) {
  const predByMatch = Object.fromEntries(predictions.map((p) => [p.match_id, p]));
  const roundLocked = isRoundLocked(matches);

  // Points total for the round (completed matches)
  const roundPoints = predictions
    .filter((p) => matches.some((m) => m.id === p.match_id))
    .reduce((sum, p) => sum + (p.points_awarded ?? 0), 0);
  const hasCompletedMatches = matches.some((m) => m.status === 'completed');

  return (
    <div>
      <RoundLockBanner matches={matches} />

      {hasCompletedMatches && roundPoints > 0 && (
        <div className="flex items-center justify-end mb-3">
          <span className="text-xs font-sans text-text-muted mr-2">Round total:</span>
          <PointsBadge points={roundPoints} />
        </div>
      )}

      <div className="flex flex-col gap-3">
        {matches.map((m) => {
          const pred = predByMatch[m.id];
          const winnerId =
            localWinners[m.id] !== undefined
              ? localWinners[m.id]
              : (pred?.predicted_winner_id ?? null);

          return (
            <KnockoutCard
              key={m.id}
              match={m}
              localWinnerId={winnerId}
              pointsAwarded={pred?.points_awarded}
              saving={saving[m.id] ?? false}
              error={errors[m.id] ?? false}
              timezone={timezone}
              highlighted={highlightedMatchIds.has(m.id)}
              roundLocked={roundLocked}
              onPick={onPick}
            />
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export function KnockoutPredictionsPage() {
  const { player } = useAuth();
  const timezone = player?.timezone ?? 'UTC';
  const queryClient = useQueryClient();

  // null until the player taps a round pill — until then we follow the
  // smart default (earliest actionable round) computed from the data.
  const [userStage, setUserStage] = useState<number | null>(null);
  const [localWinners, setLocalWinners] = useState<Record<string, string | null>>({});
  const [saving, setSaving] = useState<Record<string, boolean>>({});
  const [errors, setErrors] = useState<Record<string, boolean>>({});
  const [highlightedMatchIds, setHighlightedMatchIds] = useState<Set<string>>(new Set());
  const prevScoresRef = useRef<Record<string, boolean>>({});

  // Fetch all matches (filter knockout stages client-side)
  const { data: allMatches = [], isLoading: matchesLoading } = useQuery<MatchResponse[]>({
    queryKey: ['matches', 'all'],
    queryFn: () => apiFetch<MatchResponse[]>('/api/v1/matches'),
    staleTime: 30_000,
  });

  // Fetch my knockout predictions
  const { data: predictions = [], isLoading: predsLoading } = useQuery<KnockoutPredictionResponse[]>({
    queryKey: ['knockout-predictions', 'me'],
    queryFn: () => apiFetch<KnockoutPredictionResponse[]>('/api/v1/knockout-predictions/me'),
    staleTime: 30_000,
  });

  const knockoutMatches = allMatches.filter(
    (m) => m.stage !== 'group' && m.stage !== 'winner',
  );

  const stagesWithMatches = KNOCKOUT_STAGES.filter((s) =>
    knockoutMatches.some((m) => m.stage === s.key),
  );

  // Follow the smart default until the player picks a round, then honour their
  // choice. Clamp so a shrinking stage list can never select out of range.
  const activeStage = userStage ?? defaultStageIndex(stagesWithMatches, knockoutMatches);
  const clampedStage = Math.min(activeStage, Math.max(0, stagesWithMatches.length - 1));

  // Track null scores for realtime result detection
  useEffect(() => {
    for (const m of knockoutMatches) {
      prevScoresRef.current[m.id] = m.actual_home_score === null;
    }
  }, [allMatches]);

  // Realtime: subscribe to match changes
  useEffect(() => {
    const channel = supabase
      .channel('knockout-predictions-match-results')
      .on(
        'postgres_changes',
        { event: 'UPDATE', schema: 'public', table: 'matches' },
        async (payload) => {
          const updated = payload.new as {
            id: string;
            actual_home_score: number | null;
            actual_away_score: number | null;
          };
          const wasNull = prevScoresRef.current[updated.id] ?? true;
          const nowSet =
            updated.actual_home_score !== null && updated.actual_away_score !== null;

          await queryClient.invalidateQueries({ queryKey: ['matches', 'all'] });

          if (wasNull && nowSet) {
            const fresh = await queryClient.fetchQuery<KnockoutPredictionResponse[]>({
              queryKey: ['knockout-predictions', 'me'],
              queryFn: () =>
                apiFetch<KnockoutPredictionResponse[]>('/api/v1/knockout-predictions/me'),
            });
            const pred = fresh.find((p) => p.match_id === updated.id);
            const pts = pred?.points_awarded ?? null;
            if (pts !== null) {
              toast.success(
                `Result in! You scored ${pts} pt${pts !== 1 ? 's' : ''}`,
                { duration: 6000 },
              );
            }

            setHighlightedMatchIds((prev) => new Set([...prev, updated.id]));
            setTimeout(() => {
              setHighlightedMatchIds((prev) => {
                const next = new Set(prev);
                next.delete(updated.id);
                return next;
              });
            }, 2500);
          }
        },
      )
      .subscribe();

    return () => {
      void supabase.removeChannel(channel);
    };
  }, [queryClient]);

  async function handlePick(matchId: string, winnerId: string) {
    setSaving((prev) => ({ ...prev, [matchId]: true }));
    setErrors((prev) => ({ ...prev, [matchId]: false }));
    // Optimistic update
    setLocalWinners((prev) => ({ ...prev, [matchId]: winnerId }));

    try {
      await apiFetch<KnockoutPredictionResponse>(
        `/api/v1/knockout-predictions/${matchId}`,
        {
          method: 'PUT',
          body: JSON.stringify({ predicted_winner_id: winnerId }),
        },
      );
      await queryClient.invalidateQueries({ queryKey: ['knockout-predictions', 'me'] });
    } catch {
      setErrors((prev) => ({ ...prev, [matchId]: true }));
      // Revert optimistic update
      setLocalWinners((prev) => {
        const pred = predictions.find((p) => p.match_id === matchId);
        return { ...prev, [matchId]: pred?.predicted_winner_id ?? null };
      });
      toast.error('Failed to save pick — please try again');
    } finally {
      setSaving((prev) => ({ ...prev, [matchId]: false }));
    }
  }

  const isLoading = matchesLoading || predsLoading;

  if (isLoading) {
    return (
      <div>
        <PageHeader title="Knockout Picks" eyebrow="Bracket" />
        <PredictionsSubNav />
        <div className="space-y-4" aria-label="Loading knockout picks">
          <div className="flex gap-1.5 flex-wrap">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-8 w-20 rounded-full" />
            ))}
          </div>
          <Skeleton className="h-[300px] w-full rounded-lg" />
        </div>
      </div>
    );
  }

  if (stagesWithMatches.length === 0) {
    return (
      <div>
        <PageHeader title="Knockout Picks" eyebrow="Bracket" />
        <PredictionsSubNav />
        <BracketTeaser
          title="Knockout picks open after group stage"
          ctaLabel="Make your specials picks →"
          ctaTo="/predictions/specials"
        />
      </div>
    );
  }

  const activeStageKey = stagesWithMatches[clampedStage]?.key ?? '';
  const activeMatches = knockoutMatches
    .filter((m) => m.stage === activeStageKey)
    .sort((a, b) => a.match_number - b.match_number);

  return (
    <div>
      <PageHeader title="Knockout Picks" eyebrow="Bracket" />
      <PredictionsSubNav />

      {/* Round pill scroller */}
      <nav
        className="-mx-4 sm:-mx-0 mb-5 overflow-x-auto"
        role="tablist"
        aria-label="Knockout rounds"
      >
        <div className="flex gap-1.5 px-4 sm:px-0 min-w-max">
          {stagesWithMatches.map((stage, idx) => {
            const active = idx === clampedStage;
            return (
              <button
                key={stage.key}
                type="button"
                role="tab"
                aria-selected={active}
                aria-label={stage.long}
                onClick={() => setUserStage(idx)}
                className={cn(
                  'inline-flex items-center px-3.5 py-1.5 rounded-full text-xs font-medium font-sans whitespace-nowrap transition-colors press-down focus-visible:outline-none focus-visible:shadow-glow',
                  active
                    ? 'bg-primary/15 text-primary border border-primary/30'
                    : 'bg-surface text-text-secondary hover:bg-surface-elevated border border-border',
                )}
              >
                {stage.short}
              </button>
            );
          })}
        </div>
      </nav>

      {/* Active round content */}
      <RoundPanel
        matches={activeMatches}
        predictions={predictions}
        localWinners={localWinners}
        saving={saving}
        errors={errors}
        timezone={timezone}
        highlightedMatchIds={highlightedMatchIds}
        onPick={handlePick}
      />
    </div>
  );
}
