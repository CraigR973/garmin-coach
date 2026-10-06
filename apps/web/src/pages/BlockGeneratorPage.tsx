import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  blockGeneratorEnvelopeSchema,
  blockLockEnvelopeSchema,
  type BlockProgressionProposal,
  type GeneratedBlockDraft,
  type GeneratedBlockWorkout,
} from '@coach/shared';
import { Check, Hammer, Lock, Pencil, Sparkles, Trash2, TrendingUp } from 'lucide-react';
import { toast } from 'sonner';
import { PageHeader } from '@/components/PageHeader';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { apiFetch } from '@/lib/api';
import {
  ACCEPT_PLAN,
  DECLINE_PLAN,
  DECLINED,
  MADE,
  MAKE_PLAN_BUTTON,
  MAKE_PLAN_LINE,
  MAKE_PLAN_TITLE,
  WHY_THIS_PLAN,
  acceptedLine,
  lockedTitle,
  planSpan,
  sessionDay,
} from '@/lib/nextPlan';

const BASE = '/api/v1/block-generator';

async function fetchDraft() {
  const response = await apiFetch<unknown>(BASE);
  return blockGeneratorEnvelopeSchema.parse(response);
}

function formatDate(value: string): string {
  return new Date(`${value}T00:00:00`).toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'short',
  });
}

/** A draft made before Batch 323 has no plan name. */
function planNameOf(draft: GeneratedBlockDraft): string {
  return draft.planName ?? 'Your plan';
}

interface RefineState {
  weekNumber: number;
  dayOffset: number;
  /** Batch 323: which of the day's sessions (his Saturday carries two). */
  slot: number;
  title: string;
  plannedDurationMin: string;
  intensityTarget: string;
}

const inputClass =
  'flex h-9 w-full rounded-md border border-border bg-bg px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:shadow-glow';

