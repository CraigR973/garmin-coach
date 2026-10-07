import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  blockChangeInputSchema,
  blockGeneratorEnvelopeSchema,
  blockLockEnvelopeSchema,
  type BlockProgressionProposal,
  type GeneratedBlockDraft,
  type PlanChange,
  type SessionEdits,
} from '@coach/shared';
import { Check, Hammer, Lock, MessageCircle, Sparkles, Trash2, TrendingUp } from 'lucide-react';
import { toast } from 'sonner';
import { PageHeader } from '@/components/PageHeader';
import { PlanChangesCard } from '@/components/plan-builder/PlanChangesCard';
import { PlanDaysCard } from '@/components/plan-builder/PlanDaysCard';
import { PlanStartCard } from '@/components/plan-builder/PlanStartCard';
import {
  PlanWeekCard,
  type OpenPanel,
  type PlanWeekDates,
} from '@/components/plan-builder/PlanWeekCard';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { apiFetch } from '@/lib/api';
import { useZwiftRail } from '@/hooks/useZwiftRail';
import { openCoach } from '@/lib/coachOrigin';
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
} from '@/lib/nextPlan';
import {
  TALK_TO_COACH,
  WHY_AS_PROPOSED,
  isRide,
  overLongest,
  weekDates,
} from '@/lib/planChanges';
import { acceptedRidesDestination } from '@/lib/zwiftRail';

const BASE = '/api/v1/block-generator';

async function fetchDraft() {
  const response = await apiFetch<unknown>(BASE);
  return blockGeneratorEnvelopeSchema.parse(response);
}

/** A draft made before Batch 323 has no plan name. */
function planNameOf(draft: GeneratedBlockDraft): string {
  return draft.planName ?? 'Your plan';
}

