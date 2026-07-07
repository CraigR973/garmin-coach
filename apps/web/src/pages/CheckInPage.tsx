import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  dailyLoopEnvelopeSchema,
  manualEntryInputSchema,
  plannedWorkoutAdherenceInputSchema,
} from '@coach/shared';
import { toast } from 'sonner';
import { CollapsibleSection } from '@/components/CollapsibleSection';
import { PageHeader } from '@/components/PageHeader';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { ErrorState } from '@/components/EmptyState';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { Textarea } from '@/components/ui/textarea';
import { apiFetch } from '@/lib/api';

/** Batch 63: the tap button-group for "Overall" — five presets instead of a
 *  typed 0–10 number, so the fastest path to a saved check-in is one tap. */
const OVERALL_OPTIONS: Array<{ label: string; value: number }> = [
  { label: 'Rough', value: 2 },
  { label: 'Meh', value: 4 },
  { label: 'OK', value: 6 },
  { label: 'Good', value: 8 },
  { label: 'Great', value: 10 },
];

/** Batch 63: one-tap chips that fold into the existing `feel`/`notes` free-text
 *  columns as comma-separated tokens — no new `manual_entries` columns, no new
 *  endpoint. A chip toggles its token on/off in its target field. */
const QUICK_CHIPS: Array<{ key: string; label: string; field: 'feel' | 'notes'; token: string }> = [
  { key: 'slept-well', label: 'Slept well', field: 'feel', token: 'slept well' },
  { key: 'low-energy', label: 'Low energy', field: 'feel', token: 'low energy' },
  { key: 'niggle', label: 'Niggle', field: 'notes', token: 'niggle' },
];

function hasToken(text: string, token: string): boolean {
  return text
    .split(',')
    .map((part) => part.trim().toLowerCase())
    .includes(token.toLowerCase());
}

