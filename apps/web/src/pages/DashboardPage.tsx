import { useState, type ReactNode } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import {
  Activity,
  ArrowLeftRight,
  BedDouble,
  Bike,
  CalendarDays,
  Check,
  ChevronRight,
  ClipboardCheck,
  Dumbbell,
  Fan,
  LineChart,
  MoonStar,
  Pencil,
  Plus,
  Thermometer,
  Trash2,
  Wind,
  X,
  type LucideIcon,
} from 'lucide-react';
import { postRideCheckInInputSchema } from '@coach/shared';
import { toast } from 'sonner';
import { MetricComparisonTable, type AgeComparison } from '@/components/MetricComparisonTable';
import { type MetricBaselineRow } from '@/components/MetricsBaselineTable';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Markdown } from '@/components/Markdown';
import { PageHeader } from '@/components/PageHeader';
import { Skeleton } from '@/components/ui/skeleton';
import { VerdictHero } from '@/components/VerdictHero';
import { useAuth } from '@/contexts/AuthContext';
import { isBikeWorkout, useDailyPhase } from '@/hooks/useDailyPhase';
import { useDailyLoop, type DailyLoopData } from '@/hooks/useDailyLoop';
import { useOnlineStatus } from '@/hooks/useOnlineStatus';
import { useBedroomOvernight } from '@/hooks/useBedroomOvernight';
import { apiFetch } from '@/lib/api';
import {
  fanStatusText,
  formatDateTime,
  friendlyDate,
  hm,
  nextDays,
  overnightGlanceText,
  remContext,
  type FanState,
} from '@/lib/dailyFlow';
import { greetingForNow, verdictBadgeVariant, verdictLabel, verdictToneLabel } from '@/lib/copy';
import { dayStateForWorkouts, type DayCategory } from '@/lib/workoutCategories';

const textareaClassName =
  'min-h-[88px] w-full rounded-md border border-border bg-bg px-3 py-3 text-sm text-text-primary shadow-sm focus-visible:outline-none focus-visible:shadow-glow';

function workoutIcon(type: string): LucideIcon {
  const t = type.toLowerCase();
  if (/dumbbell|bodyweight|strength|resist/.test(t)) return Dumbbell;
  if (/bike|cycl|ride|vo2|z2|sweet|endurance|tempo|threshold/.test(t)) return Bike;
  return Activity;
}

function prettyType(type: string): string {
  const cleaned = type.replace(/[_-]+/g, ' ').trim();
  return cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
}

