import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { weekAheadEnvelopeSchema } from '@coach/shared';
import { CalendarCheck, CheckCircle2, Send, Sparkles, ThumbsUp } from 'lucide-react';
import { toast } from 'sonner';
import { PageHeader } from '@/components/PageHeader';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { apiFetch } from '@/lib/api';

type WeekAheadEnvelope = typeof weekAheadEnvelopeSchema._type;
type WeekAheadWorkout = WeekAheadEnvelope['data']['workouts'][number];
type WorkoutProposal = NonNullable<WeekAheadWorkout['proposal']>;

const BASE = '/api/v1/workout-delivery';

async function fetchWeekAhead() {
  const response = await apiFetch<unknown>(`${BASE}/week-ahead`);
  return weekAheadEnvelopeSchema.parse(response);
}

function statusVariant(status: string): 'success' | 'warning' | 'error' | 'accent' | 'muted' {
  if (status === 'pushed') return 'success';
  if (status === 'approved') return 'warning';
  if (status === 'failed') return 'error';
  if (status === 'proposed') return 'accent';
  return 'muted';
}

function statusLabel(proposal: WorkoutProposal | null): string {
  if (!proposal) return 'Not proposed';
  if (proposal.status === 'pushed') return 'Delivered';
  return proposal.status.charAt(0).toUpperCase() + proposal.status.slice(1);
}

function formatDate(value: string): string {
  return new Date(`${value}T00:00:00`).toLocaleDateString(undefined, {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
  });
}

function irOrigin(ir: Record<string, unknown> | undefined): string | null {
  return ir && typeof ir.origin === 'string' ? ir.origin : null;
}

function adjustmentSummary(ir: Record<string, unknown> | undefined): string | null {
  const adjustment = ir?.adjustment;
  if (!adjustment || typeof adjustment !== 'object') return null;
  const a = adjustment as Record<string, unknown>;
  if (a.changed !== true) return null;
  const parts: string[] = [];
  if (typeof a.durationScalePct === 'number') parts.push(`${a.durationScalePct}% duration`);
  if (typeof a.zoneDropPct === 'number' && a.zoneDropPct > 0) parts.push(`down a zone`);
  if (a.removedHit === true) parts.push('HIT removed');
  return parts.length ? parts.join(' · ') : null;
}