function toggleToken(text: string, token: string): string {
  const tokens = text
    .split(',')
    .map((part) => part.trim())
    .filter(Boolean);
  const existingIndex = tokens.findIndex((part) => part.toLowerCase() === token.toLowerCase());
  if (existingIndex >= 0) {
    tokens.splice(existingIndex, 1);
  } else {
    tokens.push(token);
  }
  return tokens.join(', ');
}

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

  // Batch 55: one unified save covers the whole check-in — the manual entry
  // (how you feel / BP / yesterday) plus every session's adherence in one pass
  // — instead of a separate save button per card/workout. Same PUT endpoints,
  // just orchestrated together so there is one clear "am I done" action.
  const saveMutation = useMutation({
    mutationFn: async () => {
      const data = query.data?.data;
      if (!data) throw new Error('Not loaded');

      const manualPayload = manualEntryInputSchema.parse({
        bpSystolic: manualForm.bpSystolic ? Number(manualForm.bpSystolic) : null,
        bpDiastolic: manualForm.bpDiastolic ? Number(manualForm.bpDiastolic) : null,
        subjectiveScore: manualForm.subjectiveScore ? Number(manualForm.subjectiveScore) : null,
        feel: manualForm.feel || null,
        supplementsJson: objectSummary(manualForm.supplements),
        foodJson: objectSummary(manualForm.food),
        notes: manualForm.notes || null,
      });
      await apiFetch(`/api/v1/daily-loop/${data.subjectDate}/manual-entry`, {
        method: 'PUT',
        body: JSON.stringify(manualPayload),
      });

      for (const workout of data.plannedWorkouts) {
        const form = adherenceForms[workout.id];
        if (!form) continue;
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
        await apiFetch(`/api/v1/daily-loop/${data.subjectDate}/planned-workouts/${workout.id}/adherence`, {
          method: 'PUT',
          body: JSON.stringify(payload),
        });
      }
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['daily-loop'] });
      toast.success('Check-in saved');
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : 'Could not save your check-in'),
  });

  const data = query.data?.data;

  function setManual<K extends keyof ManualFormState>(key: K, value: string) {
    setManualForm((current) => ({ ...current, [key]: value }));
  }

  function toggleChip(chip: (typeof QUICK_CHIPS)[number]) {
    setManualForm((current) => ({
      ...current,
      [chip.field]: toggleToken(current[chip.field], chip.token),
    }));
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

      {query.isError && (
        <ErrorState
          title="Couldn't load today's plan"
          description="You can still log how you're feeling below — your sessions will appear once this loads."
          onRetry={() => query.refetch()}
        />
      )}

      {query.isLoading && (
        <div className="space-y-5">
          <Skeleton className="h-56 w-full rounded-2xl" />
          <Skeleton className="h-40 w-full rounded-2xl" />
        </div>
      )}

      {/* Quick check-in (Batch 63): a tap for overall + a few one-tap chips is the
          whole default path — the fastest way to a saved, verdict-shaping read. */}
      <Card>
        <CardHeader>
          <CardTitle>How are you feeling?</CardTitle>
          <CardDescription>A few taps — your read feeds every analysis.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label>Overall</Label>
            <div className="flex flex-wrap gap-2">
              {OVERALL_OPTIONS.map((option) => {
                const selected = manualForm.subjectiveScore === String(option.value);
                return (
                  <Button
                    key={option.label}
                    type="button"
                    size="sm"
                    variant={selected ? 'default' : 'outline'}
                    aria-pressed={selected}
                    onClick={() => setManual('subjectiveScore', String(option.value))}
                  >
                    {option.label}
                  </Button>
                );
              })}
            </div>
          </div>
          <div className="space-y-2">
            <Label>Anything to flag?</Label>
            <div className="flex flex-wrap gap-2">
              {QUICK_CHIPS.map((chip) => {
                const active = hasToken(manualForm[chip.field], chip.token);
                return (
                  <Button
                    key={chip.key}
                    type="button"
                    size="sm"
                    variant={active ? 'default' : 'outline'}
                    aria-pressed={active}
                    onClick={() => toggleChip(chip)}
                  >
                    {chip.label}
                  </Button>
                );
              })}
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Batch 63: BP, supplements/food, and per-workout adherence move behind
          "More" — reachable, never required, so the default path stays a few
          taps. Collapsed by default; no sticky state (mirrors CollapsibleSection
          elsewhere). */}
      <CollapsibleSection
        title="More"
        summary="In your own words, blood pressure, supplements & food, and session logging"
      >
        <div className="space-y-6">
          <div className="space-y-4">
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
              <Textarea
                id="notes"
                className="min-h-[100px]"
                placeholder="Late night, stress, alcohol, illness…"
                value={manualForm.notes}
                onChange={(e) => setManual('notes', e.target.value)}
              />
            </div>
          </div>

          <div className="space-y-3 border-t border-border pt-4">
            <div>
              <p className="text-sm font-semibold text-text-primary">Blood pressure</p>
              <p className="text-xs text-text-secondary">Optional — if you took a reading this morning.</p>
            </div>
            <div className="grid grid-cols-2 gap-3">
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
            </div>
          </div>

          <div className="space-y-4 border-t border-border pt-4">
            <div>
              <p className="text-sm font-semibold text-text-primary">Yesterday</p>
              <p className="text-xs text-text-secondary">Supplements and food help spot patterns over time.</p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="supplements">Supplements</Label>
              <Textarea
                id="supplements"
                className="min-h-[100px]"
                value={manualForm.supplements}
                onChange={(e) => setManual('supplements', e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="food">Food &amp; evening snack</Label>
              <Textarea
                id="food"
                className="min-h-[100px]"
                value={manualForm.food}
                onChange={(e) => setManual('food', e.target.value)}
              />
            </div>
          </div>

          {data && data.plannedWorkouts.length > 0 && (
            <div className="space-y-4 border-t border-border pt-4">
              <div>
                <p className="text-sm font-semibold text-text-primary">How did your sessions go?</p>
                <p className="text-xs text-text-secondary">
                  Log what you actually did so tomorrow&apos;s plan stays honest.
                </p>
              </div>
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
                        <Textarea
                          id={`changes-${workout.id}`}
                          className="min-h-[100px]"
                          value={form.changeSummary}
                          onChange={(e) => setAdherence(workout.id, { changeSummary: e.target.value })}
                        />
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </CollapsibleSection>

      {/* Batch 55: one save covers the whole check-in — the per-card/per-workout
          save buttons above are gone in favour of this single clear action. */}
      <div className="flex justify-end">
        <Button type="button" onClick={() => saveMutation.mutate()} disabled={!data || saveMutation.isPending}>
          Save check-in
        </Button>
      </div>
    </div>
  );
}
