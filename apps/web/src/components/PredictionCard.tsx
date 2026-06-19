import { useEffect, useState } from 'react';
import { motion, useReducedMotion } from 'framer-motion';
import { formatInTimeZone } from 'date-fns-tz';
import { Clock, Lock } from 'lucide-react';
import type { MatchResponse, PredictionResponse, PointsBreakdown } from '../lib/types';
import { Badge } from './ui/badge';
import { PointsBreakdownPopover } from './PointsBreakdownPopover';
import { ScoreInput } from './ui/score-input';
import { useCountdown } from '../hooks/useCountdown';
import { canEdit, statusLabel, statusVariant } from '../lib/matchStatus';
import type { LocalPrediction } from '../hooks/usePredictionEditor';
import { shortPlaceholder } from '../lib/matchTeam';
import { cn } from '../lib/utils';

// ---------------------------------------------------------------------------
// Points badge with count-up animation
// ---------------------------------------------------------------------------

function PointsBadge({ points, breakdown }: { points: number; breakdown?: PointsBreakdown | null }) {
  const prefersReducedMotion = useReducedMotion();
  const [displayed, setDisplayed] = useState(prefersReducedMotion ? points : 0);

  useEffect(() => {
    if (prefersReducedMotion) { setDisplayed(points); return; }
    if (points === 0) { setDisplayed(0); return; }
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
  }, [points, prefersReducedMotion]);

  return (
    <PointsBreakdownPopover breakdown={breakdown}>
      <Badge variant={points > 0 ? 'success' : 'muted'} data-testid="points-badge" aria-live="polite">
        {displayed} {displayed === 1 ? 'pt' : 'pts'}
      </Badge>
    </PointsBreakdownPopover>
  );
}

// ---------------------------------------------------------------------------
// Countdown formatter
// ---------------------------------------------------------------------------

function formatCountdown(parts: { days: number; hours: number; minutes: number; seconds: number; expired: boolean }): string {
  if (parts.expired) return 'Started';
  if (parts.days > 0) return `${parts.days}d ${parts.hours}h`;
  if (parts.hours > 0) return `${parts.hours}h ${parts.minutes}m`;
  return `${parts.minutes}m ${parts.seconds}s`;
}

// Full-granularity variant for the prediction eyebrow (U20.7): always shows all
// four parts and ticks the seconds, e.g. "7d 21h 14m 32s".
function formatCountdownFull(parts: { days: number; hours: number; minutes: number; seconds: number; expired: boolean }): string {
  if (parts.expired) return 'Started';
  return `${parts.days}d ${parts.hours}h ${parts.minutes}m ${parts.seconds}s`;
}

// ---------------------------------------------------------------------------
// Prediction card — a single match with editable score inputs.
//
// Shared by the Predictions page (group panels) and the home upcoming-matches
// carousel. Presentation only: all editing behaviour lives in the parent via
// the onHomeChange / onAwayChange callbacks (see usePredictionEditor).
// ---------------------------------------------------------------------------

export interface PredictionCardProps {
  match: MatchResponse;
  prediction: PredictionResponse | undefined;
  local: LocalPrediction | undefined;
  timezone: string;
  highlighted: boolean;
  onHomeChange: (matchId: string, value: string) => void;
  onAwayChange: (matchId: string, value: string) => void;
  /**
   * Space-constrained contexts (the home carousel) render team codes — "🇲🇽 MEX"
   * — instead of full names, which truncate to 2–3 chars in a narrow card and
   * become ambiguous (South Africa vs South Korea both show "So…"). Defaults to
   * full names so the Predictions page is unchanged.
   */
  compact?: boolean;
}

