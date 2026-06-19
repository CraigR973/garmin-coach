import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { formatInTimeZone } from 'date-fns-tz';
import { ChevronLeft } from 'lucide-react';
import { apiFetch } from '../lib/api';
import { shortPlaceholder } from '../lib/matchTeam';
import { useAuth } from '../contexts/AuthContext';
import type {
  MatchResponse,
  PredictionResponse,
  MatchPredictionsResponse,
} from '../lib/types';
import { Badge } from '../components/ui/badge';
import { SaveButton, type SaveButtonState } from '../components/ui/save-button';
import { PointsBreakdownPopover } from '../components/PointsBreakdownPopover';
import { ScoreInput } from '../components/ui/score-input';
import { Skeleton } from '../components/ui/skeleton';
import { EmptyState } from '../components/EmptyState';
import { useCountdown } from '../hooks/useCountdown';

// ---------------------------------------------------------------------------
// Status helpers
// ---------------------------------------------------------------------------

type StatusVariant = 'default' | 'success' | 'error' | 'muted' | 'accent' | 'warning' | 'live';

const STATUS_LABEL: Record<MatchResponse['status'], string> = {
  scheduled: 'Scheduled',
  locked: 'Locked',
  live: 'Live',
  completed: 'FT',
  postponed: 'Postponed',
  cancelled: 'Cancelled',
};

const STATUS_VARIANT: Record<MatchResponse['status'], StatusVariant> = {
  scheduled: 'muted',
  locked: 'warning',
  live: 'live',
  completed: 'success',
  postponed: 'warning',
  cancelled: 'error',
};

// ---------------------------------------------------------------------------
// Match header
// ---------------------------------------------------------------------------