export function WeekAheadPage() {
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ['week-ahead'], queryFn: fetchWeekAhead });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['week-ahead'] });

  const proposeMutation = useMutation({
    mutationFn: (plannedWorkoutId: string) =>
      apiFetch(`${BASE}/planned-workouts/${plannedWorkoutId}/proposals`, { method: 'POST' }),
    onSuccess: async () => {
      await invalidate();
      toast.success('Workout proposed — approve to send it to Zwift');
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : 'Failed to propose'),
  });

  const approveMutation = useMutation({
    mutationFn: (proposalId: string) =>
      apiFetch(`${BASE}/proposals/${proposalId}/approve`, { method: 'POST' }),
    onSuccess: async () => {
      await invalidate();
      toast.success('Approved — it auto-pushes to Zwift a couple of days ahead');
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : 'Failed to approve'),
  });

  const pushMutation = useMutation({
    mutationFn: (proposalId: string) =>
      apiFetch(`${BASE}/proposals/${proposalId}/push`, { method: 'POST' }),
    onSuccess: async () => {
      await invalidate();
      toast.success('Pushed to Zwift');
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : 'Failed to push'),
  });

  if (query.isLoading) {
    return (
      <div className="space-y-6">
        <PageHeader title="Week ahead" eyebrow="Plan delivery" />
        <Card>
          <CardHeader>
            <CardTitle>Loading the week ahead…</CardTitle>
          </CardHeader>
        </Card>
      </div>
    );
  }

  if (query.isError || !query.data) {
    return (
      <div className="space-y-6">
        <PageHeader title="Week ahead" eyebrow="Plan delivery" />
        <Card>
          <CardHeader>
            <CardTitle>Week ahead unavailable</CardTitle>
            <CardDescription>
              {query.error instanceof Error ? query.error.message : 'The plan could not be loaded.'}
            </CardDescription>
          </CardHeader>
        </Card>
      </div>
    );
  }

  const workouts = query.data.data.workouts;

  return (
    <div className="space-y-6">
      <PageHeader title="Week ahead" eyebrow="Plan delivery" />

      <Card className="bg-surface-elevated/60">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <CalendarCheck className="h-4 w-4 text-primary" aria-hidden />
            Propose → approve → auto-push
          </CardTitle>
          <CardDescription>
            On an Amber morning the coach regenerates an adjusted workout for you. Nothing reaches
            Zwift until you approve it; approved rides auto-push a couple of days ahead.
          </CardDescription>
        </CardHeader>
      </Card>

      {workouts.length === 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>No deliverable rides</CardTitle>
            <CardDescription>There are no bike workouts in the week ahead to deliver.</CardDescription>
          </CardHeader>
        </Card>
      ) : (
        <div className="space-y-4">
          {workouts.map((workout) => {
            const proposal = workout.proposal;
            const ir = proposal?.structuredWorkoutIr as Record<string, unknown> | undefined;
            const origin = irOrigin(ir);
            const adjusted = origin === 'amber_regeneration' || origin === 'red_substitution';
            const summary = adjustmentSummary(ir);
            const proposeBusy =
              proposeMutation.isPending && proposeMutation.variables === workout.plannedWorkoutId;
            const approveBusy =
              approveMutation.isPending && approveMutation.variables === proposal?.id;
            const pushBusy = pushMutation.isPending && pushMutation.variables === proposal?.id;

            return (
              <Card key={workout.plannedWorkoutId}>
                <CardContent className="space-y-4 pt-6">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <p className="text-base font-semibold text-text-primary">{workout.title}</p>
                      <p className="text-sm text-text-secondary">
                        {formatDate(workout.workoutDate)} · {workout.workoutType}
                        {workout.plannedDurationMin ? ` · ${workout.plannedDurationMin} min` : ''}
                        {workout.intensityTarget ? ` · ${workout.intensityTarget}` : ''}
                      </p>
                    </div>
                    <div className="flex flex-col items-end gap-2">
                      <Badge variant={statusVariant(proposal?.status ?? 'none')}>
                        {statusLabel(proposal ?? null)}
                      </Badge>
                      {adjusted ? (
                        <Badge variant="warning" className="gap-1">
                          <Sparkles className="h-3 w-3" aria-hidden />
                          {origin === 'red_substitution' ? 'Recovery sub' : 'Amber-adjusted'}
                        </Badge>
                      ) : null}
                    </div>
                  </div>

                  {summary ? (
                    <p className="rounded-lg border border-border bg-bg px-3 py-2 text-xs text-text-secondary">
                      Adjusted: {summary}
                    </p>
                  ) : null}

                  {proposal?.status === 'failed' && proposal.lastError ? (
                    <p className="rounded-lg border border-error/40 bg-error/10 px-3 py-2 text-xs text-error">
                      {proposal.lastError}
                    </p>
                  ) : null}

                  {proposal?.status === 'pushed' ? (
                    <p className="flex items-center gap-2 text-sm text-success">
                      <CheckCircle2 className="h-4 w-4" aria-hidden />
                      Delivered to Zwift
                      {proposal.intervalsEventId ? ` · event ${proposal.intervalsEventId}` : ''}
                    </p>
                  ) : (
                    <div className="flex flex-wrap justify-end gap-2">
                      {!proposal ? (
                        <Button
                          type="button"
                          onClick={() => proposeMutation.mutate(workout.plannedWorkoutId)}
                          disabled={proposeBusy}
                        >
                          Propose
                        </Button>
                      ) : null}
                      {proposal?.status === 'proposed' ? (
                        <Button
                          type="button"
                          onClick={() => approveMutation.mutate(proposal.id)}
                          disabled={approveBusy}
                        >
                          <ThumbsUp className="mr-2 h-4 w-4" aria-hidden />
                          Approve
                        </Button>
                      ) : null}
                      {proposal && (proposal.status === 'approved' || proposal.status === 'failed') ? (
                        <Button
                          type="button"
                          onClick={() => pushMutation.mutate(proposal.id)}
                          disabled={pushBusy}
                        >
                          <Send className="mr-2 h-4 w-4" aria-hidden />
                          {proposal.status === 'failed' ? 'Retry push' : 'Push now'}
                        </Button>
                      ) : null}
                    </div>
                  )}

                  {proposal?.status === 'approved' ? (
                    <p className="text-right text-xs text-text-muted">
                      Auto-pushes to Zwift when it is a couple of days out.
                    </p>
                  ) : null}
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
