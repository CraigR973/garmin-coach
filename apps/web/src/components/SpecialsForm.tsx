import { useEffect, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Trophy, Star, Zap, Lock, Award, UserCheck, Handshake } from 'lucide-react';
import { toast } from 'sonner';
import { apiFetch } from '../lib/api';
import { useCountdown } from '../hooks/useCountdown';
import type {
  MySpecialsResponse,
  SpecialPredictionItem,
  SpecialType,
  GroupResponse,
} from '../lib/types';
import { Badge } from '../components/ui/badge';
import { SaveButton, type SaveButtonState } from '../components/ui/save-button';
import { Skeleton } from '../components/ui/skeleton';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { PlayerCombobox } from '../components/PlayerCombobox';
import { EmptyState } from '../components/EmptyState';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const SPECIAL_META: Record<SpecialType, { label: string; description: string; icon: React.ReactNode }> = {
  tournament_winner: {
    label: 'Tournament Winner',
    description: 'Which team lifts the trophy?',
    icon: <Trophy size={18} />,
  },
  golden_boot: {
    label: 'Golden Boot',
    description: 'Which player scores the most goals?',
    icon: <Star size={18} />,
  },
  top_scoring_team: {
    label: 'Top Scoring Team',
    description: 'Which team scores the most goals overall?',
    icon: <Zap size={18} />,
  },
  player_of_tournament: {
    label: 'Player of the Tournament',
    description: 'Which player wins the Golden Ball?',
    icon: <Award size={18} />,
  },
  young_player_of_tournament: {
    label: 'Young Player of the Tournament',
    description: 'Which U21 player wins the Best Young Player award?',
    icon: <UserCheck size={18} />,
  },
  golden_glove: {
    label: 'Golden Glove',
    description: 'Which goalkeeper wins the best goalkeeper award?',
    icon: <Handshake size={18} />,
  },
};

export const SPECIAL_POINTS: Record<SpecialType, number> = {
  tournament_winner: 20,
  golden_boot: 15,
  top_scoring_team: 10,
  player_of_tournament: 15,
  young_player_of_tournament: 10,
  golden_glove: 10,
};

export const PLAYER_SPECIALS: ReadonlySet<SpecialType> = new Set<SpecialType>([
  'golden_boot',
  'player_of_tournament',
  'young_player_of_tournament',
  'golden_glove',
]);

export const SPECIAL_POSITION_FILTER: Partial<Record<SpecialType, string>> = {
  golden_glove: 'GK',
};

export const TEAM_SPECIALS: ReadonlySet<SpecialType> = new Set<SpecialType>([
  'tournament_winner',
  'top_scoring_team',
]);