export function PredictionCard({
  match,
  prediction,
  local,
  timezone,
  highlighted,
  onHomeChange,
  onAwayChange,
  compact = false,
}: PredictionCardProps) {
  const kickoffLocal = formatInTimeZone(
    new Date(match.kickoff_utc),
    timezone,
    'EEE d MMM, HH:mm',
  );

  const countdown = useCountdown(match.kickoff_utc);
  const prefersReducedMotion = useReducedMotion();

  const editable = canEdit(match.status);
  const isVoided = match.status === 'cancelled' || match.status === 'postponed';
  const isCompleted = match.status === 'completed';
  const isLocked = match.status === 'locked';
  const isLive = match.status === 'live';
  const hasLiveScore =
    match.actual_home_score !== null && match.actual_away_score !== null;

  // Deadline warning: scheduled + < 1hr remaining
  const isDeadlineWarning =
    match.status === 'scheduled' &&
    !countdown.expired &&
    countdown.days === 0 &&
    countdown.hours === 0;

  const flag = (emoji: string) => (emoji ? `${emoji} ` : '');
  const homeLabel = match.home_team
    ? `${flag(match.home_team.flag_emoji)}${compact ? match.home_team.code : match.home_team.name}`
    : shortPlaceholder(match.home_team_placeholder);
  const awayLabel = match.away_team
    ? `${flag(match.away_team.flag_emoji)}${compact ? match.away_team.code : match.away_team.name}`
    : shortPlaceholder(match.away_team_placeholder);
  const homeTitle = !match.home_team ? (match.home_team_placeholder ?? undefined) : undefined;
  const awayTitle = !match.away_team ? (match.away_team_placeholder ?? undefined) : undefined;

  const homeVal = local?.home ?? (prediction?.predicted_home !== null && prediction?.predicted_home !== undefined ? String(prediction.predicted_home) : '');
  const awayVal = local?.away ?? (prediction?.predicted_away !== null && prediction?.predicted_away !== undefined ? String(prediction.predicted_away) : '');

  const points = prediction?.points_awarded ?? null;
  const noSubmission = isCompleted && !prediction;

  // A complete prediction has both scores entered (locally or saved).
  const hasPrediction = homeVal !== '' && awayVal !== '';

  return (
    <motion.div
      className={cn(
        'flex h-full flex-col rounded-lg border bg-surface p-4 transition-all',
        isVoided && 'opacity-50',
        isDeadlineWarning
          ? 'border-warning/60'
          : highlighted
            ? 'border-primary shadow-glow'
            : 'border-border',
      )}
      data-testid={`prediction-card-${match.id}`}
      animate={highlighted && !prefersReducedMotion ? { scale: [1, 1.02, 1] } : {}}
      transition={{ duration: 0.4 }}
    >
      {/* Eyebrow row: kickoff time with countdown beneath it + status pills */}
      <div className="flex items-start justify-between gap-2 mb-3">
        <div className="min-w-0">
          <span className="block font-mono text-[10px] uppercase tracking-[0.25em] text-text-muted">
            {kickoffLocal}
          </span>
          {editable && !countdown.expired && (
            <span
              className={cn(
                'mt-1 flex items-center gap-1 whitespace-nowrap font-mono text-sm tabular-nums',
                isDeadlineWarning ? 'text-warning font-semibold' : 'text-success',
              )}
              data-testid={isDeadlineWarning ? 'deadline-warning' : undefined}
            >
              <Clock className="h-3.5 w-3.5 shrink-0" aria-hidden />
              {formatCountdownFull(countdown)}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {isCompleted && points !== null && !noSubmission && (
            <PointsBadge points={points} breakdown={prediction?.points_breakdown} />
          )}
          {isCompleted && noSubmission && <Badge variant="muted">No entry</Badge>}
          {/* Live carries its own green pulse in the footer (U20.6) — skip the
              red status pill so the two don't clash. */}
          {!isLive && (
            <Badge variant={statusVariant(match.status)}>{statusLabel(match.status)}</Badge>
          )}
        </div>
      </div>

      {/* Teams + score inputs */}
      <div className="flex items-center gap-3">
        <div
          title={homeTitle}
          className={cn(
            'flex-1 text-sm font-sans text-text-primary truncate text-right',
            homeTitle && 'italic text-text-muted font-mono text-xs',
          )}
        >
          {homeLabel}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <ScoreInput
            value={homeVal}
            onChange={(v) => onHomeChange(match.id, v)}
            disabled={!editable}
            aria-label={`Home score for match ${match.match_number}`}
          />
          <span className="text-text-muted font-mono text-base self-center pt-1">–</span>
          <ScoreInput
            value={awayVal}
            onChange={(v) => onAwayChange(match.id, v)}
            disabled={!editable}
            aria-label={`Away score for match ${match.match_number}`}
          />
        </div>
        <div
          title={awayTitle}
          className={cn(
            'flex-1 text-sm font-sans text-text-primary truncate',
            awayTitle && 'italic text-text-muted font-mono text-xs',
          )}
        >
          {awayLabel}
        </div>
      </div>

      {/* Footer states — mt-auto pushes this to the bottom so all cards share
          the same height regardless of status. */}
      <div className="mt-auto">
      {isLocked && (
        <div
          className="mt-3 flex items-center justify-center gap-1.5 text-xs font-sans text-warning"
          data-testid="lock-indicator"
        >
          <Lock size={12} aria-hidden="true" />
          <span>Kicks off in {formatCountdown(countdown)}</span>
        </div>
      )}

      {/* Live: green pulse badge + current score (prediction stays visible in the
          disabled inputs above). U20.6 */}
      {isLive && (
        <div
          className="mt-3 flex items-center justify-center gap-2 font-mono text-xs"
          data-testid="live-indicator"
        >
          <span className="inline-flex items-center gap-1.5 font-semibold uppercase tracking-[0.2em] text-success">
            <span className="relative flex h-2 w-2" aria-hidden>
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-success opacity-75" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-success" />
            </span>
            Live
          </span>
          {hasLiveScore && (
            <span className="tabular-nums text-text-secondary">
              Now {match.actual_home_score}–{match.actual_away_score}
            </span>
          )}
        </div>
      )}

      {/* Uniform scheduled footer: prediction status, centered. A single
          always-present row keeps every open card the same height. */}
      {editable && (
        <div className="mt-3 text-center">
          {hasPrediction ? (
            <span
              className="font-mono text-xs uppercase tracking-[0.2em] text-success"
              data-testid="predicted-indicator"
            >
              Predicted
            </span>
          ) : (
            <span
              className="font-mono text-xs uppercase tracking-[0.2em] text-warning"
              data-testid="not-predicted-warning"
            >
              Not predicted yet
            </span>
          )}
        </div>
      )}

      {isCompleted && match.actual_home_score !== null && match.actual_away_score !== null && (
        <div className="mt-3 text-center text-xs font-mono text-text-muted tabular-nums">
          Result: {match.actual_home_score} – {match.actual_away_score}
          {match.penalties && ' (pens)'}
          {match.extra_time && !match.penalties && ' (aet)'}
        </div>
      )}

      {match.status === 'postponed' && match.postponed_reason && (
        <p className="mt-3 text-xs font-sans text-text-muted text-center">
          {match.postponed_reason}
        </p>
      )}
      </div>{/* end footer */}
    </motion.div>
  );
}
