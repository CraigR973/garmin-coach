import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { apiFetch } from '../lib/api';
import { useAuth } from '../contexts/AuthContext';
import type {
  MySpecialsResponse,
  SpecialType,
  GroupResponse,
  GlobalSpecialsResponse,
} from '../lib/types';
import { Badge } from '../components/ui/badge';
import { SaveButton } from '../components/ui/save-button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { PlayerCombobox } from '../components/PlayerCombobox';
import { PageHeader } from '../components/PageHeader';
import { PredictionsSubNav } from '../components/PredictionsSubNav';
import {
  SpecialsForm,
  teamsFromGroups,
  SPECIAL_META,
  SPECIAL_POINTS,
  SPECIAL_POSITION_FILTER,
  TEAM_SPECIALS,
  PLAYER_SPECIALS,
  ORDER,
  type TeamOption,
} from '../components/SpecialsForm';

// ---------------------------------------------------------------------------
// Global comparison view — all players across all leagues
// ---------------------------------------------------------------------------

const SPECIAL_ORDER: SpecialType[] = [
  'tournament_winner',
  'golden_boot',
  'top_scoring_team',
  'player_of_tournament',
  'young_player_of_tournament',
  'golden_glove',
];

function GlobalComparisonView({
  global: globalData,
  mySpecials,
}: {
  global: GlobalSpecialsResponse;
  mySpecials: MySpecialsResponse;
}) {
  const myPickMap = new Map(
    mySpecials.predictions.map((p) => {
      let label: string | null = null;
      if (PLAYER_SPECIALS.has(p.prediction_type as SpecialType)) {
        label = p.predicted_player_name ?? null;
      } else if (p.predicted_team_id) {
        // match against team_id in global picks
        label = p.predicted_team_id;
      }
      return [p.prediction_type, label];
    }),
  );

  return (
    <div className="mt-10 border-t border-border pt-6">
      <h2 className="font-sans font-semibold text-lg text-text-primary tracking-tight mb-1">
        How everyone picked
      </h2>
      <p className="text-text-muted text-sm font-sans mb-5">
        {globalData.total_players} players across all leagues.
      </p>

      <div className="flex flex-col gap-4">
        {SPECIAL_ORDER.map((ptype) => {
          const buckets = globalData.by_type[ptype] ?? [];
          const myRaw = myPickMap.get(ptype) ?? null;
          const total = buckets.reduce((s, b) => s + b.count, 0);
          const isTeam = !PLAYER_SPECIALS.has(ptype);

          return (
            <div key={ptype} className="rounded-lg border border-border bg-surface p-4">
              <div className="flex items-center gap-2 mb-3">
                <span className="text-primary">{SPECIAL_META[ptype].icon}</span>
                <span className="font-sans font-semibold text-sm text-text-primary">
                  {SPECIAL_META[ptype].label}
                </span>
                {total > 0 && (
                  <span className="ml-auto font-mono text-[10px] text-text-muted">
                    {total} picks
                  </span>
                )}
              </div>

              {buckets.length === 0 ? (
                <p className="text-text-muted text-sm font-sans">No picks yet.</p>
              ) : (
                <div className="flex flex-col gap-2">
                  {buckets.map((b) => {
                    const isMe = isTeam
                      ? myRaw === b.team_id
                      : myRaw === b.answer;
                    const pct = total > 0 ? Math.round((b.count / total) * 100) : 0;
                    return (
                      <div key={b.answer}>
                        <div className="flex items-center justify-between mb-1 gap-2">
                          <span
                            className={`font-sans text-sm truncate ${isMe ? 'text-primary font-semibold' : 'text-text-primary'}`}
                          >
                            {b.answer}
                            {isMe && (
                              <span className="ml-2 font-mono text-[9px] uppercase tracking-[0.15em] text-primary bg-primary/10 border border-primary/30 px-1.5 py-0.5 rounded-sm">
                                you
                              </span>
                            )}
                          </span>
                          <span className="font-mono text-xs text-text-muted shrink-0 tabular-nums">
                            {b.count} / {globalData.total_players}
                          </span>
                        </div>
                        <div className="h-1.5 rounded-full bg-surface-elevated overflow-hidden">
                          <div
                            className={`h-full rounded-full transition-all ${isMe ? 'bg-primary' : 'bg-border'}`}
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Admin award panel (visible to admin role only, post-lock)
// ---------------------------------------------------------------------------

function AdminAwardPanel({ teams }: { teams: TeamOption[] }) {
  const [awardingType, setAwardingType] = useState<SpecialType | null>(null);
  const [winnerTeamId, setWinnerTeamId] = useState<string>('');
  const [winnerPlayerId, setWinnerPlayerId] = useState<string>('');
  const [winnerPlayerName, setWinnerPlayerName] = useState<string>('');
  const queryClient = useQueryClient();

  const awardMutation = useMutation({
    mutationFn: ({
      ptype,
      teamId,
      playerId,
    }: {
      ptype: SpecialType;
      teamId: string | null;
      playerId: string | null;
    }) =>
      apiFetch('/api/v1/admin/specials/award', {
        method: 'POST',
        body: JSON.stringify({
          prediction_type: ptype,
          winner_team_id: teamId ?? undefined,
          winner_player_id: playerId ?? undefined,
        }),
      }),
    onSuccess: (_data, vars) => {
      toast.success(`${SPECIAL_META[vars.ptype].label} awarded!`);
      queryClient.invalidateQueries({ queryKey: ['specials'] });
      setAwardingType(null);
      setWinnerTeamId('');
      setWinnerPlayerId('');
      setWinnerPlayerName('');
    },
    onError: () => {
      toast.error('Award failed. Check the console.');
    },
  });

  async function handleAward(ptype: SpecialType) {
    const isTeam = TEAM_SPECIALS.has(ptype);
    if (isTeam && !winnerTeamId) {
      toast.error('Select a winning team first.');
      return;
    }
    if (!isTeam && !winnerPlayerId) {
      toast.error('Select a winning player first.');
      return;
    }
    await awardMutation.mutateAsync({
      ptype,
      teamId: isTeam ? winnerTeamId : null,
      playerId: isTeam ? null : winnerPlayerId,
    });
  }

  return (
    <div className="mt-10 border-t border-border pt-6">
      <h2 className="font-sans font-semibold text-lg text-text-primary tracking-tight mb-1">Award Specials</h2>
      <p className="text-text-muted text-sm font-sans mb-4">Admin only — award points at tournament end.</p>
      <div className="flex flex-col gap-3">
        {ORDER.map((ptype) => {
          const isTeam = TEAM_SPECIALS.has(ptype);
          const isActive = awardingType === ptype;
          const positionFilter = SPECIAL_POSITION_FILTER[ptype];
          return (
            <div key={ptype} className="rounded-lg border border-border bg-surface p-4">
              <div className="flex items-center gap-2 mb-3">
                <span className="text-primary">{SPECIAL_META[ptype].icon}</span>
                <span className="font-sans font-semibold text-sm text-text-primary">{SPECIAL_META[ptype].label}</span>
                <Badge variant="muted" className="ml-auto">{SPECIAL_POINTS[ptype]} pts</Badge>
              </div>
              {isActive ? (
                <div className="flex gap-2 items-end flex-wrap">
                  <div className="flex-1 min-w-0">
                    {isTeam ? (
                      <Select value={winnerTeamId} onValueChange={setWinnerTeamId} disabled={awardMutation.isPending}>
                        <SelectTrigger aria-label={`Winning team for ${SPECIAL_META[ptype].label}`}>
                          <SelectValue placeholder="— Select winning team —" />
                        </SelectTrigger>
                        <SelectContent>
                          {teams.map((t) => (
                            <SelectItem key={t.id} value={t.id}>
                              {t.flag_emoji} {t.name}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    ) : (
                      <PlayerCombobox
                        value={winnerPlayerId}
                        onChange={(id, name) => { setWinnerPlayerId(id); setWinnerPlayerName(name); }}
                        displayName={winnerPlayerName}
                        disabled={awardMutation.isPending}
                        placeholder="Search for the winner…"
                        aria-label={`Winner for ${SPECIAL_META[ptype].label}`}
                        position={positionFilter}
                      />
                    )}
                  </div>
                  <SaveButton
                    type="button"
                    onClick={() => handleAward(ptype)}
                    state={awardMutation.isPending ? 'saving' : 'idle'}
                    idleLabel="Award"
                    savedLabel="Awarded"
                    className="whitespace-nowrap"
                  />
                  <button
                    type="button"
                    onClick={() => { setAwardingType(null); setWinnerTeamId(''); setWinnerPlayerId(''); setWinnerPlayerName(''); }}
                    className="text-sm text-text-muted underline"
                  >
                    Cancel
                  </button>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={() => { setAwardingType(ptype); setWinnerTeamId(''); setWinnerPlayerId(''); setWinnerPlayerName(''); }}
                  className="text-sm font-sans text-primary underline"
                >
                  Set winner & award
                </button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// SpecialsPage
// ---------------------------------------------------------------------------

export function SpecialsPage() {
  const { player } = useAuth();

  const { data: mySpecials } = useQuery({
    queryKey: ['specials', 'me'],
    queryFn: () => apiFetch<MySpecialsResponse>('/api/v1/specials'),
  });

  const { data: groups } = useQuery({
    queryKey: ['groups'],
    queryFn: () => apiFetch<GroupResponse[]>('/api/v1/groups'),
  });

  const { data: globalSpecials } = useQuery({
    queryKey: ['specials', 'global'],
    queryFn: () => apiFetch<GlobalSpecialsResponse>('/api/v1/specials/global'),
    enabled: mySpecials?.is_locked === true,
    staleTime: 5 * 60_000,
  });

  const teams = groups ? teamsFromGroups(groups) : [];
  const submittedCount = mySpecials?.predictions.filter((p) => p.submitted_at != null).length ?? 0;

  return (
    <div>
      <PageHeader
        title="Tournament Specials"
        eyebrow="Pre-tournament bonus"
        action={
          <span className="inline-flex items-center px-2.5 py-1 rounded-full bg-surface-elevated border border-border font-mono text-[10px] uppercase tracking-[0.2em] text-text-secondary tabular-nums">
            {submittedCount}/{ORDER.length}
          </span>
        }
      />
      <PredictionsSubNav />
      <p className="text-text-secondary font-sans text-sm mb-5">
        Pre-tournament bonus predictions. Worth up to 80 extra points.
      </p>

      <SpecialsForm />

      {mySpecials?.is_locked && globalSpecials && mySpecials && (
        <GlobalComparisonView global={globalSpecials} mySpecials={mySpecials} />
      )}

      {player?.role === 'admin' && (
        <AdminAwardPanel teams={teams} />
      )}
    </div>
  );
}
