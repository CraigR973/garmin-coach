import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { dailyLoopEnvelopeSchema, manualEntryInputSchema } from '@coach/shared';
import { toast } from 'sonner';
import { CheckCircle2, Loader2 } from 'lucide-react';
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

const BRIEF_READY_POLL_MS = 3000;
const BRIEF_STAGE_WINDOWS_MS = [2000, 5500] as const;

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

function currentBriefStage(elapsedMs: number): number {
  if (elapsedMs < BRIEF_STAGE_WINDOWS_MS[0]) return 0;
  if (elapsedMs < BRIEF_STAGE_WINDOWS_MS[1]) return 1;
  return 2;
}

const BRIEF_STAGES = [
  {
    key: 'syncing',
    title: 'Syncing your overnight data',
    detail: "Making sure today's snapshot is fully up to date.",
  },
  {
    key: 'reading',
    title: 'Reading your morning',
    detail: 'Pulling your sleep, readiness, room, and notes into one read.',
  },
  {
    key: 'writing',
    title: 'Writing your brief',
    detail: 'Finishing the brief and sending a ready notification.',
  },
] as const;

export function CheckInPage() {
  const queryClient = useQueryClient();
  const [manualForm, setManualForm] = useState<ManualFormState>(emptyManualForm);
  const [brief, setBrief] = useState<CheckInBrief | null>(null);
  const [queuedAtMs, setQueuedAtMs] = useState<number | null>(null);
  const [stageNowMs, setStageNowMs] = useState<number>(() => Date.now());

  const query = useQuery({
    queryKey: ['daily-loop'],
    queryFn: fetchDailyLoop,
    refetchInterval: queuedAtMs != null ? BRIEF_READY_POLL_MS : false,
  });

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

  useEffect(() => {
    if (queuedAtMs == null) return;
    setStageNowMs(Date.now());
    const interval = window.setInterval(() => setStageNowMs(Date.now()), 500);
    return () => window.clearInterval(interval);
  }, [queuedAtMs]);

  useEffect(() => {
    if (queuedAtMs == null) return;
    const readyBrief = query.data?.data.morningAnalysis;
    if (!readyBrief) return;
    setBrief(readyBrief);
    setQueuedAtMs(null);
    toast.success('Your brief is ready');
  }, [queuedAtMs, query.data]);

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
      setQueuedAtMs(updated.morningAnalysis ? null : Date.now());
      await queryClient.invalidateQueries({ queryKey: ['daily-loop'] });
      toast.success(
        updated.morningAnalysis
          ? 'Your brief is ready'
          : "Check-in saved — I'll notify you when your brief is ready",
      );
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : 'Could not save your check-in'),
  });

  const data = query.data?.data;
  // Batch 96: a brief exists either freshly generated this session (`brief`,
  // set on save success) or already on the loaded snapshot (a same-day check-in
  // or the 09:30 backstop) — either way, re-submitting shouldn't regenerate it.
  const briefExists = brief != null || data?.morningAnalysis != null;
  const waitingForBrief = queuedAtMs != null && !briefExists;
  const waitingStage = waitingForBrief ? currentBriefStage(stageNowMs - queuedAtMs) : -1;

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
          submit still yields today's objective read.
          Batch 97: submitting returns immediately, then the page waits on the
          normal daily-loop snapshot while the server finishes the brief and
          sends a ready push. Batch 96 still prevents silent re-generation once
          a brief exists. */}
      <div className="flex justify-end">
        {briefExists ? (
          <Button asChild>
            <Link to="/brief">View brief</Link>
          </Button>
        ) : waitingForBrief ? (
          <Button type="button" disabled>
            Today&apos;s brief is on the way
          </Button>
        ) : (
          <Button type="button" onClick={() => saveMutation.mutate()} disabled={!data || saveMutation.isPending}>
            {saveMutation.isPending ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                Saving check-in…
              </>
            ) : (
              "Get today's brief"
            )}
          </Button>
        )}
      </div>

      {waitingForBrief ? (
        <Card>
          <CardHeader>
            <CardTitle>I&apos;ll notify you when it&apos;s ready</CardTitle>
            <CardDescription>
              You can leave this page now. If notifications are off, this screen will update when the brief lands.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-3" aria-label="Brief progress">
              {BRIEF_STAGES.map((stage, index) => {
                const complete = index < waitingStage;
                const current = index === waitingStage;
                return (
                  <div
                    key={stage.key}
                    className={`flex items-start gap-3 rounded-2xl border px-4 py-3 ${
                      complete
                        ? 'border-emerald-300 bg-emerald-50'
                        : current
                          ? 'border-primary/40 bg-primary/5'
                          : 'border-border bg-muted/30'
                    }`}
                  >
                    <div className="mt-0.5 flex h-5 w-5 items-center justify-center">
                      {complete ? (
                        <CheckCircle2 className="h-4 w-4 text-emerald-700" aria-hidden />
                      ) : current ? (
                        <Loader2 className="h-4 w-4 animate-spin text-primary" aria-hidden />
                      ) : (
                        <span className="text-xs font-semibold text-text-secondary">{index + 1}</span>
                      )}
                    </div>
                    <div className="space-y-1">
                      <p className="text-sm font-semibold text-text-primary">{stage.title}</p>
                      <p className="text-sm text-text-secondary">{stage.detail}</p>
                    </div>
                  </div>
                );
              })}
            </div>
            <div className="flex items-center justify-between gap-3">
              <p className="text-sm text-text-secondary">No push? You can stay here or check back in a moment.</p>
              <Button type="button" variant="outline" onClick={() => query.refetch()}>
                Refresh now
              </Button>
            </div>
          </CardContent>
        </Card>
      ) : null}

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
