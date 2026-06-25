import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  dailyLoopEnvelopeSchema,
  manualEntryInputSchema,
  plannedWorkoutAdherenceInputSchema,
} from '@coach/shared';
import { Activity, Bike, ClipboardCheck, ShieldAlert, Thermometer, Wind } from 'lucide-react';
import { toast } from 'sonner';
import { PageHeader } from '@/components/PageHeader';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useAuth } from '@/contexts/AuthContext';
import { apiFetch } from '@/lib/api';
import { useOnlineStatus } from '@/hooks/useOnlineStatus';

const textareaClassName =
  'min-h-[120px] w-full rounded-md border border-border bg-bg px-3 py-3 text-sm text-text-primary shadow-sm focus-visible:outline-none focus-visible:shadow-glow';

type DailyLoopEnvelope = typeof dailyLoopEnvelopeSchema._type;
type DailyLoopData = DailyLoopEnvelope['data'];

type ManualFormState = {
  bpSystolic: string;
  bpDiastolic: string;
  subjectiveScore: string;
  rpe: string;
  feel: string;
  supplements: string;
  food: string;
  notes: string;
};

type AdherenceFormState = {
  status: 'completed' | 'modified' | 'skipped';
  rpe: string;
  feel: string;
  notes: string;
  completedDurationMin: string;
  intensity: string;
  changeSummary: string;
};

function emptyManualForm(): ManualFormState {
  return {
    bpSystolic: '',
    bpDiastolic: '',
    subjectiveScore: '',
    rpe: '',
    feel: '',
    supplements: '',
    food: '',
    notes: '',
  };
}

function emptyAdherenceForm(): AdherenceFormState {
  return {
    status: 'completed',
    rpe: '',
    feel: '',
    notes: '',
    completedDurationMin: '',
    intensity: '',
    changeSummary: '',
  };
}

function textSummary(value: unknown): string {
  if (!value || typeof value !== 'object') {
    return '';
  }
  if (typeof (value as { summary?: unknown }).summary === 'string') {
    return (value as { summary: string }).summary;
  }
  if (Array.isArray((value as { items?: unknown }).items)) {
    return ((value as { items: unknown[] }).items.filter((item) => typeof item === 'string') as string[]).join('\n');
  }
  return '';
}

function objectSummary(text: string): Record<string, unknown> {
  const trimmed = text.trim();
  if (!trimmed) {
    return {};
  }
  return {
    summary: trimmed,
    items: trimmed
      .split('\n')
      .map((item) => item.trim())
      .filter(Boolean),
  };
}

function verdictVariant(verdict: string | null | undefined): 'success' | 'warning' | 'error' | 'muted' {
  if (verdict === 'green') return 'success';
  if (verdict === 'amber') return 'warning';
  if (verdict === 'red') return 'error';
  return 'muted';
}

function titleCase(value: string | null | undefined): string {
  if (!value) return 'Not ready yet';
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return 'Not synced';
  const d = new Date(value);
  // Hive occasionally returns a far-future timestamp — treat as sync error
  if (d.getTime() > Date.now() + 24 * 60 * 60 * 1000) return 'Sync error';
  return d.toLocaleString();
}

function formatMinutes(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return 'No sleep duration';
  return `${Math.round(seconds / 60)} min`;
}

async function fetchDailyLoop() {
  const response = await apiFetch<unknown>('/api/v1/daily-loop');
  return dailyLoopEnvelopeSchema.parse(response);
}