export function BlockGeneratorPage() {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState<RefineState | null>(null);

  const query = useQuery({ queryKey: ['block-generator'], queryFn: fetchDraft });
  // Batch 323: Home's next-plan card reads the daily loop, so a decision refreshes it.
  const invalidate = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: ['block-generator'] }),
      queryClient.invalidateQueries({ queryKey: ['daily-loop'] }),
    ]);

  // Batch 323: the next plan is built from his last one, starting the day after it ends
  // with his FTP as it stands, so the builder asks for neither a start date nor an FTP.
  const generateMutation = useMutation({
    mutationFn: async () => {
      const response = await apiFetch<unknown>(`${BASE}/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      return blockGeneratorEnvelopeSchema.parse(response);
    },
    onSuccess: async () => {
      await invalidate();
      toast.success(MADE);
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : 'Could not make the plan'),
  });

  const refineMutation = useMutation({
    mutationFn: async (state: RefineState) => {
      const response = await apiFetch<unknown>(`${BASE}/refine`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          weekNumber: state.weekNumber,
          dayOffset: state.dayOffset,
          slot: state.slot,
          title: state.title,
          plannedDurationMin: state.plannedDurationMin ? Number(state.plannedDurationMin) : null,
          intensityTarget: state.intensityTarget || null,
        }),
      });
      return blockGeneratorEnvelopeSchema.parse(response);
    },
    onSuccess: async () => {
      await invalidate();
      setEditing(null);
      toast.success('Day updated.');
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : 'Failed to refine day'),
  });

  const lockMutation = useMutation({
    mutationFn: async () => {
      const response = await apiFetch<unknown>(`${BASE}/lock`, { method: 'POST' });
      return blockLockEnvelopeSchema.parse(response);
    },
    onSuccess: async () => {
      const name = query.data?.data.draft ? planNameOf(query.data.data.draft) : 'Your plan';
      await invalidate();
      toast.success(acceptedLine(name));
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : 'Could not accept the plan'),
  });

  const discardMutation = useMutation({
    mutationFn: async () => {
      await apiFetch<unknown>(`${BASE}/discard`, { method: 'POST' });
    },
    onSuccess: async () => {
      await invalidate();
      setEditing(null);
      toast.success(DECLINED);
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : 'Could not decline the plan'),
  });

  if (query.isLoading) {
    return (
      <div className="space-y-6">
        <PageHeader title="Plan builder" />
        <Card>
          <CardHeader>
            <CardTitle>Loading…</CardTitle>
          </CardHeader>
        </Card>
      </div>
    );
  }

  if (query.isError || !query.data) {
    return (
      <div className="space-y-6">
        <PageHeader title="Plan builder" />
        <Card>
          <CardHeader>
            <CardTitle>Block builder unavailable</CardTitle>
            <CardDescription>
              {query.error instanceof Error ? query.error.message : 'Could not load the draft.'}
            </CardDescription>
          </CardHeader>
        </Card>
      </div>
    );
  }

  const { draft, canGenerate } = query.data.data;
  const isDraft = draft?.status === 'draft';

  return (
    <div className="space-y-6">
      <PageHeader title="Plan builder" />

      {canGenerate && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-primary" aria-hidden />
              {MAKE_PLAN_TITLE}
            </CardTitle>
            <CardDescription>{MAKE_PLAN_LINE}</CardDescription>
          </CardHeader>
          <CardContent className="flex justify-end">
            <Button
              type="button"
              onClick={() => generateMutation.mutate()}
              disabled={generateMutation.isPending}
            >
              <Hammer className="mr-2 h-4 w-4" aria-hidden />
              {MAKE_PLAN_BUTTON}
            </Button>
          </CardContent>
        </Card>
      )}

      {draft?.status === 'locked' && (
        <Card className="border-success/40 bg-success/5">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Lock className="h-4 w-4 text-success" aria-hidden />
              {lockedTitle(planNameOf(draft))}
            </CardTitle>
            <CardDescription>{planSpan(draft.startDate, draft.endDate)}</CardDescription>
          </CardHeader>
        </Card>
      )}

      {isDraft && draft && (
        <DraftView
          draft={draft}
          editing={editing}
          onEdit={setEditing}
          onEditChange={setEditing}
          onSaveEdit={() => editing && refineMutation.mutate(editing)}
          savingEdit={refineMutation.isPending}
          onLock={() => lockMutation.mutate()}
          locking={lockMutation.isPending}
          onDiscard={() => discardMutation.mutate()}
          discarding={discardMutation.isPending}
        />
      )}
    </div>
  );
}

interface DraftViewProps {
  draft: GeneratedBlockDraft;
  editing: RefineState | null;
  onEdit: (state: RefineState) => void;
  onEditChange: (state: RefineState) => void;
  onSaveEdit: () => void;
  savingEdit: boolean;
  onLock: () => void;
  locking: boolean;
  onDiscard: () => void;
  discarding: boolean;
}

function DraftView({
  draft,
  editing,
  onEdit,
  onEditChange,
  onSaveEdit,
  savingEdit,
  onLock,
  locking,
  onDiscard,
  discarding,
}: DraftViewProps) {
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle>{planNameOf(draft)}</CardTitle>
              <CardDescription className="mt-1">
                {planSpan(draft.startDate, draft.endDate)}
              </CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {draft.whyThisPlan && draft.whyThisPlan.length > 0 ? (
            <div className="space-y-2">
              <p className="text-sm font-medium text-text-primary">{WHY_THIS_PLAN}</p>
              <ul className="list-disc space-y-1 pl-5 text-sm leading-6 text-text-secondary">
                {draft.whyThisPlan.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </div>
          ) : null}
          <div className="flex flex-wrap gap-2">
            <Button type="button" onClick={onLock} disabled={locking}>
              <Check className="mr-2 h-4 w-4" aria-hidden />
              {ACCEPT_PLAN}
            </Button>
            <Button type="button" variant="outline" onClick={onDiscard} disabled={discarding}>
              <Trash2 className="mr-2 h-4 w-4" aria-hidden />
              {DECLINE_PLAN}
            </Button>
          </div>
        </CardContent>
      </Card>

      {draft.progressionProposal && (
        <ProgressionProposalPanel proposal={draft.progressionProposal} />
      )}

      {draft.weeks.map((week) => (
        <Card key={week.weekNumber}>
          <CardHeader>
            <CardTitle className="flex items-center justify-between gap-2 text-base">
              <span>
                Week {week.weekNumber} · {week.label}
              </span>
              <span className="text-xs font-normal text-text-muted">
                {formatDate(week.startDate)}–{formatDate(week.endDate)}
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-2">
              {week.workouts.map((workout) => {
                const slot = workout.slot ?? 0;
                const isEditing =
                  editing?.weekNumber === week.weekNumber &&
                  editing?.dayOffset === workout.dayOffset &&
                  editing?.slot === slot;
                return (
                  <li
                    key={`${workout.dayOffset}-${slot}`}
                    className="rounded-lg border border-border px-3 py-2 text-sm"
                  >
                    {isEditing && editing ? (
                      <div className="space-y-2">
                        <input
                          aria-label="Workout title"
                          value={editing.title}
                          onChange={(e) => onEditChange({ ...editing, title: e.target.value })}
                          className={inputClass}
                        />
                        <div className="grid grid-cols-2 gap-2">
                          <input
                            aria-label="Duration minutes"
                            type="number"
                            min={1}
                            value={editing.plannedDurationMin}
                            onChange={(e) =>
                              onEditChange({ ...editing, plannedDurationMin: e.target.value })
                            }
                            className={inputClass}
                          />
                          <input
                            aria-label="Intensity target"
                            value={editing.intensityTarget}
                            onChange={(e) =>
                              onEditChange({ ...editing, intensityTarget: e.target.value })
                            }
                            className={inputClass}
                          />
                        </div>
                        <div className="flex justify-end gap-2">
                          <Button
                            type="button"
                            size="sm"
                            onClick={onSaveEdit}
                            disabled={savingEdit}
                          >
                            {savingEdit ? 'Saving…' : 'Save'}
                          </Button>
                        </div>
                      </div>
                    ) : (
                      <div className="flex items-center justify-between gap-2">
                        <div>
                          <p className="text-xs text-text-muted">{sessionDay(workout.workoutDate)}</p>
                          <p className="font-medium text-text-primary">{workout.title}</p>
                          <p className="text-xs text-text-muted">
                            {workout.plannedDurationMin ? `${workout.plannedDurationMin} min` : ''}
                            {workout.plannedDurationMin && workout.intensityTarget ? ' · ' : ''}
                            {workout.intensityTarget ?? ''}
                          </p>
                        </div>
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          aria-label={`Edit ${workout.title}`}
                          onClick={() => onEdit(toRefineState(week.weekNumber, workout))}
                        >
                          <Pencil className="h-4 w-4" aria-hidden />
                        </Button>
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function ProgressionProposalPanel({ proposal }: { proposal: BlockProgressionProposal }) {
  const change = proposal.ftpChangeWatts;
  const changeLabel = change > 0 ? `+${change}w` : `${change}w`;
  return (
    <Card className="border-primary/30 bg-primary/5">
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <TrendingUp className="h-4 w-4 text-primary" aria-hidden />
              Last-block proposal
            </CardTitle>
            <CardDescription className="mt-1">{proposal.summary}</CardDescription>
          </div>
          <Badge variant={proposal.status === 'ready' ? 'default' : 'muted'}>
            {proposal.status === 'ready' ? changeLabel : 'Fallback'}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <div className="grid gap-3 sm:grid-cols-3">
          <div>
            <p className="text-xs uppercase text-text-muted">FTP seed</p>
            <p className="font-medium text-text-primary">
              {proposal.currentFtpWatts}w → {proposal.recommendedFtpWatts}w
            </p>
          </div>
          <div className="sm:col-span-2">
            <p className="text-xs uppercase text-text-muted">Focus</p>
            <p className="font-medium text-text-primary">{proposal.focus}</p>
          </div>
        </div>
        {proposal.structuralNudge && (
          <p className="rounded-md border border-border bg-surface/80 px-3 py-2 text-text-secondary">
            {proposal.structuralNudge}
          </p>
        )}
        {proposal.evidence.length > 0 && (
          <ul className="space-y-1 text-text-muted">
            {proposal.evidence.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function toRefineState(weekNumber: number, workout: GeneratedBlockWorkout): RefineState {
  return {
    weekNumber,
    dayOffset: workout.dayOffset,
    slot: workout.slot ?? 0,
    title: workout.title,
    plannedDurationMin: workout.plannedDurationMin ? String(workout.plannedDurationMin) : '',
    intensityTarget: workout.intensityTarget ?? '',
  };
}