export function DashboardPage() {
  const { player } = useAuth();
  const queryClient = useQueryClient();
  const isOnline = useOnlineStatus();
  const query = useDailyLoop();
  const greeting = `${greetingForNow()}${player ? `, ${player.displayName}` : ''}`;
  const data = query.data?.data;
  const phase = useDailyPhase(data);
  const invalidateLoop = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['daily-loop'] }),
      queryClient.invalidateQueries({ queryKey: ['week-ahead'] }),
    ]);
  };
  const editMutation = useMutation({
    mutationFn: ({
      workoutId,
      durationScalePct,
      intensityScalePct,
    }: {
      workoutId: string;
      durationScalePct?: number;
      intensityScalePct?: number;
    }) =>
      apiFetch(`/api/v1/workout-delivery/planned-workouts/${workoutId}/edit`, {
        method: 'POST',
        body: JSON.stringify({ durationScalePct, intensityScalePct }),
      }),
    onSuccess: async () => {
      await invalidateLoop();
      toast.success('Updated and synced to Zwift');
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : 'Could not update the session'),
  });
  const approveMutation = useMutation({
    mutationFn: ({ workoutId }: { workoutId: string }) =>
      apiFetch(`/api/v1/workout-delivery/planned-workouts/${workoutId}/approve-adjustment`, {
        method: 'POST',
      }),
    onSuccess: async () => {
      await invalidateLoop();
      toast.success("Coach's adjustment uploaded to Zwift");
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : 'Could not approve the adjustment'),
  });
  const skipMutation = useMutation({
    mutationFn: ({ workoutId }: { workoutId: string }) =>
      apiFetch(`/api/v1/workout-delivery/planned-workouts/${workoutId}/skip`, { method: 'POST' }),
    onSuccess: async () => {
      await invalidateLoop();
      toast.success('Session skipped');
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : 'Could not skip the session'),
  });
  const swapMutation = useMutation({
    mutationFn: ({ workoutId, targetDate }: { workoutId: string; targetDate: string }) =>
      apiFetch(`/api/v1/workout-delivery/planned-workouts/${workoutId}/swap`, {
        method: 'POST',
        body: JSON.stringify({ targetDate }),
      }),
    onSuccess: async () => {
      await invalidateLoop();
      toast.success('Day swapped');
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : 'Could not swap the day'),
  });
  const addWorkoutMutation = useMutation({
    mutationFn: ({ date, category }: { date: string; category: Exclude<DayCategory, 'rest'> }) =>
      apiFetch(`/api/v1/plan-actions/days/${date}/workouts`, {
        method: 'POST',
        body: JSON.stringify({ category }),
      }),
    onSuccess: async () => {
      await invalidateLoop();
      toast.success('Workout added');
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : 'Could not add the workout'),
  });
  const skipDayMutation = useMutation({
    mutationFn: ({ date }: { date: string }) =>
      apiFetch(`/api/v1/plan-actions/days/${date}/skip`, { method: 'POST' }),
    onSuccess: async () => {
      await invalidateLoop();
      toast.success('Day skipped');
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : 'Could not skip the day'),
  });
  const actualMutation = useMutation({
    mutationFn: ({ date, label, notes }: { date: string; label: string; notes: string | null }) =>
      apiFetch(`/api/v1/plan-actions/days/${date}/actual`, {
        method: 'POST',
        body: JSON.stringify({ label, notes }),
      }),
    onSuccess: async () => {
      await invalidateLoop();
      toast.success('Logged what happened');
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : 'Could not save that note'),
  });
  const postRideCheckInMutation = useMutation({
    mutationFn: ({
      activityId,
      subjectiveScore,
      rpe,
      feel,
      notes,
    }: {
      activityId: string;
      subjectiveScore: number | null;
      rpe: number | null;
      feel: string | null;
      notes: string | null;
    }) => {
      if (!data) throw new Error('Daily loop not loaded');
      const payload = postRideCheckInInputSchema.parse({
        subjectiveScore,
        rpe,
        feel,
        notes,
      });
      return apiFetch(`/api/v1/daily-loop/${data.subjectDate}/activities/${activityId}/post-ride-check-in`, {
        method: 'PUT',
        body: JSON.stringify(payload),
      });
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['daily-loop'] });
      toast.success('Ride check-in saved');
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : 'Could not save ride check-in'),
  });

  if (query.isLoading) {
    return (
      <div className="space-y-5">
        <PageHeader title={greeting} />
        <Skeleton className="h-24 w-full rounded-2xl" />
        <Skeleton className="h-40 w-full rounded-2xl" />
      </div>
    );
  }

  if (query.isError || !query.data) {
    return (
      <div className="space-y-5">
        <PageHeader title={greeting} />
        <Card>
          <CardHeader>
            <CardTitle>Today&apos;s brief couldn&apos;t load</CardTitle>
            <CardDescription>
              {query.error instanceof Error ? query.error.message : 'Please try again in a moment.'}
            </CardDescription>
          </CardHeader>
        </Card>
      </div>
    );
  }

  const daily = data!;
  const analysis = daily.morningAnalysis;
  const ageComparison = (analysis?.ageComparison ?? null) as AgeComparison | null;
  const metricsVsBaselines = (analysis?.metricsVsBaselines ?? []) as MetricBaselineRow[];
  const sleep = daily.sleep;
  const thermal = daily.thermalState;
  const postWorkouts = daily.postWorkoutAnalyses ?? [];
  const todaysWorkouts = daily.plannedWorkouts;
  const dayState = dayStateForWorkouts(todaysWorkouts);
  const actionsBusy =
    editMutation.isPending ||
    approveMutation.isPending ||
    skipMutation.isPending ||
    swapMutation.isPending ||
    addWorkoutMutation.isPending ||
    skipDayMutation.isPending ||
    actualMutation.isPending;
  const todayActions = {
    busy: actionsBusy,
    onEdit: (payload: { workoutId: string; durationScalePct?: number; intensityScalePct?: number }) =>
      editMutation.mutate(payload),
    onApprove: (payload: { workoutId: string }) => approveMutation.mutate(payload),
    onSkip: (payload: { workoutId: string }) => skipMutation.mutate(payload),
    onSwap: (payload: { workoutId: string; targetDate: string }) => swapMutation.mutate(payload),
  };
  const dayActions = {
    busy: actionsBusy,
    onAddWorkout: (category: Exclude<DayCategory, 'rest'>) =>
      addWorkoutMutation.mutate({ date: daily.subjectDate, category }),
    onSkipDay: () => skipDayMutation.mutate({ date: daily.subjectDate }),
    onRecordActual: (payload: { label: string; notes: string | null }) =>
      actualMutation.mutate({ date: daily.subjectDate, ...payload }),
  };

  return (
    <div className="space-y-5">
      {!isOnline && (
        <div
          role="status"
          className="rounded-xl border border-warning/40 bg-warning/10 px-4 py-3 text-sm text-warning"
        >
          You&apos;re offline — showing your last saved brief for {friendlyDate(daily.subjectDate)}.
        </div>
      )}

      <PageHeader title={greeting} />

      <VerdictHero verdict={analysis?.verdict} dateLabel={friendlyDate(daily.subjectDate)} />

      {phase === 'pre_ride' && (
        <>
          <div className="flex flex-wrap gap-2">
            <Button asChild>
              <Link to="/check-in">
                <ClipboardCheck className="mr-2 h-4 w-4" aria-hidden />
                {daily.manualEntry ? 'Update check-in' : 'Check in'}
              </Link>
            </Button>
          </div>

          <SleepSnapshotCard
            sleep={sleep}
            metricsVsBaselines={metricsVsBaselines}
            ageComparison={ageComparison}
            morningBriefLink="/brief"
            baselinesLink="/baselines"
          />

          <OvernightGlance />

          <DayPlanCard
            dayState={dayState}
            workouts={todaysWorkouts}
            verdict={analysis?.verdict}
            planAdjustments={analysis?.planAdjustments ?? []}
            subjectDate={daily.subjectDate}
            workoutActions={todayActions}
            dayActions={dayActions}
          />
        </>
      )}

      {phase === 'post_ride' && (
        <>
          <PostRideCard
            items={postWorkouts}
            onSaveCheckIn={(payload) => postRideCheckInMutation.mutate(payload)}
            savingActivityId={postRideCheckInMutation.variables?.activityId ?? null}
            isSaving={postRideCheckInMutation.isPending}
          />

          <TomorrowCard
            tomorrowImpact={postWorkouts[0]?.tomorrowImpact}
            fallback={
              analysis?.verdict
                ? `${verdictLabel(analysis.verdict)} tomorrow starts from today&apos;s recovery picture.`
                : 'Tomorrow&apos;s cue will show up here after the coach read.'
            }
          />

          <SleepPrepCard />

          <BedroomSummaryCard thermal={thermal} />
        </>
      )}

      {phase === 'rest_day' && (
        <>
          <SleepSnapshotCard
            sleep={sleep}
            metricsVsBaselines={metricsVsBaselines}
            ageComparison={ageComparison}
            morningBriefLink="/brief"
            baselinesLink="/baselines"
          />

          <OvernightGlance />

          <DayPlanCard
            dayState={dayState}
            workouts={todaysWorkouts}
            verdict={analysis?.verdict}
            planAdjustments={analysis?.planAdjustments ?? []}
            subjectDate={daily.subjectDate}
            workoutActions={todayActions}
            dayActions={dayActions}
          />

          <BedroomSummaryCard thermal={thermal} />
        </>
      )}
    </div>
  );
}

