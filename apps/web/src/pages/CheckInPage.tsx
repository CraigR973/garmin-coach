import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  dailyLoopEnvelopeSchema,
  manualEntryInputSchema,
  plannedWorkoutAdherenceInputSchema,
} from '@coach/shared';
import { toast } from 'sonner';
import { PageHeader } from '@/components/PageHeader';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { apiFetch } from '@/lib/api';

const textareaClassName =
  'min-h-[100px] w-full rounded-md border border-border bg-bg px-3 py-3 text-sm text-text-primary shadow-sm focus-visible:outline-none focus-visible:shadow-glow';

type ManualFormState = {
  bpSystolic: string;
  bpDiastolic: string;
  subjectiveScore: string;
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
  return { bpSystolic: '', bpDiastolic: '', subjectiveScore: '', feel: '', supplements: '', food: '', notes: '' };
}

function emptyAdherenceForm(): AdherenceFormState {
  return { status: 'completed', rpe: '', feel: '', notes: '', completedDurationMin: '', intensity: '', changeSummary: '' };
}

function textSummary(value: unknown): string {
  if (!value || typeof value !== 'object') return '';
  if (typeof (value as { summary?: unknown }).summary === 'string') {
    return (value as { summary: string }).summary;
  }
  if (Array.isArray((value as { items?: unknown }).items)) {
    return ((value as { items: unknown[] }).items.filter((i) => typeof i === 'string') as string[]).join('\n');
  }
  return '';
}

function objectSummary(text: string): Record<string, unknown> {
  const trimmed = text.trim();
  if (!trimmed) return {};
  return {
    summary: trimmed,
    items: trimmed.split('\n').map((i) => i.trim()).filter(Boolean),
  };
}

async function fetchDailyLoop() {
  const response = await apiFetch<unknown>('/api/v1/daily-loop');
  return dailyLoopEnvelopeSchema.parse(response);
}

