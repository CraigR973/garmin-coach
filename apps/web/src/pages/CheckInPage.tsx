import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { dailyLoopEnvelopeSchema, manualEntryInputSchema } from '@coach/shared';
import { toast } from 'sonner';
import { Loader2 } from 'lucide-react';
import { CollapsibleSection } from '@/components/CollapsibleSection';
import { Markdown } from '@/components/Markdown';
import { PageHeader } from '@/components/PageHeader';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { ErrorState } from '@/components/EmptyState';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { Textarea } from '@/components/ui/textarea';
import { VerdictHero } from '@/components/VerdictHero';
import { apiFetch } from '@/lib/api';
import { SUBJECTIVE_FEEL_OPTIONS } from '@/lib/subjectiveFeel';

type CheckInBrief = NonNullable<
  ReturnType<typeof dailyLoopEnvelopeSchema.parse>['data']['morningAnalysis']
>;

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

function emptyManualForm(): ManualFormState {
  return { bpSystolic: '', bpDiastolic: '', subjectiveScore: '', feel: '', supplements: '', food: '', notes: '' };
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
  const [brief, setBrief] = useState<CheckInBrief | null>(null);

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
  }, [query.data]);

  // Batch 85: the check-in is the primary trigger for today's brief. Saving
  // force-regenerates the read server-side (folding in his notes/questions) and
  // returns the fresh snapshot, so the mutation surfaces the brief here and on Home.
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
      const response = await apiFetch<unknown>(`/api/v1/daily-loop/${data.subjectDate}/manual-entry`, {
        method: 'PUT',
        body: JSON.stringify(manualPayload),
      });
      return dailyLoopEnvelopeSchema.parse(response).data;
    },
    onSuccess: async (updated) => {
      setBrief(updated.morningAnalysis ?? null);
      await queryClient.invalidateQueries({ queryKey: ['daily-loop'] });
      toast.success(updated.morningAnalysis ? 'Your brief is ready' : 'Check-in saved');
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
            <Label>How you feel today</Label>
            <div className="flex flex-wrap gap-2">
              {SUBJECTIVE_FEEL_OPTIONS.map((option) => {
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
        summary="In your own words, blood pressure, and yesterday's supplements & food"
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
        </div>
      </CollapsibleSection>

      {/* Batch 85: one button generates today's brief from his check-in. An empty
          submit still yields today's objective read; a "reading your morning…"
          state covers the LLM call. The result surfaces below and on Home. */}
      <div className="flex justify-end">
        <Button type="button" onClick={() => saveMutation.mutate()} disabled={!data || saveMutation.isPending}>
          {saveMutation.isPending ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              Reading your morning…
            </>
          ) : (
            "Get today's brief"
          )}
        </Button>
      </div>

      {brief && (
        <div className="space-y-4">
          <VerdictHero verdict={brief.verdict} />
          <Card>
            <CardHeader>
              <CardTitle>Today&apos;s brief</CardTitle>
              <CardDescription>
                Generated from your check-in.{' '}
                <Link to="/" className="font-medium text-primary underline-offset-4 hover:underline">
                  See it on Home →
                </Link>
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Markdown>{brief.outputMarkdown}</Markdown>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