function SleepSnapshotCard({
  sleep,
  metricsVsBaselines,
  ageComparison,
  morningBriefLink,
  baselinesLink,
}: {
  sleep: {
    qualifier?: string | null;
    durationSec?: number | null;
    remSleepSec?: number | null;
  } | null;
  metricsVsBaselines: MetricBaselineRow[];
  ageComparison: AgeComparison | null;
  morningBriefLink: string;
  baselinesLink: string;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <BedDouble className="h-4 w-4 text-primary" aria-hidden />
          Last night&apos;s sleep
        </CardTitle>
        {sleep ? (
          <CardDescription>
            {hm(sleep.durationSec)} asleep
            {sleep.qualifier ? ` · ${sleep.qualifier}` : ''}
            {remContext(sleep.remSleepSec) ? ` · REM ${remContext(sleep.remSleepSec)}` : ''}
          </CardDescription>
        ) : (
          <CardDescription>No sleep data has synced for last night yet.</CardDescription>
        )}
      </CardHeader>
      <CardContent className="space-y-4">
        <MetricComparisonTable rows={metricsVsBaselines} ageComparison={ageComparison} />
        <div className="grid gap-3 sm:grid-cols-2">
          <DetailLinkCard
            to={morningBriefLink}
            title="Full morning brief"
            description="Open the complete coach read and verdict notes."
          />
          <DetailLinkCard
            to={baselinesLink}
            title="Baselines"
            description="See the full metrics-vs-baselines table."
          />
        </div>
      </CardContent>
    </Card>
  );
}