export function CheckInPage() {
  const queryClient = useQueryClient();
  const [manualForm, setManualForm] = useState<ManualFormState>(emptyManualForm);
  const [adherenceForms, setAdherenceForms] = useState<Record<string, AdherenceFormState>>({});

  const query = useQuery({ queryKey: ['daily-loop'], queryFn: fetchDailyLoop });

  useEffect(() => {
    const data = query.data?.data;
    if (!data) return;

    const manualEntry = data.manualEntry;
    setManualForm({
      bpSystolic: manualEntry?.bpSystolic ? String(manualEntry.bpSystolic) : '',
      bpDiastolic: manualEntry?.bpDiastolic ? String(manualEntry.bpDiastolic) : '',
      subjectiveScore: manualEntry?.subjectiveScore ? String(manualEntry.subjectiveScore) : '',
      feel: manualEntry?.feel ?? '',
      supplements: textSummary(manualEntry?.supplementsJson),
      food: textSummary(manualEntry?.foodJson),
      notes: manualEntry?.notes ?? '',
    });

    const next: Record<string, AdherenceFormState> = {};
    for (const workout of data.plannedWorkouts) {
      next[workout.id] = {
        status: (workout.adherence?.adherenceStatus as AdherenceFormState['status'] | null) ?? 'completed',
        rpe: workout.adherence?.rpe != null ? String(workout.adherence.rpe) : '',
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
    setAdherenceForms(next);
  }, [query.data]);

  const manualMutation = useMutation({
    mutationFn: async (subjectDate: string) => {
      const payload = manualEntryInputSchema.parse({
        bpSystolic: manualForm.bpSystolic ? Number(manualForm.bpSystolic) : null,
        bpDiastolic: manualForm.bpDiastolic ? Number(manualForm.bpDiastolic) : null,
        subjectiveScore: manualForm.subjectiveScore ? Number(manualForm.subjectiveScore) : null,
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
      toast.success('Check-in saved');
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : 'Could not save your check-in'),
  });

  const adherenceMutation = useMutation({
    mutationFn: async (workoutId: string) => {
      const data = query.data?.data;
      if (!data) throw new Error('Not loaded');
      const form = adherenceForms[workoutId];
      if (!form) throw new Error('Missing form');
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
      toast.success('Saved');
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : 'Could not save'),
  });

  const data = query.data?.data;

  function setManual<K extends keyof ManualFormState>(key: K, value: string) {
    setManualForm((current) => ({ ...current, [key]: value }));
  }

  function setAdherence(workoutId: string, patch: Partial<AdherenceFormState>) {
    setAdherenceForms((current) => ({
      ...current,
      [workoutId]: { ...(current[workoutId] ?? emptyAdherenceForm()), ...patch },
    }));
  }

  return (
    <div className="space-y-5">
      <PageHeader title="Check in" back={{ to: '/', label: 'Home' }} />

      {/* How you feel */}
      <Card>
        <CardHeader>
          <CardTitle>How are you feeling?</CardTitle>
          <CardDescription>Your own read on this morning feeds every analysis.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="subjective-score">Overall (0–10)</Label>
            <Input
              id="subjective-score"
              inputMode="numeric"
              placeholder="1 awful · 5 OK · 10 fantastic"
              value={manualForm.subjectiveScore}
              onChange={(e) => setManual('subjectiveScore', e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="feel">In a few words</Label>
            <Input
              id="feel"
              placeholder="e.g. tired at first, better now"
              value={manualForm.feel}
              onChange={(e) => setManual('feel', e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="notes">Anything worth noting</Label>
            <textarea
              id="notes"
              className={textareaClassName}
              placeholder="Late night, stress, alcohol, illness…"
              value={manualForm.notes}
              onChange={(e) => setManual('notes', e.target.value)}
            />
          </div>
        </CardContent>
      </Card>

      {/* Body */}
      <Card>
        <CardHeader>
          <CardTitle>Blood pressure</CardTitle>
          <CardDescription>Optional — if you took a reading this morning.</CardDescription>
        </CardHeader>
        <CardContent className="grid grid-cols-2 gap-3">
          <div className="space-y-2">
            <Label htmlFor="bp-systolic">Systolic</Label>
            <Input
              id="bp-systolic"
              inputMode="numeric"
              value={manualForm.bpSystolic}
              onChange={(e) => setManual('bpSystolic', e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="bp-diastolic">Diastolic</Label>
            <Input
              id="bp-diastolic"
              inputMode="numeric"
              value={manualForm.bpDiastolic}
              onChange={(e) => setManual('bpDiastolic', e.target.value)}
            />
          </div>
        </CardContent>
      </Card>

      {/* Yesterday */}
      <Card>
        <CardHeader>
          <CardTitle>Yesterday</CardTitle>
          <CardDescription>Supplements and food help spot patterns over time.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="supplements">Supplements</Label>
            <textarea
              id="supplements"
              className={textareaClassName}
              value={manualForm.supplements}
              onChange={(e) => setManual('supplements', e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="food">Food &amp; evening snack</Label>
            <textarea
              id="food"
              className={textareaClassName}
              value={manualForm.food}
              onChange={(e) => setManual('food', e.target.value)}
            />
          </div>
          <div className="flex justify-end">
            <Button
              type="button"
              onClick={() => data && manualMutation.mutate(data.subjectDate)}
              disabled={!data || manualMutation.isPending}
            >
              Save check-in
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* How sessions went */}
      {data && data.plannedWorkouts.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>How did your sessions go?</CardTitle>
            <CardDescription>Log what you actually did so tomorrow&apos;s plan stays honest.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {data.plannedWorkouts.map((workout) => {
              const form = adherenceForms[workout.id] ?? emptyAdherenceForm();
              return (
                <div key={workout.id} className="rounded-2xl border border-border bg-bg px-4 py-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="font-semibold text-text-primary">{workout.title}</p>
                    {workout.adherence ? <Badge variant="muted">Logged</Badge> : null}
                  </div>

                  <div className="mt-3 grid gap-3 sm:grid-cols-2">
                    <div className="space-y-2">
                      <Label htmlFor={`status-${workout.id}`}>Outcome</Label>
                      <Select
                        value={form.status}
                        onValueChange={(value) =>
                          setAdherence(workout.id, { status: value as AdherenceFormState['status'] })
                        }
                      >
                        <SelectTrigger id={`status-${workout.id}`}>
                          <SelectValue placeholder="Select" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="completed">Did it as planned</SelectItem>
                          <SelectItem value="modified">Changed it</SelectItem>
                          <SelectItem value="skipped">Skipped it</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor={`duration-${workout.id}`}>Actual minutes</Label>
                      <Input
                        id={`duration-${workout.id}`}
                        inputMode="numeric"
                        value={form.completedDurationMin}
                        onChange={(e) => setAdherence(workout.id, { completedDurationMin: e.target.value })}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor={`rpe-${workout.id}`}>How hard (RPE)</Label>
                      <Input
                        id={`rpe-${workout.id}`}
                        inputMode="decimal"
                        value={form.rpe}
                        onChange={(e) => setAdherence(workout.id, { rpe: e.target.value })}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor={`feel-${workout.id}`}>How it felt</Label>
                      <Input
                        id={`feel-${workout.id}`}
                        value={form.feel}
                        onChange={(e) => setAdherence(workout.id, { feel: e.target.value })}
                      />
                    </div>
                  </div>

                  {form.status === 'modified' && (
                    <div className="mt-3 space-y-2">
                      <Label htmlFor={`changes-${workout.id}`}>What changed?</Label>
                      <textarea
                        id={`changes-${workout.id}`}
                        className={textareaClassName}
                        value={form.changeSummary}
                        onChange={(e) => setAdherence(workout.id, { changeSummary: e.target.value })}
                      />
                    </div>
                  )}

                  <div className="mt-3 flex justify-end">
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => adherenceMutation.mutate(workout.id)}
                      disabled={adherenceMutation.isPending}
                    >
                      Save session
                    </Button>
                  </div>
                </div>
              );
            })}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