function MatchHeader({ match, timezone }: { match: MatchResponse; timezone: string }) {
  const homeLabel = match.home_team
    ? `${match.home_team.flag_emoji} ${match.home_team.name}`
    : shortPlaceholder(match.home_team_placeholder);
  const awayLabel = match.away_team
    ? `${match.away_team.flag_emoji} ${match.away_team.name}`
    : shortPlaceholder(match.away_team_placeholder);
  const homeTitle = !match.home_team ? (match.home_team_placeholder ?? undefined) : undefined;
  const awayTitle = !match.away_team ? (match.away_team_placeholder ?? undefined) : undefined;

  const kickoffLocal = formatInTimeZone(
    new Date(match.kickoff_utc),
    timezone,
    'EEE d MMM yyyy, HH:mm',
  );

  const isResult =
    match.status === 'completed' &&
    match.actual_home_score !== null &&
    match.actual_away_score !== null;

  return (
    <div className="rounded-lg border border-border bg-surface p-6 mb-6">
      <div className="flex items-center justify-between mb-4">
        <span className="text-xs font-mono text-text-muted uppercase tracking-wider">
          Match {match.match_number} · {match.stage.toUpperCase()}
        </span>
        <Badge variant={STATUS_VARIANT[match.status]}>{STATUS_LABEL[match.status]}</Badge>
      </div>

      <div className="flex items-center justify-between gap-4">
        <span
          title={homeTitle}
          className={homeTitle
            ? 'flex-1 text-center font-mono text-sm italic text-text-muted'
            : 'flex-1 text-center text-lg font-sans text-text-primary font-semibold'}
        >
          {homeLabel}
        </span>

        {isResult ? (
          <span className="font-mono text-3xl font-bold text-text-primary tabular-nums shrink-0">
            {match.actual_home_score} – {match.actual_away_score}
          </span>
        ) : (
          <span className="text-text-muted font-mono text-xl shrink-0">vs</span>
        )}

        <span
          title={awayTitle}
          className={awayTitle
            ? 'flex-1 text-center font-mono text-sm italic text-text-muted'
            : 'flex-1 text-center text-lg font-sans text-text-primary font-semibold'}
        >
          {awayLabel}
        </span>
      </div>

      <div className="mt-4 text-center space-y-1">
        <p className="text-sm font-mono text-text-secondary">{kickoffLocal}</p>
        {match.venue && (
          <p className="text-xs text-text-muted font-sans">{match.venue}</p>
        )}
        {match.extra_time && (
          <p className="text-xs text-text-muted font-mono">
            {match.penalties ? 'After extra time & penalties' : 'After extra time'}
          </p>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Cancelled notice
// ---------------------------------------------------------------------------

function CancelledNotice({ reason }: { reason: string | null }) {
  return (
    <div className="rounded-lg border border-border bg-surface p-4 text-center">
      <p className="text-error font-sans font-semibold mb-1">Match Cancelled</p>
      <p className="text-sm text-text-muted font-sans">
        {reason ?? 'This match has been cancelled. No points will be awarded.'}
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Lock countdown
// ---------------------------------------------------------------------------

function LockCountdown({ kickoffUtc }: { kickoffUtc: string }) {
  const { days, hours, minutes, seconds, expired } = useCountdown(kickoffUtc);
  if (expired) return null;
  const parts =
    days > 0
      ? `${days}d ${hours}h ${minutes}m`
      : hours > 0
        ? `${hours}h ${minutes}m ${seconds}s`
        : `${minutes}m ${seconds}s`;
  return (
    <div className="text-center mb-4">
      <p className="text-xs text-text-muted font-sans mb-1">Predictions lock at kickoff</p>
      <p className="font-mono text-primary font-bold tabular-nums">{parts}</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Pre-lock: own prediction form
// ---------------------------------------------------------------------------

interface PredictionFormProps {
  matchId: string;
  existing: PredictionResponse | undefined;
}

function PredictionForm({ matchId, existing }: PredictionFormProps) {
  const queryClient = useQueryClient();
  const [home, setHome] = useState<string>(
    existing?.predicted_home !== null && existing?.predicted_home !== undefined
      ? String(existing.predicted_home)
      : '',
  );
  const [away, setAway] = useState<string>(
    existing?.predicted_away !== null && existing?.predicted_away !== undefined
      ? String(existing.predicted_away)
      : '',
  );
  const [saveState, setSaveState] = useState<SaveButtonState>('idle');

  const mutation = useMutation({
    mutationFn: (body: { predicted_home: number; predicted_away: number }) =>
      apiFetch<PredictionResponse>(`/api/v1/predictions/${matchId}`, {
        method: 'PUT',
        body: JSON.stringify(body),
      }),
    onMutate: () => {
      setSaveState('saving');
    },
    onSuccess: () => {
      setSaveState('saved');
      queryClient.invalidateQueries({ queryKey: ['predictions', 'me'] });
    },
    onError: () => {
      setSaveState('idle');
    },
  });

  // Auto-reset from `saved` → `idle` after the 1.2 s hold.
  useEffect(() => {
    if (saveState !== 'saved') return;
    const id = setTimeout(() => setSaveState('idle'), 1200);
    return () => clearTimeout(id);
  }, [saveState]);

  const homeVal = parseInt(home, 10);
  const awayVal = parseInt(away, 10);
  const isValid = !isNaN(homeVal) && !isNaN(awayVal) && homeVal >= 0 && awayVal >= 0;

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!isValid) return;
    mutation.mutate({ predicted_home: homeVal, predicted_away: awayVal });
  }

  return (
    <div className="rounded-lg border border-border bg-surface-elevated p-4">
      <h2 className="text-base font-semibold text-text-primary font-sans tracking-tight mb-4">Your Prediction</h2>

      {existing?.submitted_at && (
        <p className="text-xs text-text-muted font-sans mb-3">
          Last saved · updated {existing.update_count} time{existing.update_count !== 1 ? 's' : ''}
        </p>
      )}

      <form onSubmit={handleSubmit} className="flex items-center gap-3">
        <ScoreInput
          value={home}
          onChange={setHome}
          aria-label="Home score"
        />
        <span className="font-mono text-text-muted self-center pt-1">–</span>
        <ScoreInput
          value={away}
          onChange={setAway}
          aria-label="Away score"
        />
        <SaveButton
          state={saveState}
          idleLabel="Save"
          savedLabel="Saved"
          size="sm"
          className="ml-2"
          disabled={!isValid}
        />
      </form>

      {mutation.isError && (
        <p className="text-error text-xs font-sans mt-2">Failed to save. Try again.</p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Post-lock: comparison table
// ---------------------------------------------------------------------------

interface ComparisonTableProps {
  response: MatchPredictionsResponse;
  currentPlayerId: string;
}

function ComparisonTable({ response, currentPlayerId }: ComparisonTableProps) {
  if (response.predictions.length === 0) {
    return (
      <div className="rounded-lg border border-border bg-surface p-4 text-center">
        <p className="text-text-muted font-sans text-sm">No predictions were submitted.</p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-border bg-surface overflow-hidden">
      <h2 className="text-base font-semibold text-text-primary font-sans tracking-tight p-4 border-b border-border">
        All Predictions
      </h2>
      <div className="overflow-x-auto">
        <table className="w-full text-sm font-sans">
          <thead>
            <tr className="border-b border-border bg-background">
              <th className="text-left px-4 py-2 text-text-muted font-mono text-xs uppercase tracking-wider">
                Player
              </th>
              <th className="text-center px-4 py-2 text-text-muted font-mono text-xs uppercase tracking-wider">
                Prediction
              </th>
              <th className="text-center px-4 py-2 text-text-muted font-mono text-xs uppercase tracking-wider">
                Points
              </th>
            </tr>
          </thead>
          <tbody>
            {response.predictions.map((item) => (
              <tr
                key={item.player_id}
                className={`border-b border-border last:border-0 ${
                  item.player_id === currentPlayerId ? 'bg-surface-elevated' : ''
                }`}
              >
                <td className="px-4 py-3 text-text-primary">
                  {item.player_name}
                  {item.player_id === currentPlayerId && (
                    <span className="ml-2 text-xs text-text-muted">(you)</span>
                  )}
                </td>
                <td className="px-4 py-3 text-center font-mono text-text-primary tabular-nums">
                  {item.predicted_home !== null && item.predicted_away !== null
                    ? `${item.predicted_home} – ${item.predicted_away}`
                    : <span className="text-text-muted">–</span>}
                </td>
                <td className="px-4 py-3 text-center font-mono text-text-primary tabular-nums">
                  {item.points_awarded !== null ? (
                    <PointsBreakdownPopover breakdown={item.points_breakdown}>
                      <span>{item.points_awarded}</span>
                    </PointsBreakdownPopover>
                  ) : (
                    <span className="text-text-muted">–</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export function MatchDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { player } = useAuth();
  const timezone = player?.timezone ?? 'UTC';

  const matchQuery = useQuery<MatchResponse>({
    queryKey: ['match', id],
    queryFn: () => apiFetch<MatchResponse>(`/api/v1/matches/${id}`),
    enabled: !!id,
  });

  const myPredsQuery = useQuery<PredictionResponse[]>({
    queryKey: ['predictions', 'me'],
    queryFn: () => apiFetch<PredictionResponse[]>('/api/v1/predictions/me'),
    staleTime: 30_000,
  });

  const isPreLock = matchQuery.data?.status === 'scheduled';

  const matchPredsQuery = useQuery<MatchPredictionsResponse>({
    queryKey: ['predictions', 'match', id],
    queryFn: () => apiFetch<MatchPredictionsResponse>(`/api/v1/predictions/match/${id}`),
    enabled: !!id && !isPreLock,
    staleTime: 30_000,
  });

  if (matchQuery.isLoading) {
    return (
      <div>
        <Skeleton className="h-3 w-12 mb-4" />
        <Skeleton className="h-[200px] w-full mb-6" />
        <Skeleton className="h-[140px] w-full" />
      </div>
    );
  }
  if (matchQuery.error || !matchQuery.data) {
    return (
      <EmptyState
        title="Match not found"
        description="This match either doesn't exist or couldn't be loaded."
      />
    );
  }

  const match = matchQuery.data;
  const myPrediction = myPredsQuery.data?.find((p) => p.match_id === id);

  return (
    <div>
      <button
        onClick={() => navigate(-1)}
        aria-label="Back"
        className="tap-target -ml-2 mb-3 inline-flex items-center gap-1 text-xs font-mono uppercase tracking-[0.2em] text-text-muted hover:text-text-primary press-down rounded-md focus-visible:outline-none focus-visible:shadow-glow"
      >
        <ChevronLeft className="h-4 w-4" aria-hidden />
        Back
      </button>

      <MatchHeader match={match} timezone={timezone} />

      {match.status === 'cancelled' && (
        <CancelledNotice reason={match.postponed_reason} />
      )}

      {isPreLock && (
        <>
          <LockCountdown kickoffUtc={match.kickoff_utc} />
          <PredictionForm matchId={id!} existing={myPrediction} />
        </>
      )}

      {!isPreLock && match.status !== 'cancelled' && (
        <>
          {matchPredsQuery.isLoading && (
            <Skeleton className="h-[200px] w-full" aria-label="Loading predictions" />
          )}
          {matchPredsQuery.data && (
            <ComparisonTable
              response={matchPredsQuery.data}
              currentPlayerId={player?.id ?? ''}
            />
          )}
        </>
      )}

      {match.status === 'cancelled' && matchPredsQuery.data && (
        <div className="mt-4">
          <ComparisonTable
            response={matchPredsQuery.data}
            currentPlayerId={player?.id ?? ''}
          />
        </div>
      )}
    </div>
  );
}