type TodayWorkout = DailyLoopData['plannedWorkouts'][number];

type TodayWorkoutActions = {
  busy: boolean;
  onEdit: (payload: {
    workoutId: string;
    durationScalePct?: number;
    intensityScalePct?: number;
  }) => void;
  onApprove: (payload: { workoutId: string }) => void;
  onSkip: (payload: { workoutId: string }) => void;
  onSwap: (payload: { workoutId: string; targetDate: string }) => void;
};

function DayPlanCard({
  dayState,
  workouts,
  verdict,
  planAdjustments,
  subjectDate,
  workoutActions,
  dayActions,
}: {
  dayState: { label: string; isRest: boolean };
  workouts: TodayWorkout[];
  verdict?: string | null;
  planAdjustments: string[];
  subjectDate: string;
  workoutActions: TodayWorkoutActions;
  dayActions: {
    busy: boolean;
    onAddWorkout: (category: Exclude<DayCategory, 'rest'>) => void;
    onSkipDay: () => void;
    onRecordActual: (payload: { label: string; notes: string | null }) => void;
  };
}) {
  const hasWorkouts = workouts.length > 0;
  return (
    <div className="space-y-3">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between gap-2">
            <span>{dayState.label} day</span>
            <Badge variant={verdictBadgeVariant(verdict)}>{verdictLabel(verdict)}</Badge>
          </CardTitle>
          <CardDescription>
            {hasWorkouts ? 'Each session can be changed on its own.' : 'No session is scheduled.'}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <AddWorkoutButtons busy={dayActions.busy} onAddWorkout={dayActions.onAddWorkout} />
          <div className="flex flex-wrap gap-2">
            <Button asChild type="button" size="sm" variant="outline">
              <Link to="/delivery">
                <CalendarDays className="h-4 w-4" aria-hidden />
                View week
              </Link>
            </Button>
            {hasWorkouts && (
              <Button type="button" size="sm" variant="outline" onClick={dayActions.onSkipDay} disabled={dayActions.busy}>
                <Trash2 className="h-4 w-4" aria-hidden />
                Skip whole day
              </Button>
            )}
          </div>
          {!hasWorkouts && (
            <p className="rounded-xl border border-dashed border-border px-4 py-4 text-sm text-text-secondary">
              Rest is the plan today. Add something light, swap a workout in from the week, or just record what happened.
            </p>
          )}
          <ActualWorkoutForm busy={dayActions.busy} onSubmit={dayActions.onRecordActual} />
        </CardContent>
      </Card>

      {workouts.map((workout) => (
        <TodayCard
          key={workout.id}
          workout={workout}
          verdict={verdict}
          planAdjustments={planAdjustments}
          subjectDate={subjectDate}
          {...workoutActions}
        />
      ))}
    </div>
  );
}

function AddWorkoutButtons({
  busy,
  onAddWorkout,
}: {
  busy: boolean;
  onAddWorkout: (category: Exclude<DayCategory, 'rest'>) => void;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => onAddWorkout('cycle')}>
        <Plus className="h-4 w-4" aria-hidden />
        Cycle
      </Button>
      <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => onAddWorkout('weights')}>
        <Plus className="h-4 w-4" aria-hidden />
        Weights
      </Button>
      <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => onAddWorkout('flexibility')}>
        <Plus className="h-4 w-4" aria-hidden />
        Flexibility
      </Button>
    </div>
  );
}