export function DashboardPage() {
  const { player } = useAuth();
  const queryClient = useQueryClient();
  const isOnline = useOnlineStatus();
  const [manualForm, setManualForm] = useState<ManualFormState>(emptyManualForm);
  const [adherenceForms, setAdherenceForms] = useState<Record<string, AdherenceFormState>>({});

  const query = useQuery({
    queryKey: ['daily-loop'],
    queryFn: fetchDailyLoop,
  });

  useEffect(() => {
    const data = query.data?.data;
    if (!data) return;

    const manualEntry = data.manualEntry;
    setManualForm({
      bpSystolic: manualEntry?.bpSystolic ? String(manualEntry.bpSystolic) : '',
      bpDiastolic: manualEntry?.bpDiastolic ? String(manualEntry.bpDiastolic) : '',
      subjectiveScore: manualEntry?.subjectiveScore ? String(manualEntry.subjectiveScore) : '',
      rpe: manualEntry?.rpe !== null && manualEntry?.rpe !== undefined ? String(manualEntry.rpe) : '',
      feel: manualEntry?.feel ?? '',
      supplements: textSummary(manualEntry?.supplementsJson),
      food: textSummary(manualEntry?.foodJson),
      notes: manualEntry?.notes ?? '',
    });

    const nextAdherenceForms: Record<string, AdherenceFormState> = {};
    for (const workout of data.plannedWorkouts) {
      nextAdherenceForms[workout.id] = {
        status: (workout.adherence?.adherenceStatus as AdherenceFormState['status'] | null) ?? 'completed',
        rpe:
          workout.adherence?.rpe !== null && workout.adherence?.rpe !== undefined
            ? String(workout.adherence.rpe)
            : '',
        feel: workout.adherence?.feel ?? '',
        notes: workout.adherence?.notes ?? '',
        completedDurationMin:
          typeof workout.adherence?.actualWorkoutJson?.completedDurationMin === 'number'
            ? String(workout.adherence.actualWorkoutJson.completedDurationMin)
            : '',
        intensity:
          typeof workout.adherence?.actualWorkoutJson?.intensity === 'string'
            ? workout.adherence.actualWorkoutJson.intensity
            : '',
        changeSummary:
          typeof workout.adherence?.actualWorkoutJson?.changeSummary === 'string'
            ? workout.adherence.actualWorkoutJson.changeSummary
            : '',
      };
    }
    setAdherenceForms(nextAdherenceForms);
  }, [query.data]);

  const manualMutation = useMutation({
    mutationFn: async (subjectDate: string) => {
      const payload = manualEntryInputSchema.parse({
        bpSystolic: manualForm.bpSystolic ? Number(manualForm.bpSystolic) : null,
        bpDiastolic: manualForm.bpDiastolic ? Number(manualForm.bpDiastolic) : null,
        subjectiveScore: manualForm.subjectiveScore ? Number(manualForm.subjectiveScore) : null,
        rpe: manualForm.rpe ? Number(manualForm.rpe) : null,
        feel: manualForm.feel || null,
        supplementsJson: objectSummary(manualForm.supplements),
        foodJson: objectSummary(manualForm.food),
        notes: manualForm.notes || null,
      });
      return apiFetch(`/api/v1/daily-loop/${subjectDate}/manual-entry`, {
        method: 'PUT',
        body: JSON.stringify(payload),
      });
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['daily-loop'] });
      toast.success('Manual check-in saved');
    },
    onError: (error) => {
      toast.error(error instanceof Error ? error.message : 'Failed to save manual check-in');
    },
  });

  const adherenceMutation = useMutation({
    mutationFn: async (workoutId: string) => {
      const data = query.data?.data;
      if (!data) throw new Error('Daily loop not loaded');
      const form = adherenceForms[workoutId];
      if (!form) throw new Error('Adherence form missing');
      const payload = plannedWorkoutAdherenceInputSchema.parse({
        status: form.status,
        rpe: form.rpe ? Number(form.rpe) : null,
        feel: form.feel || null,
        notes: form.notes || null,
        actualWorkoutJson: {
          completedDurationMin: form.completedDurationMin ? Number(form.completedDurationMin) : null,
          intensity: form.intensity || null,
          changeSummary: form.changeSummary || null,
        },
      });
      return apiFetch(`/api/v1/daily-loop/${data.subjectDate}/planned-workouts/${workoutId}/adherence`, {
        method: 'PUT',
        body: JSON.stringify(payload),
      });
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['daily-loop'] });
      toast.success('Adherence saved');
    },
    onError: (error) => {
      toast.error(error instanceof Error ? error.message : 'Failed to save adherence');
    },
  });

  if (query.isLoading) {
    return (
      <div className="space-y-6">
        <PageHeader title={`Good morning${player ? `, ${player.displayName}` : ''}`} eyebrow="Daily Loop" />
        <Card>
          <CardHeader>
            <CardTitle>Loading today&apos;s coaching brief…</CardTitle>
          </CardHeader>
        </Card>
      </div>
    );
  }

  if (query.isError || !query.data) {
    return (
      <div className="space-y-6">
        <PageHeader title={`Good morning${player ? `, ${player.displayName}` : ''}`} eyebrow="Daily Loop" />
        <Card>
          <CardHeader>
            <CardTitle>Daily loop unavailable</CardTitle>
            <CardDescription>
              {query.error instanceof Error ? query.error.message : 'The coaching brief could not be loaded.'}
            </CardDescription>
          </CardHeader>
        </Card>
      </div>
    );
  }

  const data: DailyLoopData = query.data.data;
  const analysis = data.morningAnalysis;
  const thermal = data.thermalState;
  const postWorkoutAnalyses = data.postWorkoutAnalyses ?? [];

  return (
    <div className="space-y-6">
      {!isOnline && (
        <div
          role="status"
          className="rounded-xl border border-amber-700/60 bg-amber-900/20 px-4 py-3 text-sm text-amber-200"
        >
          You&apos;re offline — showing cached data for {data.subjectDate}
        </div>
      )}
      <PageHeader
        title={`Good morning${player ? `, ${player.displayName}` : ''}`}
        eyebrow="Daily Loop"
        action={<Badge variant={verdictVariant(analysis?.verdict)}>{titleCase(analysis?.verdict)}</Badge>}
      />

      <div className="grid gap-4 lg:grid-cols-[1.1fr,0.9fr]">
        <Card className="bg-surface-elevated/60">
          <CardHeader>
            <CardTitle>Morning verdict</CardTitle>
            <CardDescription>
              {analysis ? `Generated ${formatDateTime(analysis.generatedAtUtc)}` : 'No morning analysis has been stored yet.'}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {analysis ? (
              <>
                <div className="flex flex-wrap gap-2">
                  {(analysis.reasons ?? []).map((reason) => (
                    <Badge key={reason} variant="muted" className="whitespace-normal py-1">
                      {reason}
                    </Badge>
                  ))}
                </div>
                {analysis.planAdjustments.length ? (
                  <div className="rounded-xl border border-border bg-bg px-4 py-3 text-sm text-text-primary">
                    <p className="mb-2 font-medium">Plan adjustments</p>
                    <ul className="space-y-1">
                      {analysis.planAdjustments.map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                <div className="rounded-xl border border-border bg-bg px-4 py-3 text-sm leading-6 text-text-primary whitespace-pre-wrap">
                  {analysis.outputMarkdown}
                </div>
              </>
            ) : (
              <p className="text-sm text-text-secondary">
                No verdict for this date yet — it&rsquo;s generated automatically each morning once your
                overnight Garmin metrics finish syncing after you wake.
              </p>
            )}
          </CardContent>
        </Card>

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-1">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Activity className="h-4 w-4 text-primary" aria-hidden />
                Key metrics
              </CardTitle>
            </CardHeader>
            <CardContent className="grid grid-cols-2 gap-3 text-sm">
              <div className="rounded-xl border border-border px-3 py-3">
                <p className="text-text-muted">Readiness</p>
                <p className="text-lg font-semibold text-text-primary">{data.dailyMetrics?.readinessScore ?? '—'}</p>
              </div>
              <div className="rounded-xl border border-border px-3 py-3">
                <p className="text-text-muted">Sleep</p>
                <p className="text-lg font-semibold text-text-primary">{data.sleep?.ageAdjustedScore ?? data.sleep?.score ?? '—'}</p>
              </div>
              <div className="rounded-xl border border-border px-3 py-3">
                <p className="text-text-muted">HRV</p>
                <p className="text-lg font-semibold text-text-primary">{data.dailyMetrics?.hrvLastNightAvgMs ?? '—'}</p>
              </div>
              <div className="rounded-xl border border-border px-3 py-3">
                <p className="text-text-muted">Body battery</p>
                <p className="text-lg font-semibold text-text-primary">{data.dailyMetrics?.bodyBatteryEnd ?? '—'}</p>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Thermometer className="h-4 w-4 text-primary" aria-hidden />
                Thermal state
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm text-text-primary">
              <div className="flex items-center justify-between rounded-xl border border-border px-3 py-3">
                <span>Indoor now</span>
                <span className="font-semibold">
                  {thermal.latestTemperatureC !== null && thermal.latestTemperatureC !== undefined
                    ? `${thermal.latestTemperatureC.toFixed(1)}°C`
                    : 'Not synced'}
                </span>
              </div>
              <div className="flex items-center justify-between rounded-xl border border-border px-3 py-3">
                <span>Thermostat set</span>
                <span className="font-semibold">
                  {thermal.targetTemperatureC !== null && thermal.targetTemperatureC !== undefined
                    ? `${thermal.targetTemperatureC.toFixed(1)}°C`
                    : '—'}
                </span>
              </div>
              <div className="flex items-center justify-between rounded-xl border border-border px-3 py-3">
                <span>Overnight low</span>
                <span className="font-semibold">
                  {thermal.overnightLowC !== null && thermal.overnightLowC !== undefined
                    ? `${thermal.overnightLowC.toFixed(1)}°C`
                    : '—'}
                </span>
              </div>
              <div className="flex items-center justify-between rounded-xl border border-border px-3 py-3">
                <span className="flex items-center gap-2">
                  <Wind className="h-4 w-4 text-text-secondary" aria-hidden />
                  Overnight wind
                </span>
                <span className="font-semibold">
                  {thermal.overnightWindMaxMph !== null && thermal.overnightWindMaxMph !== undefined
                    ? `${thermal.overnightWindMaxMph.toFixed(0)} mph`
                    : '—'}
                </span>
              </div>
              <p className="text-xs text-text-muted">Latest sync: {formatDateTime(thermal.capturedAtUtc)}</p>
            </CardContent>
          </Card>
        </div>
      </div>

      {postWorkoutAnalyses.length ? (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Bike className="h-4 w-4 text-primary" aria-hidden />
              Post-workout analysis
            </CardTitle>
            <CardDescription>
              {postWorkoutAnalyses.length === 1
                ? 'Latest ride analysis, recovery protocol, and tomorrow impact.'
                : `${postWorkoutAnalyses.length} ride analyses for ${data.subjectDate}.`}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {postWorkoutAnalyses.map((item) => (
              <div key={item.id} className="rounded-2xl border border-border bg-bg px-4 py-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="text-base font-semibold text-text-primary">
                      {item.activityName ?? 'Garmin ride'}
                    </p>
                    <p className="text-sm text-text-secondary">
                      Generated {formatDateTime(item.generatedAtUtc)}
                      {item.activityType ? ` · ${item.activityType}` : ''}
                    </p>
                  </div>
                  <Badge variant={item.recoveryDecision?.excluded ? 'warning' : 'accent'}>
                    {item.recoveryDecision?.excluded ? 'Recovery excluded' : 'Recovery ready'}
                  </Badge>
                </div>
                <div className="mt-4 rounded-xl border border-border bg-surface px-4 py-3 text-sm leading-6 text-text-primary whitespace-pre-wrap">
                  {item.outputMarkdown}
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      ) : null}

      <div className="grid gap-4 xl:grid-cols-[1fr,1fr]">
        <Card>
          <CardHeader>
            <CardTitle>Today&apos;s plan</CardTitle>
            <CardDescription>
              {data.plannedWorkouts.length
                ? `${data.plannedWorkouts.length} active workout${data.plannedWorkouts.length > 1 ? 's' : ''} for ${data.subjectDate}`
                : `No active workouts stored for ${data.subjectDate}.`}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {data.plannedWorkouts.map((workout) => {
              const adherence = adherenceForms[workout.id] ?? emptyAdherenceForm();
              return (
                <div key={workout.id} className="rounded-2xl border border-border bg-bg px-4 py-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <p className="text-base font-semibold text-text-primary">{workout.title}</p>
                      <p className="text-sm text-text-secondary">
                        {workout.workoutType} · {workout.plannedDurationMin ? `${workout.plannedDurationMin} min` : 'Duration TBD'}
                        {workout.intensityTarget ? ` · ${workout.intensityTarget}` : ''}
                      </p>
                    </div>
                    <Badge variant={workout.adherence ? 'accent' : 'muted'}>
                      {workout.adherence?.adherenceStatus ? titleCase(workout.adherence.adherenceStatus) : 'Awaiting adherence'}
                    </Badge>
                  </div>

                  <div className="mt-4 grid gap-3 md:grid-cols-2">
                    <div className="space-y-2">
                      <Label htmlFor={`status-${workout.id}`}>Outcome</Label>
                      <Select
                        value={adherence.status}
                        onValueChange={(value) =>
                          setAdherenceForms((current) => ({
                            ...current,
                            [workout.id]: {
                              ...(current[workout.id] ?? emptyAdherenceForm()),
                              status: value as AdherenceFormState['status'],
                            },
                          }))
                        }
                      >
                        <SelectTrigger id={`status-${workout.id}`}>
                          <SelectValue placeholder="Select outcome" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="completed">Completed</SelectItem>
                          <SelectItem value="modified">Modified</SelectItem>
                          <SelectItem value="skipped">Skipped</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor={`duration-${workout.id}`}>Actual duration (min)</Label>
                      <Input
                        id={`duration-${workout.id}`}
                        inputMode="numeric"
                        value={adherence.completedDurationMin}
                        onChange={(event) =>
                          setAdherenceForms((current) => ({
                            ...current,
                            [workout.id]: {
                              ...(current[workout.id] ?? emptyAdherenceForm()),
                              completedDurationMin: event.target.value,
                            },
                          }))
                        }
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor={`rpe-${workout.id}`}>Actual RPE</Label>
                      <Input
                        id={`rpe-${workout.id}`}
                        inputMode="decimal"
                        value={adherence.rpe}
                        onChange={(event) =>
                          setAdherenceForms((current) => ({
                            ...current,
                            [workout.id]: {
                              ...(current[workout.id] ?? emptyAdherenceForm()),
                              rpe: event.target.value,
                            },
                          }))
                        }
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor={`intensity-${workout.id}`}>Actual intensity</Label>
                      <Input
                        id={`intensity-${workout.id}`}
                        value={adherence.intensity}
                        onChange={(event) =>
                          setAdherenceForms((current) => ({
                            ...current,
                            [workout.id]: {
                              ...(current[workout.id] ?? emptyAdherenceForm()),
                              intensity: event.target.value,
                            },
                          }))
                        }
                      />
                    </div>
                  </div>

                  <div className="mt-3 grid gap-3">
                    <div className="space-y-2">
                      <Label htmlFor={`feel-${workout.id}`}>How it felt</Label>
                      <Input
                        id={`feel-${workout.id}`}
                        value={adherence.feel}
                        onChange={(event) =>
                          setAdherenceForms((current) => ({
                            ...current,
                            [workout.id]: {
                              ...(current[workout.id] ?? emptyAdherenceForm()),
                              feel: event.target.value,
                            },
                          }))
                        }
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor={`changes-${workout.id}`}>What changed?</Label>
                      <textarea
                        id={`changes-${workout.id}`}
                        className={textareaClassName}
                        value={adherence.changeSummary}
                        onChange={(event) =>
                          setAdherenceForms((current) => ({
                            ...current,
                            [workout.id]: {
                              ...(current[workout.id] ?? emptyAdherenceForm()),
                              changeSummary: event.target.value,
                            },
                          }))
                        }
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor={`notes-${workout.id}`}>Notes</Label>
                      <textarea
                        id={`notes-${workout.id}`}
                        className={textareaClassName}
                        value={adherence.notes}
                        onChange={(event) =>
                          setAdherenceForms((current) => ({
                            ...current,
                            [workout.id]: {
                              ...(current[workout.id] ?? emptyAdherenceForm()),
                              notes: event.target.value,
                            },
                          }))
                        }
                      />
                    </div>
                  </div>

                  <div className="mt-4 flex justify-end">
                    <Button
                      type="button"
                      onClick={() => adherenceMutation.mutate(workout.id)}
                      disabled={adherenceMutation.isPending}
                    >
                      <ClipboardCheck className="mr-2 h-4 w-4" aria-hidden />
                      Save adherence
                    </Button>
                  </div>
                </div>
              );
            })}
          </CardContent>
        </Card>

        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Manual check-in</CardTitle>
              <CardDescription>BP, subjective state, food, supplements, and notes feed later analyses.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="bp-systolic">BP systolic</Label>
                  <Input
                    id="bp-systolic"
                    inputMode="numeric"
                    value={manualForm.bpSystolic}
                    onChange={(event) => setManualForm((current) => ({ ...current, bpSystolic: event.target.value }))}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="bp-diastolic">BP diastolic</Label>
                  <Input
                    id="bp-diastolic"
                    inputMode="numeric"
                    value={manualForm.bpDiastolic}
                    onChange={(event) => setManualForm((current) => ({ ...current, bpDiastolic: event.target.value }))}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="subjective-score">Subjective score</Label>
                  <Input
                    id="subjective-score"
                    inputMode="numeric"
                    value={manualForm.subjectiveScore}
                    onChange={(event) =>
                      setManualForm((current) => ({ ...current, subjectiveScore: event.target.value }))
                    }
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="manual-rpe">RPE</Label>
                  <Input
                    id="manual-rpe"
                    inputMode="decimal"
                    value={manualForm.rpe}
                    onChange={(event) => setManualForm((current) => ({ ...current, rpe: event.target.value }))}
                  />
                </div>
              </div>
              <div className="space-y-2">
                <Label htmlFor="manual-feel">Feel</Label>
                <Input
                  id="manual-feel"
                  value={manualForm.feel}
                  onChange={(event) => setManualForm((current) => ({ ...current, feel: event.target.value }))}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="manual-supplements">Supplements</Label>
                <textarea
                  id="manual-supplements"
                  className={textareaClassName}
                  value={manualForm.supplements}
                  onChange={(event) =>
                    setManualForm((current) => ({ ...current, supplements: event.target.value }))
                  }
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="manual-food">Food</Label>
                <textarea
                  id="manual-food"
                  className={textareaClassName}
                  value={manualForm.food}
                  onChange={(event) => setManualForm((current) => ({ ...current, food: event.target.value }))}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="manual-notes">Notes</Label>
                <textarea
                  id="manual-notes"
                  className={textareaClassName}
                  value={manualForm.notes}
                  onChange={(event) => setManualForm((current) => ({ ...current, notes: event.target.value }))}
                />
              </div>
              <div className="flex justify-end">
                <Button type="button" onClick={() => manualMutation.mutate(data.subjectDate)} disabled={manualMutation.isPending}>
                  Save check-in
                </Button>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <ShieldAlert className="h-4 w-4 text-warning" aria-hidden />
                Data-quality guardrails
              </CardTitle>
              <CardDescription>The morning engine and daily loop both respect these rules.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {data.dataQualityWarnings.map((warning) => (
                <div key={warning.id} className="rounded-2xl border border-border bg-bg px-4 py-3">
                  <div className="flex items-center justify-between gap-3">
                    <p className="font-medium text-text-primary">{warning.summary}</p>
                    <Badge variant={warning.status === 'active' ? 'warning' : 'muted'}>
                      {warning.status === 'active' ? 'Active today' : 'Guardrail'}
                    </Badge>
                  </div>
                  <p className="mt-2 text-sm text-text-secondary">{warning.reason}</p>
                  {warning.detail ? <p className="mt-1 text-xs text-warning">{warning.detail}</p> : null}
                </div>
              ))}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Sleep snapshot</CardTitle>
            </CardHeader>
            <CardContent className="grid grid-cols-2 gap-3 text-sm">
              <div className="rounded-xl border border-border px-3 py-3">
                <p className="text-text-muted">Duration</p>
                <p className="text-base font-semibold text-text-primary">{formatMinutes(data.sleep?.durationSec)}</p>
              </div>
              <div className="rounded-xl border border-border px-3 py-3">
                <p className="text-text-muted">Qualifier</p>
                <p className="text-base font-semibold text-text-primary">{data.sleep?.qualifier ?? '—'}</p>
              </div>
              <div className="rounded-xl border border-border px-3 py-3">
                <p className="text-text-muted">SpO2</p>
                <p className="text-base font-semibold text-text-primary">
                  {data.sleep?.averageSpo2Pct !== null && data.sleep?.averageSpo2Pct !== undefined
                    ? `${data.sleep.averageSpo2Pct.toFixed(1)}%`
                    : '—'}
                </p>
              </div>
              <div className="rounded-xl border border-border px-3 py-3">
                <p className="text-text-muted">Respiration</p>
                <p className="text-base font-semibold text-text-primary">
                  {data.sleep?.averageRespiration !== null && data.sleep?.averageRespiration !== undefined
                    ? data.sleep.averageRespiration.toFixed(1)
                    : '—'}
                </p>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
