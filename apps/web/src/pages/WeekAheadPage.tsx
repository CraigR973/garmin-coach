import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { dailyLoopEnvelopeSchema, weekAheadEnvelopeSchema } from '@coach/shared';
import { Activity, Bike, CheckCircle2, Dumbbell, Moon, Send, Sparkles, ThumbsUp } from 'lucide-react';
import { toast } from 'sonner';
import { PageHeader } from '@/components/PageHeader';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { verdictLabel } from '@/lib/copy';
import { apiFetch } from '@/lib/api';
import { cn } from '@/lib/utils';

type WeekAheadEnvelope = typeof weekAheadEnvelopeSchema._type;
type WeekAheadWorkout = WeekAheadEnvelope['data']['workouts'][number];
type WorkoutProposal = NonNullable<WeekAheadWorkout['proposal']>;

const BASE = '/api/v1/workout-delivery';

// Mark's fixed weekly structure (handover §4). The exact VO₂ / Sweet-Spot
// sessions progress through the 13-week block, but the day pattern doesn't
// change — so this is a stable, at-a-glance reference for his week.
interface ShapeDay {
  dow: number; // JS getDay(): 0 = Sunday
  name: string;
  cycling: string;
  rest?: boolean;
  extras: string[];
}

const WEEKLY_SHAPE: ShapeDay[] = [
  { dow: 1, name: 'Monday', cycling: 'Rest day', rest: true, extras: ['Dumbbells 20 min', 'Flexibility 16 min'] },
  { dow: 2, name: 'Tuesday', cycling: 'VO₂ max', extras: ['Flexibility 16 min'] },
  { dow: 3, name: 'Wednesday', cycling: 'Endurance · Z2 60 min', extras: ['Flexibility 16 min'] },
  { dow: 4, name: 'Thursday', cycling: 'Sweet spot', extras: ['Flexibility 16 min'] },
  { dow: 5, name: 'Friday', cycling: 'Rest day', rest: true, extras: ['Flexibility 16 min'] },
  { dow: 6, name: 'Saturday', cycling: 'Z2 + sprints', extras: ['Bodyweight 15 min', 'Flexibility 16 min'] },
  { dow: 0, name: 'Sunday', cycling: 'Long Z2 · 90–125 min', extras: ['Flexibility 16 min'] },
];

function verdictBadgeVariant(verdict: string | null | undefined): 'success' | 'warning' | 'error' | 'muted' {
  if (verdict === 'green') return 'success';
  if (verdict === 'amber') return 'warning';
  if (verdict === 'red') return 'error';
  return 'muted';
}

// Plain-English delivery status — no "proposed/IR/push" jargon.
function statusLabel(proposal: WorkoutProposal | null): string {
  if (!proposal) return 'Not set up';
  switch (proposal.status) {
    case 'pushed':
      return 'Sent to Zwift';
    case 'approved':
      return 'Approved';
    case 'failed':
      return 'Send failed';
    case 'proposed':
      return 'Ready to review';
    default:
      return proposal.status;
  }
}

function statusVariant(status: string | undefined): 'success' | 'warning' | 'error' | 'accent' | 'muted' {
  if (status === 'pushed') return 'success';
  if (status === 'approved') return 'warning';
  if (status === 'failed') return 'error';
  if (status === 'proposed') return 'accent';
  return 'muted';
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
  if (typeof a.durationScalePct === 'number') parts.push(`${a.durationScalePct}% of the duration`);
  if (typeof a.zoneDropPct === 'number' && a.zoneDropPct > 0) parts.push('down a zone');
  if (a.removedHit === true) parts.push('HIT removed');
  return parts.length ? parts.join(' · ') : null;
}

async function fetchWeekAhead() {
  const response = await apiFetch<unknown>(`${BASE}/week-ahead`);
  return weekAheadEnvelopeSchema.parse(response);
}

async function fetchDailyLoop() {
  const response = await apiFetch<unknown>('/api/v1/daily-loop');
  return dailyLoopEnvelopeSchema.parse(response);
}