function ActualWorkoutForm({
  busy,
  onSubmit,
}: {
  busy: boolean;
  onSubmit: (payload: { label: string; notes: string | null }) => void;
}) {
  const [open, setOpen] = useState(false);
  const [label, setLabel] = useState('');
  const [notes, setNotes] = useState('');
  if (!open) {
    return (
      <Button type="button" size="sm" variant="ghost" onClick={() => setOpen(true)}>
        I did something else
      </Button>
    );
  }
  return (
    <div className="space-y-3 rounded-lg border border-border bg-surface-elevated/60 px-3 py-3">
      <div className="space-y-1.5">
        <Label htmlFor="actual-label">What happened?</Label>
        <Input
          id="actual-label"
          value={label}
          onChange={(event) => setLabel(event.target.value)}
          placeholder="Walked instead"
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="actual-notes">Notes</Label>
        <textarea
          id="actual-notes"
          className={textareaClassName}
          value={notes}
          onChange={(event) => setNotes(event.target.value)}
        />
      </div>
      <div className="flex gap-2">
        <Button
          type="button"
          size="sm"
          disabled={busy || !label.trim()}
          onClick={() => onSubmit({ label: label.trim(), notes: notes.trim() || null })}
        >
          Save
        </Button>
        <Button type="button" size="sm" variant="outline" onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

function TodayCard({
  workout,
  verdict,
  planAdjustments = [],
  subjectDate,
  busy,
  onEdit,
  onApprove,
  onSkip,
  onSwap,
}: {
  workout: TodayWorkout | null;
  verdict?: string | null;
  planAdjustments?: string[];
  subjectDate: string;
} & TodayWorkoutActions) {
  const [panel, setPanel] = useState<'none' | 'edit' | 'swap' | 'skip'>('none');
  const [ignored, setIgnored] = useState(false);
  const [durationScalePct, setDurationScalePct] = useState('100');
  const [intensityScalePct, setIntensityScalePct] = useState('100');

  if (!workout) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Today</CardTitle>
          <CardDescription>A calm read of the day ahead.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="rounded-xl border border-dashed border-border px-4 py-4">
            <p className="font-medium text-text-primary">Nothing planned today</p>
            <p className="mt-1 text-sm text-text-secondary">
              No session is scheduled — enjoy the rest day.
            </p>
          </div>
        </CardContent>
      </Card>
    );
  }

  const Icon = workoutIcon(workout.workoutType);
  const isBike = isBikeWorkout(workout.workoutType);
  const delivery = workout.delivery ?? null;
  const inZwift = Boolean(delivery?.intervalsEventId);
  // The two-state split: a coach adjustment is waiting (bike only), unless Mark
  // has dismissed it for this view (Ignore is a pure front-end dismiss — #99).
  const hasPendingChange = Boolean(delivery?.changed) && isBike && !ignored;
  const togglePanel = (next: 'edit' | 'swap' | 'skip') =>
    setPanel((current) => (current === next ? 'none' : next));

  let statusLine: string;
  if (!isBike) {
    statusLine = 'Non-bike session — nothing to upload to Zwift.';
  } else if (hasPendingChange) {
    statusLine = 'The coach adjusted today’s session off your sleep and recovery.';
  } else if (inZwift) {
    statusLine = 'Already in Zwift, ready to ride.';
  } else {
    statusLine = 'Not yet in Zwift.';
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between gap-2">
          <span>Today&apos;s session</span>
          <Badge variant={verdictBadgeVariant(verdict)}>{verdictLabel(verdict)}</Badge>
        </CardTitle>
        <CardDescription>The one thing to focus on now.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="rounded-xl border border-border bg-bg px-3 py-3">
          <div className="flex items-center gap-3">
            <Icon className="h-5 w-5 shrink-0 text-primary" aria-hidden />
            <div className="min-w-0 flex-1">
              <p className="font-medium text-text-primary">{workout.title}</p>
              <p className="text-sm text-text-secondary">
                {prettyType(workout.workoutType)}
                {workout.plannedDurationMin ? ` · ${workout.plannedDurationMin} min` : ''}
                {workout.intensityTarget ? ` · ${workout.intensityTarget}` : ''}
              </p>
            </div>
            {workout.adherence?.adherenceStatus ? (
              <Badge variant="muted" className="shrink-0 capitalize">
                {workout.adherence.adherenceStatus}
              </Badge>
            ) : null}
          </div>
          <p className="mt-2 text-xs text-text-secondary">{statusLine}</p>
        </div>

        {hasPendingChange && planAdjustments.length > 0 && (
          <div className="rounded-xl border border-warning/30 bg-warning/10 px-3 py-3 text-sm">
            <p className="mb-1 font-medium text-warning">Coach&apos;s suggested change</p>
            <ul className="ml-4 list-disc space-y-1 text-text-primary marker:text-warning">
              {planAdjustments.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
        )}

        <div className="flex flex-wrap gap-2">
          {hasPendingChange && (
            <>
              <Button
                type="button"
                size="sm"
                onClick={() => onApprove({ workoutId: workout.id })}
                disabled={busy}
              >
                <Check className="h-4 w-4" aria-hidden />
                Approve &amp; upload
              </Button>
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => setIgnored(true)}
                disabled={busy}
              >
                <X className="h-4 w-4" aria-hidden />
                Ignore
              </Button>
            </>
          )}
          {isBike && (
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => togglePanel('edit')}
              aria-expanded={panel === 'edit'}
            >
              <Pencil className="h-4 w-4" aria-hidden />
              {hasPendingChange ? 'Manual edit' : 'Edit'}
            </Button>
          )}
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => togglePanel('swap')}
            aria-expanded={panel === 'swap'}
          >
            <ArrowLeftRight className="h-4 w-4" aria-hidden />
            Swap day
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => togglePanel('skip')}
            aria-expanded={panel === 'skip'}
          >
            <Trash2 className="h-4 w-4" aria-hidden />
            Skip
          </Button>
        </div>

        {panel === 'edit' && (
          <div className="grid gap-3 rounded-lg border border-border bg-surface-elevated/60 px-3 py-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
            <div className="space-y-1.5">
              <Label htmlFor={`duration-${workout.id}`}>Duration %</Label>
              <Input
                id={`duration-${workout.id}`}
                type="number"
                min={50}
                max={125}
                step={5}
                value={durationScalePct}
                onChange={(event) => setDurationScalePct(event.target.value)}
                aria-label="Duration percentage"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor={`intensity-${workout.id}`}>Intensity %</Label>
              <Input
                id={`intensity-${workout.id}`}
                type="number"
                min={50}
                max={120}
                step={5}
                value={intensityScalePct}
                onChange={(event) => setIntensityScalePct(event.target.value)}
                aria-label="Intensity percentage"
              />
            </div>
            <Button
              type="button"
              size="sm"
              disabled={busy}
              onClick={() =>
                onEdit({
                  workoutId: workout.id,
                  durationScalePct: Number(durationScalePct),
                  intensityScalePct: Number(intensityScalePct),
                })
              }
            >
              {busy ? 'Saving…' : 'Apply & sync'}
            </Button>
          </div>
        )}

        {panel === 'swap' && (
          <div className="rounded-lg border border-border bg-surface-elevated/60 px-3 py-3">
            <p className="mb-2 text-sm text-text-secondary">Move this session to:</p>
            <div className="flex flex-wrap gap-2">
              {nextDays(subjectDate, 7).map((day) => (
                <Button
                  key={day.iso}
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={busy}
                  onClick={() => onSwap({ workoutId: workout.id, targetDate: day.iso })}
                >
                  {day.label}
                </Button>
              ))}
            </div>
          </div>
        )}

        {panel === 'skip' && (
          <div className="rounded-lg border border-error/30 bg-error/10 px-3 py-3">
            <p className="text-sm text-text-primary">
              Skip this session?{' '}
              {isBike && inZwift ? 'It will be removed from Zwift.' : 'It will be marked as skipped.'}
            </p>
            <div className="mt-2 flex gap-2">
              <Button
                type="button"
                size="sm"
                variant="destructive"
                disabled={busy}
                onClick={() => onSkip({ workoutId: workout.id })}
              >
                {busy ? 'Skipping…' : 'Confirm skip'}
              </Button>
              <Button type="button" size="sm" variant="outline" onClick={() => setPanel('none')}>
                Cancel
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function PostRideCard({
  items,
  onSaveCheckIn,
  savingActivityId,
  isSaving,
}: {
  items: Array<{
    id: string;
    activityId?: string | null;
    activityName?: string | null;
    generatedAtUtc: string;
    outputMarkdown: string;
    recoveryDecision?: { excluded?: boolean } | null;
    postRideCheckIn?: {
      subjectiveScore?: number | null;
      rpe?: number | null;
      feel?: string | null;
      notes?: string | null;
    } | null;
  }>;
  onSaveCheckIn: (payload: {
    activityId: string;
    subjectiveScore: number | null;
    rpe: number | null;
    feel: string | null;
    notes: string | null;
  }) => void;
  savingActivityId: string | null;
  isSaving: boolean;
}) {
  const [drafts, setDrafts] = useState<
    Record<string, { subjectiveScore: string; rpe: string; feel: string; notes: string }>
  >({});

  function formFor(item: {
    activityId?: string | null;
    postRideCheckIn?: {
      subjectiveScore?: number | null;
      rpe?: number | null;
      feel?: string | null;
      notes?: string | null;
    } | null;
  }) {
    const key = item.activityId ?? '';
    if (drafts[key]) return drafts[key];
    return {
      subjectiveScore:
        item.postRideCheckIn?.subjectiveScore != null ? String(item.postRideCheckIn.subjectiveScore) : '',
      rpe: item.postRideCheckIn?.rpe != null ? String(item.postRideCheckIn.rpe) : '',
      feel: item.postRideCheckIn?.feel ?? '',
      notes: item.postRideCheckIn?.notes ?? '',
    };
  }

  function patchDraft(
    activityId: string,
    patch: Partial<{ subjectiveScore: string; rpe: string; feel: string; notes: string }>,
    item: { postRideCheckIn?: { subjectiveScore?: number | null; rpe?: number | null; feel?: string | null; notes?: string | null } | null },
  ) {
    setDrafts((current) => ({
      ...current,
      [activityId]: { ...formFor({ activityId, postRideCheckIn: item.postRideCheckIn }), ...patch },
    }));
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Bike className="h-4 w-4 text-primary" aria-hidden />
          After your ride
        </CardTitle>
        <CardDescription>Your latest ride, recovery, and what it means for tomorrow.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {items.map((item) => (
          <div key={item.id} className="space-y-4 rounded-2xl border border-border bg-bg px-4 py-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="font-semibold text-text-primary">{item.activityName ?? 'Your ride'}</p>
                <p className="text-sm text-text-secondary">Generated {formatDateTime(item.generatedAtUtc)}</p>
              </div>
              {item.recoveryDecision?.excluded ? <Badge variant="warning">Not counted for recovery</Badge> : null}
            </div>
            {item.activityId ? (
              <PostRideCheckInForm
                activityId={item.activityId}
                value={formFor(item)}
                logged={Boolean(item.postRideCheckIn)}
                onChange={(patch) => patchDraft(item.activityId!, patch, item)}
                onSave={(value) =>
                  onSaveCheckIn({
                    activityId: item.activityId!,
                    subjectiveScore: value.subjectiveScore ? Number(value.subjectiveScore) : null,
                    rpe: value.rpe ? Number(value.rpe) : null,
                    feel: value.feel || null,
                    notes: value.notes || null,
                  })
                }
                isSaving={isSaving && savingActivityId === item.activityId}
              />
            ) : null}
            <div>
              <Markdown>{item.outputMarkdown}</Markdown>
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function PostRideCheckInForm({
  activityId,
  value,
  logged,
  onChange,
  onSave,
  isSaving,
}: {
  activityId: string;
  value: { subjectiveScore: string; rpe: string; feel: string; notes: string };
  logged: boolean;
  onChange: (patch: Partial<{ subjectiveScore: string; rpe: string; feel: string; notes: string }>) => void;
  onSave: (value: { subjectiveScore: string; rpe: string; feel: string; notes: string }) => void;
  isSaving: boolean;
}) {
  return (
    <div className="rounded-xl border border-border bg-surface-elevated/60 px-3 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-medium text-text-primary">How did it feel?</p>
        {logged ? <Badge variant="muted">Logged</Badge> : null}
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor={`post-ride-rpe-${activityId}`}>RPE</Label>
          <Input
            id={`post-ride-rpe-${activityId}`}
            inputMode="decimal"
            value={value.rpe}
            onChange={(event) => onChange({ rpe: event.target.value })}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor={`post-ride-legs-${activityId}`}>Legs</Label>
          <Input
            id={`post-ride-legs-${activityId}`}
            inputMode="numeric"
            placeholder="1-10"
            value={value.subjectiveScore}
            onChange={(event) => onChange({ subjectiveScore: event.target.value })}
          />
        </div>
        <div className="space-y-1.5 sm:col-span-2">
          <Label htmlFor={`post-ride-feel-${activityId}`}>Feel</Label>
          <Input
            id={`post-ride-feel-${activityId}`}
            value={value.feel}
            onChange={(event) => onChange({ feel: event.target.value })}
          />
        </div>
        <div className="space-y-1.5 sm:col-span-2">
          <Label htmlFor={`post-ride-notes-${activityId}`}>Niggles or notes</Label>
          <textarea
            id={`post-ride-notes-${activityId}`}
            className={textareaClassName}
            value={value.notes}
            onChange={(event) => onChange({ notes: event.target.value })}
          />
        </div>
      </div>
      <div className="mt-3 flex justify-end">
        <Button type="button" variant="outline" onClick={() => onSave(value)} disabled={isSaving}>
          {isSaving ? 'Saving...' : 'Save ride check-in'}
        </Button>
      </div>
    </div>
  );
}

function TomorrowCard({ tomorrowImpact, fallback }: { tomorrowImpact: string | null | undefined; fallback: string }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Tomorrow</CardTitle>
        <CardDescription>The next cue to keep in mind.</CardDescription>
      </CardHeader>
      <CardContent>
        <p className="text-sm leading-6 text-text-primary">{tomorrowImpact ?? fallback}</p>
      </CardContent>
    </Card>
  );
}

function SleepPrepCard() {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <MoonStar className="h-4 w-4 text-primary" aria-hidden />
          Tonight
        </CardTitle>
        <CardDescription>Keep the bedroom and bedtime routine working for you.</CardDescription>
      </CardHeader>
      <CardContent>
        <p className="text-sm leading-6 text-text-primary">
          Aim for the usual sleep setup: pre-cool the room, keep the evening calm, and stay on the bedtime routine.
        </p>
      </CardContent>
    </Card>
  );
}

function BedroomSummaryCard({
  thermal,
}: {
  thermal: {
    latestTemperatureC?: number | null;
    targetTemperatureC?: number | null;
    overnightLowC?: number | null;
    overnightWindMaxMph?: number | null;
    fan: FanState;
  };
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Thermometer className="h-4 w-4 text-primary" aria-hidden />
          Bedroom
        </CardTitle>
        <CardDescription>One tap away from the full climate detail.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
          <Stat
            label="Indoor now"
            value={thermal.latestTemperatureC != null ? `${thermal.latestTemperatureC.toFixed(1)}°C` : 'Not synced'}
          />
          <Stat
            label="Thermostat"
            value={thermal.targetTemperatureC != null ? `${thermal.targetTemperatureC.toFixed(1)}°C` : '—'}
          />
          <Stat
            label="Overnight low"
            value={thermal.overnightLowC != null ? `${thermal.overnightLowC.toFixed(1)}°C` : '—'}
          />
          <Stat
            label="Wind"
            value={thermal.overnightWindMaxMph != null ? `${thermal.overnightWindMaxMph.toFixed(0)} mph` : '—'}
            icon={<Wind className="h-3.5 w-3.5 text-text-muted" aria-hidden />}
          />
        </div>
        <div className="flex items-start gap-2 rounded-xl border border-border px-3 py-3 text-sm">
          <Fan className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden />
          <div className="min-w-0">
            <p className="font-medium text-text-primary">Bedroom fan</p>
            <p className="text-text-secondary">{fanStatusText(thermal.fan)}</p>
          </div>
        </div>
        <DetailLinkCard
          to="/bedroom"
          title="Bedroom & weather detail"
          description="Open the full room and overnight weather read, and control the fan."
        />
      </CardContent>
    </Card>
  );
}

/** One-line last-night room/fan glance, shown in the morning brief alongside last
 *  night's sleep (Batch 31) — it explains *last* night, not tonight's live fan state,
 *  so it belongs with the morning read rather than the evening bedroom card.
 *  Fetches the last completed night (shared cache with /bedroom) and stays silent
 *  until there's something to say, so Home never shows a spinner for it. */
function OvernightGlance() {
  const query = useBedroomOvernight();
  const summary = query.data?.data.summary;
  const glance = overnightGlanceText(summary);
  if (!glance) return null;
  return (
    <Link
      to="/bedroom"
      className="flex items-center justify-between gap-2 rounded-xl border border-border bg-bg px-3 py-2.5 text-sm transition hover:border-accent/40"
    >
      <span className="flex items-center gap-2 text-text-secondary">
        <LineChart className="h-4 w-4 shrink-0 text-primary" aria-hidden />
        {summary ? (
          <Badge
            variant={verdictBadgeVariant(summary.roomVerdict)}
            className="shrink-0"
            data-testid="overnight-room-verdict-badge"
          >
            {verdictToneLabel(summary.roomVerdict)}
          </Badge>
        ) : null}
        {glance}
      </span>
      <ChevronRight className="h-4 w-4 shrink-0 text-text-muted" aria-hidden />
    </Link>
  );
}

function DetailLinkCard({
  to,
  title,
  description,
}: {
  to: string;
  title: string;
  description: string;
}) {
  return (
    <Link
      to={to}
      className="flex items-center justify-between rounded-xl border border-border bg-bg px-4 py-4 transition hover:border-accent/40 hover:bg-panel"
    >
      <div>
        <p className="font-medium text-text-primary">{title}</p>
        <p className="mt-1 text-sm text-text-secondary">{description}</p>
      </div>
      <ChevronRight className="h-4 w-4 text-text-muted" aria-hidden />
    </Link>
  );
}

function Stat({
  label,
  value,
  hint,
  icon,
}: {
  label: string;
  value: string | number;
  hint?: string;
  icon?: ReactNode;
}) {
  return (
    <div className="rounded-xl border border-border px-3 py-3">
      <p className="flex items-center gap-1.5 text-xs text-text-muted">
        {icon}
        {label}
      </p>
      <p className="text-lg font-semibold text-text-primary">{value}</p>
      {hint && <p className="text-[11px] text-text-muted">{hint}</p>}
    </div>
  );
}