export const ORDER: SpecialType[] = [
  'tournament_winner',
  'golden_boot',
  'top_scoring_team',
  'player_of_tournament',
  'young_player_of_tournament',
  'golden_glove',
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

export interface TeamOption {
  id: string;
  name: string;
  code: string;
  flag_emoji: string;
}

export function teamsFromGroups(groups: GroupResponse[]): TeamOption[] {
  const seen = new Set<string>();
  const teams: TeamOption[] = [];
  for (const g of groups) {
    for (const s of g.standings) {
      if (!seen.has(s.team_id)) {
        seen.add(s.team_id);
        teams.push({ id: s.team_id, name: s.team_name, code: s.team_code, flag_emoji: s.flag_emoji });
      }
    }
  }
  return teams.sort((a, b) => a.name.localeCompare(b.name));
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
// Lock countdown banner
// ---------------------------------------------------------------------------

export function LockBanner({ lockAt, isLocked }: { lockAt: string | null; isLocked: boolean }) {
  const countdown = useCountdown(lockAt ?? new Date(0).toISOString());

  if (isLocked) {
    return (
      <div className="flex items-center gap-2 px-3 py-2 rounded-md bg-warning/10 border border-warning/30 text-warning text-sm font-sans mb-6">
        <Lock size={14} aria-hidden="true" />
        <span>Tournament has started — special predictions are locked.</span>
      </div>
    );
  }

  if (!lockAt) return null;

  const isDeadlineSoon = !countdown.expired && countdown.days === 0 && countdown.hours === 0;

  return (
    <div
      className={`flex items-center gap-2 px-3 py-2 rounded-md border text-sm font-sans mb-6 ${
        isDeadlineSoon
          ? 'bg-warning/10 border-warning/30 text-warning'
          : 'bg-surface border-border text-text-muted'
      }`}
    >
      <Lock size={14} aria-hidden="true" />
      <span>
        Locks in <span className="font-medium">{formatCountdown(countdown)}</span> — at the opening
        match kickoff.
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Single special card (pre-lock form)
// ---------------------------------------------------------------------------

function SpecialCard({
  ptype,
  prediction,
  teams,
  isLocked,
  onSave,
}: {
  ptype: SpecialType;
  prediction: SpecialPredictionItem | null;
  teams: TeamOption[];
  isLocked: boolean;
  onSave: (
    ptype: SpecialType,
    teamId: string | null,
    playerId: string | null,
    playerName: string | null,
  ) => Promise<void>;
}) {
  const meta = SPECIAL_META[ptype];
  const isTeamPick = !PLAYER_SPECIALS.has(ptype);
  const positionFilter = SPECIAL_POSITION_FILTER[ptype];

  const [teamId, setTeamId] = useState<string>(prediction?.predicted_team_id ?? '');
  const [playerId, setPlayerId] = useState<string>(prediction?.predicted_player_id ?? '');
  const [playerDisplayName, setPlayerDisplayName] = useState<string>(
    prediction?.predicted_player_name ?? '',
  );
  const [saveState, setSaveState] = useState<SaveButtonState>('idle');

  const isDirty = isTeamPick
    ? teamId !== (prediction?.predicted_team_id ?? '')
    : playerId !== (prediction?.predicted_player_id ?? '');

  const isSubmitted = prediction?.submitted_at != null;

  useEffect(() => {
    if (saveState !== 'saved') return;
    const id = setTimeout(() => setSaveState('idle'), 1200);
    return () => clearTimeout(id);
  }, [saveState]);

  function handlePlayerSelect(id: string, name: string) {
    setPlayerId(id);
    setPlayerDisplayName(name);
  }

  async function handleSave() {
    if (isTeamPick && !teamId) {
      toast.error('Please select a team.');
      return;
    }
    if (!isTeamPick && !playerId) {
      toast.error('Please select a player.');
      return;
    }
    setSaveState('saving');
    try {
      await onSave(
        ptype,
        isTeamPick ? teamId : null,
        isTeamPick ? null : playerId,
        isTeamPick ? null : playerDisplayName,
      );
      toast.success(`${meta.label} saved!`);
      setSaveState('saved');
    } catch {
      toast.error('Failed to save. Try again.');
      setSaveState('idle');
    }
  }

  const selectedTeam = teams.find((t) => t.id === teamId);

  return (
    <div className="rounded-lg border border-border bg-surface p-5">
      <div className="flex items-center gap-2.5 mb-1 text-primary">
        {meta.icon}
        <h3 className="font-sans font-semibold text-base tracking-tight text-text-primary">{meta.label}</h3>
        <span className="ml-auto">
          <Badge variant="muted">{SPECIAL_POINTS[ptype]} pts</Badge>
        </span>
      </div>
      <p className="text-text-muted text-sm font-sans mb-4">{meta.description}</p>

      {isLocked ? (
        <div className="font-sans text-sm text-text-primary">
          {isSubmitted ? (
            <span>
              {isTeamPick ? (
                selectedTeam ? (
                  <span>
                    {selectedTeam.flag_emoji} {selectedTeam.name}
                  </span>
                ) : (
                  <span className="text-text-muted">—</span>
                )
              ) : playerDisplayName ? (
                <span>{playerDisplayName}</span>
              ) : (
                <span className="text-text-muted">—</span>
              )}
              {prediction?.points_awarded != null && (
                <Badge
                  variant={prediction.points_awarded > 0 ? 'success' : 'muted'}
                  className="ml-2"
                >
                  {prediction.points_awarded} pts
                </Badge>
              )}
            </span>
          ) : (
            <span className="text-text-muted">No prediction submitted.</span>
          )}
        </div>
      ) : isTeamPick ? (
        <div className="flex gap-2 items-end flex-wrap">
          <div className="flex-1 min-w-0">
            <Select value={teamId} onValueChange={setTeamId} disabled={saveState === 'saving'}>
              <SelectTrigger aria-label={`Select team for ${meta.label}`}>
                <SelectValue placeholder="— Select a team —" />
              </SelectTrigger>
              <SelectContent>
                {teams.map((t) => (
                  <SelectItem key={t.id} value={t.id}>
                    {t.flag_emoji} {t.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <SaveButton
            type="button"
            onClick={handleSave}
            state={saveState}
            idleLabel={isSubmitted ? 'Update' : 'Save'}
            savedLabel="Saved"
            disabled={!isDirty}
            className="whitespace-nowrap"
          />
        </div>
      ) : (
        <div className="flex gap-2 items-end flex-wrap">
          <div className="flex-1 min-w-0">
            <PlayerCombobox
              value={playerId}
              onChange={handlePlayerSelect}
              displayName={playerDisplayName}
              disabled={saveState === 'saving'}
              placeholder="Search for a player…"
              aria-label={`${meta.label} player`}
              position={positionFilter}
            />
          </div>
          <SaveButton
            type="button"
            onClick={handleSave}
            state={saveState}
            idleLabel={isSubmitted ? 'Update' : 'Save'}
            savedLabel="Saved"
            disabled={!isDirty}
            className="whitespace-nowrap"
          />
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// SpecialsForm — embeddable form with its own data queries
// ---------------------------------------------------------------------------

export function SpecialsForm() {
  const queryClient = useQueryClient();

  const { data: mySpecials, isLoading: loadingSpecials, isError: errSpecials } = useQuery({
    queryKey: ['specials', 'me'],
    queryFn: () => apiFetch<MySpecialsResponse>('/api/v1/specials'),
  });

  const { data: groups } = useQuery({
    queryKey: ['groups'],
    queryFn: () => apiFetch<GroupResponse[]>('/api/v1/groups'),
  });

  const saveMutation = useMutation({
    mutationFn: ({
      ptype,
      teamId,
      playerId,
    }: {
      ptype: SpecialType;
      teamId: string | null;
      playerId: string | null;
    }) =>
      apiFetch(`/api/v1/specials/${ptype}`, {
        method: 'PUT',
        body: JSON.stringify({
          predicted_team_id: teamId ?? undefined,
          predicted_player_id: playerId ?? undefined,
        }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['specials', 'me'] });
    },
  });

  const teams = groups ? teamsFromGroups(groups) : [];

  async function handleSave(
    ptype: SpecialType,
    teamId: string | null,
    playerId: string | null,
    _playerName: string | null,
  ): Promise<void> {
    await saveMutation.mutateAsync({ ptype, teamId, playerId });
  }

  if (loadingSpecials) {
    return (
      <div className="space-y-4" aria-label="Loading specials">
        <Skeleton className="h-12 w-full" />
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-[140px] w-full" />
        ))}
      </div>
    );
  }

  if (errSpecials || !mySpecials) {
    return (
      <EmptyState
        title="Couldn't load specials"
        description="Refresh the page or check your connection."
      />
    );
  }

  const predMap = new Map(mySpecials.predictions.map((p) => [p.prediction_type, p]));

  return (
    <div>
      <LockBanner lockAt={mySpecials.lock_at} isLocked={mySpecials.is_locked} />
      <div className="flex flex-col gap-4">
        {ORDER.map((ptype) => {
          const pred = predMap.get(ptype) ?? null;
          const hasValue = pred?.submitted_at != null;
          return (
            <SpecialCard
              key={ptype}
              ptype={ptype}
              prediction={hasValue ? pred : null}
              teams={teams}
              isLocked={mySpecials.is_locked}
              onSave={handleSave}
            />
          );
        })}
      </div>
    </div>
  );
}