export function WeekAheadPage() {
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ['week-ahead'], queryFn: fetchWeekAhead });
  // Reuse the cached daily-loop to light up today's row with its verdict.
  const todayQuery = useQuery({ queryKey: ['daily-loop'], queryFn: fetchDailyLoop, retry: false });

  const todayDow = new Date().getDay();
  const todayVerdict = todayQuery.data?.data.morningAnalysis?.verdict ?? null;

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['week-ahead'] });

  const proposeMutation = useMutation({
    mutationFn: (plannedWorkoutId: string) =>
      apiFetch(`${BASE}/planned-workouts/${plannedWorkoutId}/proposals`, { method: 'POST' }),
    onSuccess: async () => {
      await invalidate();
      toast.success('Ready — approve it to send to Zwift');
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : 'Could not prepare it'),
  });

  const approveMutation = useMutation({
    mutationFn: (proposalId: string) => apiFetch(`${BASE}/proposals/${proposalId}/approve`, { method: 'POST' }),
    onSuccess: async () => {
      await invalidate();
      toast.success('Approved — Home sends today’s ride when you are ready');
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : 'Could not approve'),
  });

  const pushMutation = useMutation({
    mutationFn: (proposalId: string) => apiFetch(`${BASE}/proposals/${proposalId}/push`, { method: 'POST' }),
    onSuccess: async () => {
      await invalidate();
      toast.success('Sent to Zwift');
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : 'Could not send'),
  });

  return (
    <div className="space-y-5">
      <PageHeader title="Plan" />

      {/* Your week at a glance */}
      <Card>
        <CardHeader>
          <CardTitle>Your training week</CardTitle>
          <CardDescription>Your fixed weekly shape. The hard sessions progress through the block.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          {WEEKLY_SHAPE.map((day) => {
            const isToday = day.dow === todayDow;
            return (
              <div
                key={day.dow}
                className={cn(
                  'flex items-start gap-3 rounded-xl border px-3 py-3',
                  isToday ? 'border-primary/50 bg-primary/5' : 'border-border bg-bg',
                )}
              >
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-surface-elevated">
                  {day.rest ? (
                    <Moon className="h-4 w-4 text-text-muted" aria-hidden />
                  ) : (
                    <Bike className="h-4 w-4 text-primary" aria-hidden />
                  )}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium text-text-primary">{day.name}</span>
                    {isToday && <Badge variant="default">Today</Badge>}
                    {isToday && todayVerdict && (
                      <Badge variant={verdictBadgeVariant(todayVerdict)}>{verdictLabel(todayVerdict)}</Badge>
                    )}
                  </div>
                  <p className={cn('text-sm', day.rest ? 'text-text-muted' : 'text-text-secondary')}>{day.cycling}</p>
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    {day.extras.map((extra) => (
                      <span
                        key={extra}
                        className="inline-flex items-center gap-1 rounded-full border border-border bg-surface px-2 py-0.5 text-xs text-text-secondary"
                      >
                        {/dumbbell|bodyweight/i.test(extra) ? (
                          <Dumbbell className="h-3 w-3" aria-hidden />
                        ) : (
                          <Activity className="h-3 w-3" aria-hidden />
                        )}
                        {extra}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            );
          })}
        </CardContent>
      </Card>

      {/* Send to Zwift */}
      <div>
        <PageHeader title="Send to Zwift" className="mb-3" />
        <Card className="bg-surface-elevated/60">
          <CardContent className="pt-6">
            <p className="text-sm text-text-secondary">
              Your bike sessions can go straight to Zwift. On an easier day the coach trims the
              workout for you — nothing is sent until you approve it.
            </p>
          </CardContent>
        </Card>
      </div>

      {query.isLoading ? (
        <Card>
          <CardHeader>
            <CardTitle>Loading your rides…</CardTitle>
          </CardHeader>
        </Card>
      ) : query.isError || !query.data ? (
        <Card>
          <CardHeader>
            <CardTitle>Rides couldn&apos;t load</CardTitle>
            <CardDescription>
              {query.error instanceof Error ? query.error.message : 'Please try again in a moment.'}
            </CardDescription>
          </CardHeader>
        </Card>
      ) : query.data.data.workouts.length === 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>No bike rides this week</CardTitle>
            <CardDescription>There are no cycling sessions to send to Zwift right now.</CardDescription>
          </CardHeader>
        </Card>
      ) : (
        <div className="space-y-4">
          {query.data.data.workouts.map((workout) => {
            const proposal = workout.proposal;
            const ir = proposal?.structuredWorkoutIr as Record<string, unknown> | undefined;
            const origin = irOrigin(ir);
            const adjusted = origin === 'amber_regeneration' || origin === 'red_substitution';
            const summary = adjustmentSummary(ir);
            const proposeBusy = proposeMutation.isPending && proposeMutation.variables === workout.plannedWorkoutId;
            const approveBusy = approveMutation.isPending && approveMutation.variables === proposal?.id;
            const pushBusy = pushMutation.isPending && pushMutation.variables === proposal?.id;

            return (
              <Card key={workout.plannedWorkoutId}>
                <CardContent className="space-y-4 pt-6">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <p className="font-semibold text-text-primary">{workout.title}</p>
                      <p className="text-sm text-text-secondary">
                        {formatDate(workout.workoutDate)}
                        {workout.plannedDurationMin ? ` · ${workout.plannedDurationMin} min` : ''}
                        {workout.intensityTarget ? ` · ${workout.intensityTarget}` : ''}
                      </p>
                    </div>
                    <div className="flex flex-col items-end gap-2">
                      <Badge variant={statusVariant(proposal?.status)}>{statusLabel(proposal ?? null)}</Badge>
                      {adjusted ? (
                        <Badge variant="warning" className="gap-1">
                          <Sparkles className="h-3 w-3" aria-hidden />
                          {origin === 'red_substitution' ? 'Recovery swap' : 'Eased for recovery'}
                        </Badge>
                      ) : null}
                    </div>
                  </div>

                  {summary ? (
                    <p className="rounded-lg border border-border bg-bg px-3 py-2 text-xs text-text-secondary">
                      Trimmed to {summary}.
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
                      Sent to Zwift
                    </p>
                  ) : (
                    <div className="flex flex-wrap justify-end gap-2">
                      {!proposal ? (
                        <Button
                          type="button"
                          onClick={() => proposeMutation.mutate(workout.plannedWorkoutId)}
                          disabled={proposeBusy}
                        >
                          Prepare for Zwift
                        </Button>
                      ) : null}
                      {proposal?.status === 'proposed' ? (
                        <Button type="button" onClick={() => approveMutation.mutate(proposal.id)} disabled={approveBusy}>
                          <ThumbsUp className="mr-2 h-4 w-4" aria-hidden />
                          Approve
                        </Button>
                      ) : null}
                      {proposal && (proposal.status === 'approved' || proposal.status === 'failed') ? (
                        <Button type="button" onClick={() => pushMutation.mutate(proposal.id)} disabled={pushBusy}>
                          <Send className="mr-2 h-4 w-4" aria-hidden />
                          {proposal.status === 'failed' ? 'Try again' : 'Send now'}
                        </Button>
                      ) : null}
                    </div>
                  )}

                  {proposal?.status === 'approved' ? (
                    <p className="text-right text-xs text-text-muted">
                      Approved. Use Home to send today&apos;s ride when you are ready.
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