export function BlockGeneratorPage() {
  const queryClient = useQueryClient();
  const zwiftRail = useZwiftRail();
  const [openPanel, setOpenPanel] = useState<OpenPanel>(null);

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

  // Batch 324: one change from the closed list, against the revision on screen; the server
  // checks it, versions the draft and says what it did.
  const changeMutation = useMutation({
    mutationFn: async ({
      change,
      expectedRevision,
    }: {
      change: PlanChange;
      expectedRevision: number | null;
    }) => {
      const body = blockChangeInputSchema.parse({ change, expectedRevision });
      const response = await apiFetch<unknown>(`${BASE}/changes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      return blockGeneratorEnvelopeSchema.parse(response);
    },
  });

  // A save can carry more than one change (a new name and new minutes); each goes in turn,
  // against the revision the one before it made.
  const applyChanges = async (changes: PlanChange[]) => {
    let revision = query.data?.data.draft?.revision ?? null;
    try {
      for (const change of changes) {
        const envelope = await changeMutation.mutateAsync({ change, expectedRevision: revision });
        queryClient.setQueryData(['block-generator'], envelope);
        const log = envelope.data.draft?.changes ?? [];
        const last = log[log.length - 1];
        if (last) toast.success(last.summary);
        revision = envelope.data.draft?.revision ?? null;
      }
      setOpenPanel(null);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not change the plan');
      await queryClient.invalidateQueries({ queryKey: ['block-generator'] });
    } finally {
      void queryClient.invalidateQueries({ queryKey: ['daily-loop'] });
    }
  };

  const lockMutation = useMutation({
    mutationFn: async () => {
      const response = await apiFetch<unknown>(`${BASE}/lock`, { method: 'POST' });
      return blockLockEnvelopeSchema.parse(response);
    },
    onSuccess: async () => {
      const name = query.data?.data.draft ? planNameOf(query.data.data.draft) : 'Your plan';
      await invalidate();
      toast.success(acceptedLine(name, acceptedRidesDestination(zwiftRail)));
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
      setOpenPanel(null);
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

  const { draft, canGenerate, sessionEdits, startOptions, sessionChangesSinceRebuild } =
    query.data.data;
  const { weeksOverLongest } = query.data.data;
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
          sessionEdits={sessionEdits}
          startOptions={startOptions}
          sessionChangesSinceRebuild={sessionChangesSinceRebuild}
          weeksOverLongest={weeksOverLongest}
          openPanel={openPanel}
          onOpenPanel={setOpenPanel}
          changing={changeMutation.isPending}
          onChanges={applyChanges}
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
  sessionEdits: Record<string, SessionEdits>;
  startOptions: string[];
  sessionChangesSinceRebuild: number;
  weeksOverLongest: number[];
  openPanel: OpenPanel;
  onOpenPanel: (panel: OpenPanel) => void;
  changing: boolean;
  onChanges: (changes: PlanChange[]) => Promise<void>;
  onLock: () => void;
  locking: boolean;
  onDiscard: () => void;
  discarding: boolean;
}

function DraftView({
  draft,
  sessionEdits,
  startOptions,
  sessionChangesSinceRebuild,
  weeksOverLongest,
  openPanel,
  onOpenPanel,
  changing,
  onChanges,
  onLock,
  locking,
  onDiscard,
  discarding,
}: DraftViewProps) {
  const changes = draft.changes ?? [];
  const planDates: PlanWeekDates[] = draft.weeks.map((week) => ({
    weekNumber: week.weekNumber,
    label: week.label,
    dates: weekDates(week.startDate),
  }));
  const rideDates = new Set(
    draft.weeks.flatMap((week) =>
      week.workouts.filter((workout) => isRide(workout)).map((workout) => workout.workoutDate),
    ),
  );
  const longest = draft.basis?.longestWeekMin ?? null;
  const previousPlan = draft.basis?.previousPlan ?? 'your last plan';
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
              <p className="text-sm font-medium text-text-primary">
                {changes.length > 0 ? WHY_AS_PROPOSED : WHY_THIS_PLAN}
              </p>
              <ul className="list-disc space-y-1 pl-5 text-sm leading-6 text-text-secondary">
                {draft.whyThisPlan.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </div>
          ) : null}
          <div className="flex flex-wrap gap-2">
            <Button type="button" onClick={onLock} disabled={locking || changing}>
              <Check className="mr-2 h-4 w-4" aria-hidden />
              {ACCEPT_PLAN}
            </Button>
            <Button type="button" variant="outline" onClick={onDiscard} disabled={discarding}>
              <Trash2 className="mr-2 h-4 w-4" aria-hidden />
              {DECLINE_PLAN}
            </Button>
            <Button type="button" variant="ghost" onClick={() => openCoach()}>
              <MessageCircle className="mr-2 h-4 w-4" aria-hidden />
              {TALK_TO_COACH}
            </Button>
          </div>
        </CardContent>
      </Card>

      {draft.progressionProposal && (
        <ProgressionProposalPanel proposal={draft.progressionProposal} />
      )}

      {draft.days ? (
        <PlanDaysCard
          days={draft.days}
          sessionChangesSinceRebuild={sessionChangesSinceRebuild}
          pending={changing}
          onSave={(days) => void onChanges([{ kind: 'days', days }])}
        />
      ) : null}

      {startOptions.length > 0 ? (
        <PlanStartCard
          startDate={draft.startDate}
          options={startOptions}
          pending={changing}
          onSave={(startDate) => void onChanges([{ kind: 'start', startDate }])}
        />
      ) : null}

      {changes.length > 0 ? (
        <PlanChangesCard
          changes={changes}
          pending={changing}
          onReset={() => void onChanges([{ kind: 'reset' }])}
        />
      ) : null}

      {draft.weeks.map((week) => (
        <PlanWeekCard
          key={week.weekNumber}
          week={week}
          sessionEdits={sessionEdits}
          planDates={planDates}
          rideDates={rideDates}
          overLongestLine={
            longest !== null && weeksOverLongest.includes(week.weekNumber)
              ? overLongest(previousPlan, longest)
              : null
          }
          openPanel={openPanel}
          onOpenPanel={onOpenPanel}
          pending={changing}
          onChanges={onChanges}
        />
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
