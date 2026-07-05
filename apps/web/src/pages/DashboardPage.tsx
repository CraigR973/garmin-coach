import { useState, type ReactNode } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import {
  Activity,
  ArrowLeftRight,
  ArrowRight,
  BedDouble,
  Bike,
  CalendarDays,
  Check,
  ClipboardCheck,
  Dumbbell,
  MoonStar,
  MoreHorizontal,
  Pencil,
  Plus,
  Thermometer,
  Trash2,
  X,
  type LucideIcon,
} from 'lucide-react';
import { postRideCheckInInputSchema } from '@coach/shared';
import { toast } from 'sonner';
import type { AgeComparison, MetricBaselineRow } from '@/components/MetricComparisonTable';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { CollapsibleSection } from '@/components/CollapsibleSection';
import { ErrorState, OfflineNotice } from '@/components/EmptyState';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Markdown } from '@/components/Markdown';
import { PageHeader } from '@/components/PageHeader';
import { Skeleton } from '@/components/ui/skeleton';
import { Textarea } from '@/components/ui/textarea';
import { VerdictHero } from '@/components/VerdictHero';
import { SleepSnapshotBody } from '@/components/SleepSnapshotBody';
import { SleepPrepBody } from '@/components/SleepPrepBody';
import { BedroomBody } from '@/components/BedroomBody';
import { DetailLinkCard } from '@/components/DetailLinkCard';
import { useAuth } from '@/contexts/AuthContext';
import { isBikeWorkout, useDailyPhase } from '@/hooks/useDailyPhase';
import { useDailyLoop, type DailyLoopData } from '@/hooks/useDailyLoop';
import { useOnlineStatus } from '@/hooks/useOnlineStatus';
import { apiFetch } from '@/lib/api';
import { cn } from '@/lib/utils';
import { formatDateTime, friendlyDate, hm, nextDays, remContext, type FanState } from '@/lib/dailyFlow';
import { greetingForNow, verdictLabel } from '@/lib/copy';
import { dayStateForWorkouts, type DayCategory } from '@/lib/workoutCategories';
import { actionSection, nextAction, type NextAction } from '@/lib/homeActions';
import { hasReviewedSleep } from '@/lib/sleepReview';
import {
  isEveningNow,
  orderedSections,
  primarySection,
  sectionLane,
  splitPrimaryDetail,
  type HomeSectionKey,
} from '@/lib/homeSections';

const SLEEP_PREP_SUMMARY = 'Keep the bedroom and bedtime routine working for you.';

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

type TodaySleep = {
  qualifier?: string | null;
  durationSec?: number | null;
  remSleepSec?: number | null;
} | null;

/** Collapsed one-liner for the "Last night's sleep" section (from the daily-loop
 *  payload — no bedroom-overnight query, so a collapsed sleep card stays lazy). */
function sleepSummary(sleep: TodaySleep): string {
  if (!sleep) return 'No sleep data has synced for last night yet.';
  const parts = [`${hm(sleep.durationSec)} asleep`];
  if (sleep.qualifier) parts.push(sleep.qualifier);
  const rem = remContext(sleep.remSleepSec);
  if (rem) parts.push(`REM ${rem}`);
  return parts.join(' · ');
}

type SummaryTone = 'default' | 'warning';
type SectionSummary = { text: string; tone: SummaryTone };

/** Collapsed one-liner + tone for the Today section — the day's session titles,
 *  flagged `warning` when the coach has eased a bike session that still needs a
 *  decision (Batch 50), so a collapsed Today signals it holds a pending action. */
function todaySummary(workouts: TodayWorkout[]): SectionSummary {
  if (workouts.length === 0) return { text: 'Rest is the plan today.', tone: 'default' };
  const text = workouts.map((workout) => workout.title).join(' · ');
  const tone: SummaryTone = workouts.some(
    (workout) => Boolean(workout.delivery?.changed) && isBikeWorkout(workout.workoutType),
  )
    ? 'warning'
    : 'default';
  return { text, tone };
}

/** Collapsed one-liner + tone for the After-your-ride section — flagged
 *  `warning` while a ride's "how did it feel" check-in is still unlogged. */
function afterRideSummary(
  items: Array<{ activityName?: string | null; postRideCheckIn?: unknown }>,
): SectionSummary {
  if (items.length === 0) return { text: '', tone: 'default' };
  const text = items.map((item) => item.activityName ?? 'Your ride').join(' · ');
  const tone: SummaryTone = items.some((item) => item.postRideCheckIn == null)
    ? 'warning'
    : 'default';
  return { text, tone };
}

/** DOM id for a Home section card, so the Next strip can scroll to it. */
function sectionDomId(key: HomeSectionKey): string {
  return `home-section-${key}`;
}

/** Collapsed one-liner for the Bedroom section — live indoor read + fan mode. */
function bedroomSummary(thermal: { latestTemperatureC?: number | null; fan: FanState }): string {
  const temp =
    thermal.latestTemperatureC != null ? `${thermal.latestTemperatureC.toFixed(1)}°C` : 'not synced';
  const fan = thermal.fan.autoEnabled ? 'fan on auto' : 'fan on manual';
  return `Indoor ${temp} · ${fan}`;
}

export function DashboardPage() {
  const { player } = useAuth();
  const queryClient = useQueryClient();
  const isOnline = useOnlineStatus();
  const query = useDailyLoop();
  const greeting = `${greetingForNow()}${player ? `, ${player.displayName}` : ''}`;
  const data = query.data?.data;
  // One clock read threaded through both the phase and the section ordering, so
  // they never disagree on whether it's evening (Batch 48 wind_down phase).
  const isEvening = isEveningNow();
  const phase = useDailyPhase(data, isEvening);
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
        <ErrorState
          title="Today's brief couldn't load"
          description={query.error instanceof Error ? query.error.message : "We couldn't reach the server just now."}
          onRetry={() => query.refetch()}
        />
      </div>
    );
  }

  const daily = data!;
  const analysis = daily.morningAnalysis;
  const ageComparison = (analysis?.ageComparison ?? null) as AgeComparison | null;
  const metricsVsBaselines = (analysis?.metricsVsBaselines ?? []) as MetricBaselineRow[];
  const chronicSuggestions = daily.chronicSuggestions ?? null;
  const sleep = daily.sleep;
  const thermal = daily.thermalState;
  const postWorkouts = daily.postWorkoutAnalyses ?? [];
  const postFlexibilityAnalyses = daily.postFlexibilityAnalyses ?? [];
  const postStrengthAnalyses = daily.postStrengthAnalyses ?? [];
  const postWalkAnalyses = daily.postWalkAnalyses ?? [];
  const hasRide = postWorkouts.length > 0;
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

  // Tomorrow's cue: the ride's forward look when we have one, else a verdict-shaped
  // fallback. Shared by the section summary and body so they never disagree.
  const tomorrowText =
    postWorkouts[0]?.tomorrowImpact ??
    (analysis?.verdict
      ? `${verdictLabel(analysis.verdict)} tomorrow starts from today's recovery picture.`
      : "Tomorrow's cue will show up here after the coach read.");

  // Batch 50: the one context-aware action drives both the Next strip and — via
  // its section override — which section is expanded, so a pending item is never
  // stranded in a collapsed off-phase section. It falls back to the Batch 48
  // phase primary when the action navigates away or everything is clear.
  //
  // The morning (pre-training / rest-day, i.e. not yet trained and not evening)
  // re-orders to sleep → check-in → eased ride (confirmed 2026-07-05); the sleep
  // rung completes off a per-day client flag set when Mark opens `/sleep`.
  const isMorning = phase === 'pre_training' || phase === 'rest_day';
  const action = nextAction(daily, {
    isEvening,
    isMorning,
    hasReviewedSleep: hasReviewedSleep(daily.subjectDate),
  });
  const primary = actionSection(action) ?? primarySection(phase, { hasRide });
  // Batch 37: render the full section set every load; exactly one is expanded
  // (the action/phase primary). Presence is only ever gated by hasRide.
  const order = orderedSections(phase, { hasRide, isEvening, primary });
  // Batch 54: the lead section stays prominent; the rest recede under "More detail".
  const { lead, detail } = splitPrimaryDetail(order, primary);
  const scrollToSection = (key: HomeSectionKey) => {
    document
      .getElementById(sectionDomId(key))
      ?.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
  };

  const todaySummaryValue = todaySummary(todaysWorkouts);
  const afterRideSummaryValue = afterRideSummary(postWorkouts);

  const sections: Record<
    HomeSectionKey,
    { title: string; icon: ReactNode; summary: ReactNode; tone?: SummaryTone; body: ReactNode }
  > = {
    lastNight: {
      title: "Last night's sleep",
      icon: <BedDouble className="h-4 w-4 text-primary" aria-hidden />,
      summary: sleepSummary(sleep),
      body: (
        <SleepSnapshotBody
          metricsVsBaselines={metricsVsBaselines}
          ageComparison={ageComparison}
          chronicSuggestions={chronicSuggestions}
          morningBriefLink="/brief"
        />
      ),
    },
    today: {
      title: `${dayState.label} day`,
      icon: <CalendarDays className="h-4 w-4 text-primary" aria-hidden />,
      summary: todaySummaryValue.text,
      tone: todaySummaryValue.tone,
      body: (
        <DayPlanBody
          workouts={todaysWorkouts}
          planAdjustments={analysis?.planAdjustments ?? []}
          flexibilityAnalyses={postFlexibilityAnalyses}
          strengthAnalyses={postStrengthAnalyses}
          walkAnalyses={postWalkAnalyses}
          walkingBrief={daily.walkingBrief ?? null}
          breathworkBrief={daily.breathworkBrief ?? null}
          subjectDate={daily.subjectDate}
          workoutActions={todayActions}
          dayActions={dayActions}
        />
      ),
    },
    afterRide: {
      title: 'After your ride',
      icon: <Bike className="h-4 w-4 text-primary" aria-hidden />,
      summary: afterRideSummaryValue.text,
      tone: afterRideSummaryValue.tone,
      body: (
        <PostRideBody
          items={postWorkouts}
          onSaveCheckIn={(payload) => postRideCheckInMutation.mutate(payload)}
          savingActivityId={postRideCheckInMutation.variables?.activityId ?? null}
          isSaving={postRideCheckInMutation.isPending}
        />
      ),
    },
    tomorrow: {
      title: 'Tomorrow',
      icon: <CalendarDays className="h-4 w-4 text-primary" aria-hidden />,
      summary: tomorrowText,
      body: <TomorrowBody text={tomorrowText} />,
    },
    tonight: {
      title: 'Tonight',
      icon: <MoonStar className="h-4 w-4 text-primary" aria-hidden />,
      summary: daily.sleepProjection?.headline ?? SLEEP_PREP_SUMMARY,
      // Batch 50: Home's evening cards stay compact and defer to the Sleep hub
      // (Batch 49) rather than duplicating the full wind-down controls.
      body: (
        <div className="space-y-4">
          <SleepPrepBody projection={daily.sleepProjection ?? null} />
          <DetailLinkCard
            to="/sleep"
            title="Tonight's sleep & bedroom"
            description="Open the full wind-down plan and fan controls."
          />
        </div>
      ),
    },
    bedroom: {
      title: 'Bedroom',
      icon: <Thermometer className="h-4 w-4 text-primary" aria-hidden />,
      summary: bedroomSummary(thermal),
      body: <BedroomBody thermal={thermal} />,
    },
  };

  return (
    <div className="space-y-5">
      {!isOnline && (
        <OfflineNotice
          description={`You're offline — showing your last saved brief for ${friendlyDate(daily.subjectDate)}.`}
        />
      )}

      {/* Batch 54: a compact greeting lockup (was the full PageHeader h1) so the
          verdict sits higher on cold load. */}
      <div className="flex items-baseline justify-between gap-3">
        <p className="text-sm font-medium text-text-secondary">{greeting}</p>
        <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-text-muted">
          {friendlyDate(daily.subjectDate)}
        </p>
      </div>

      <VerdictHero verdict={analysis?.verdict} dateLabel={friendlyDate(daily.subjectDate)} />

      <NextActionStrip action={action} onGoToSection={scrollToSection} />

      {/* Batch 51: on md+ the sections split into an act lane (Today / After
          your ride / Tomorrow) and a context lane (Last night / Tonight /
          Bedroom), sharing one grid so mobile keeps its single stacked column
          (grid-cols-1) without a second, duplicate render tree. Batch 54: the
          one lead/primary section stays prominent; everything else recedes
          under a quiet "More detail" grouping (still present — collapse-not-
          remove kept), one variant lighter and defaulted closed. */}
      <div className="grid grid-cols-1 gap-5 md:grid-cols-2 md:items-start">
        {lead ? (
          <CollapsibleSection
            id={sectionDomId(lead)}
            title={sections[lead].title}
            icon={sections[lead].icon}
            summary={sections[lead].summary}
            tone={sections[lead].tone}
            defaultOpen
            className={sectionLane(lead) === 'act' ? 'md:col-start-1' : 'md:col-start-2'}
          >
            {sections[lead].body}
          </CollapsibleSection>
        ) : null}
        {detail.length > 0 ? (
          <p className="font-mono text-[10px] uppercase tracking-[0.25em] text-text-muted md:col-span-2">
            More detail
          </p>
        ) : null}
        {detail.map((key) => {
          const section = sections[key];
          const lane = sectionLane(key);
          return (
            <CollapsibleSection
              key={key}
              id={sectionDomId(key)}
              title={section.title}
              icon={section.icon}
              summary={section.summary}
              tone={section.tone}
              variant="secondary"
              defaultOpen={false}
              className={lane === 'act' ? 'md:col-start-1' : 'md:col-start-2'}
            >
              {section.body}
            </CollapsibleSection>
          );
        })}
      </div>
    </div>
  );
}

/**
 * The "Next" strip under the verdict hero (Batch 50): the single context-aware
 * primary action for right now. A `to` action navigates away (e.g. Check in);
 * a `sectionKey` action scrolls to its Home section (already expanded by the
 * action override); the all-clear state is a quiet, button-less line.
 */
function NextActionStrip({
  action,
  onGoToSection,
}: {
  action: NextAction;
  onGoToSection: (key: HomeSectionKey) => void;
}) {
  if (action.key === 'all-set') {
    return (
      <div
        role="status"
        className="flex items-center gap-3 rounded-2xl border border-success/30 bg-success/10 px-4 py-4 text-sm text-text-secondary shadow-sm"
      >
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-success/15 text-success">
          <Check className="h-4 w-4" aria-hidden />
        </span>
        <span>
          <span className="font-medium text-text-primary">{action.label}</span> — nothing needs a decision right now.
        </span>
      </div>
    );
  }
  const isWarning = action.tone === 'warning';
  return (
    <section
      aria-label="Next action"
      className={cn(
        'flex flex-col gap-3 rounded-2xl border px-4 py-4 shadow-sm sm:flex-row sm:items-center sm:justify-between',
        isWarning ? 'border-warning/45 bg-warning/10' : 'border-accent/45 bg-accent/10',
      )}
    >
      <div className="min-w-0">
        <p className={cn('font-mono text-[10px] uppercase tracking-[0.25em]', isWarning ? 'text-warning' : 'text-accent')}>
          Next
        </p>
        <p className="mt-1 text-base font-semibold text-text-primary">{action.label}</p>
      </div>
      {action.to ? (
        <Button asChild size="sm" variant={isWarning ? 'default' : 'accent'} className="w-full sm:w-auto">
          <Link to={action.to}>
            <ArrowRight className="mr-1.5 h-4 w-4" aria-hidden />
            {action.label}
          </Link>
        </Button>
      ) : (
        <Button
          size="sm"
          variant={isWarning ? 'default' : 'accent'}
          className="w-full sm:w-auto"
          onClick={() => action.sectionKey && onGoToSection(action.sectionKey)}
        >
          <ArrowRight className="mr-1.5 h-4 w-4" aria-hidden />
          {action.label}
        </Button>
      )}
    </section>
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

/** The expanded body of the Today section: the day's session rows plus the
 *  day-level footer. The day label + verdict badge live in the section header
 *  (Batch 36 unified card, Batch 37 collapse). */
function DayPlanBody({
  workouts,
  planAdjustments,
  flexibilityAnalyses,
  strengthAnalyses,
  walkAnalyses,
  walkingBrief,
  breathworkBrief,
  subjectDate,
  workoutActions,
  dayActions,
}: {
  workouts: TodayWorkout[];
  planAdjustments: string[];
  flexibilityAnalyses: DailyLoopData['postFlexibilityAnalyses'];
  strengthAnalyses: DailyLoopData['postStrengthAnalyses'];
  walkAnalyses: DailyLoopData['postWalkAnalyses'];
  walkingBrief: DailyLoopData['walkingBrief'] | null;
  breathworkBrief: DailyLoopData['breathworkBrief'] | null;
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
    <div className="space-y-4">
      {hasWorkouts ? (
        <div className="space-y-4">
          {workouts.map((workout, index) => (
            <div
              key={workout.id}
              className={index > 0 ? 'space-y-3 border-t border-border pt-4' : 'space-y-3'}
            >
              <WorkoutRow
                workout={workout}
                planAdjustments={planAdjustments}
                subjectDate={subjectDate}
                {...workoutActions}
              />
            </div>
          ))}
        </div>
      ) : (
        <p className="rounded-xl border border-dashed border-border px-4 py-4 text-sm text-text-secondary">
          Rest is the plan today. Add something light, swap a workout in from the week, or just record what happened.
        </p>
      )}

      {flexibilityAnalyses.length > 0 ? <FlexibilityReadList items={flexibilityAnalyses} /> : null}
      {strengthAnalyses.length > 0 ? <StrengthReadList items={strengthAnalyses} /> : null}
      {walkAnalyses.length > 0 ? <WalkReadList items={walkAnalyses} /> : null}
      {walkingBrief ? <WalkingBriefPanel brief={walkingBrief} /> : null}
      {breathworkBrief ? <BreathworkBriefPanel brief={breathworkBrief} /> : null}

      <div className={`space-y-3${hasWorkouts ? ' border-t border-border pt-4' : ''}`}>
        <AddWorkoutButtons busy={dayActions.busy} onAddWorkout={dayActions.onAddWorkout} />
        <div className="flex flex-wrap gap-2">
          <Button asChild type="button" size="sm" variant="outline">
            <Link to="/delivery">
              <CalendarDays className="h-4 w-4" aria-hidden />
              View week
            </Link>
          </Button>
          {/* Batch 50: the prominent Check-in button moved into the Next strip;
              this is its always-available fallback. Named "Morning check-in"
              (not just "Check in") so it isn't confused with the per-ride
              "How did it feel?" check-in on the After-your-ride card below. */}
          <Button asChild type="button" size="sm" variant="outline">
            <Link to="/check-in">
              <ClipboardCheck className="h-4 w-4" aria-hidden />
              Morning check-in
            </Link>
          </Button>
          {hasWorkouts && (
            <Button type="button" size="sm" variant="outline" onClick={dayActions.onSkipDay} disabled={dayActions.busy}>
              <Trash2 className="h-4 w-4" aria-hidden />
              Skip whole day
            </Button>
          )}
        </div>
        <ActualWorkoutForm busy={dayActions.busy} onSubmit={dayActions.onRecordActual} />
      </div>
    </div>
  );
}

function WalkingBriefPanel({
  brief,
}: {
  brief: NonNullable<DailyLoopData['walkingBrief']>;
}) {
  const distanceKm = brief.window4w.totalDistanceM / 1000;
  return (
    <div className="rounded-xl border border-border bg-bg px-3 py-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-semibold text-text-primary">Walking base</p>
          <p className="text-sm text-text-secondary">
            {brief.window4w.sessionCount} walks · {distanceKm.toFixed(1)} km · {brief.window4w.totalDurationMin} min in 4 weeks
          </p>
        </div>
        <Badge variant="muted">{brief.trend.replace(/_/g, ' ')}</Badge>
      </div>
      <p className="mt-2 text-sm text-text-secondary">{brief.trendReason}</p>
    </div>
  );
}

function BreathworkBriefPanel({
  brief,
}: {
  brief: NonNullable<DailyLoopData['breathworkBrief']>;
}) {
  return (
    <div className="rounded-xl border border-border bg-bg px-3 py-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-semibold text-text-primary">Breathwork rhythm</p>
          <p className="text-sm text-text-secondary">
            {brief.window4w.sessionCount} sessions · {brief.window4w.totalDurationMin} min in 4 weeks
          </p>
        </div>
        <Badge variant="muted">{brief.trend.replace(/_/g, ' ')}</Badge>
      </div>
      <p className="mt-2 text-sm text-text-secondary">{brief.trendReason}</p>
    </div>
  );
}

function FlexibilityReadList({
  items,
}: {
  items: DailyLoopData['postFlexibilityAnalyses'];
}) {
  return (
    <div className="space-y-3 rounded-xl border border-border bg-bg px-3 py-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-semibold text-text-primary">Flexibility read</p>
          <p className="text-sm text-text-secondary">
            {items.length === 1 ? items[0].activityName ?? 'Mobility session' : `${items.length} mobility sessions`}
          </p>
        </div>
        <Badge variant="muted">Advisory</Badge>
      </div>
      <div className="space-y-4">
        {items.map((item) => (
          <div key={item.id} className="space-y-2 border-t border-border pt-3 first:border-t-0 first:pt-0">
            <p className="text-xs text-text-secondary">Generated {formatDateTime(item.generatedAtUtc)}</p>
            <Markdown>{item.outputMarkdown}</Markdown>
          </div>
        ))}
      </div>
    </div>
  );
}

function StrengthReadList({
  items,
}: {
  items: DailyLoopData['postStrengthAnalyses'];
}) {
  return (
    <div className="space-y-3 rounded-xl border border-border bg-bg px-3 py-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-semibold text-text-primary">Strength read</p>
          <p className="text-sm text-text-secondary">
            {items.length === 1 ? items[0].activityName ?? 'Strength session' : `${items.length} strength sessions`}
          </p>
        </div>
        <Badge variant="muted">Advisory</Badge>
      </div>
      <div className="space-y-4">
        {items.map((item) => (
          <div key={item.id} className="space-y-2 border-t border-border pt-3 first:border-t-0 first:pt-0">
            <p className="text-xs text-text-secondary">Generated {formatDateTime(item.generatedAtUtc)}</p>
            <Markdown>{item.outputMarkdown}</Markdown>
          </div>
        ))}
      </div>
    </div>
  );
}

function WalkReadList({
  items,
}: {
  items: DailyLoopData['postWalkAnalyses'];
}) {
  return (
    <div className="space-y-3 rounded-xl border border-border bg-bg px-3 py-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-semibold text-text-primary">Walk read</p>
          <p className="text-sm text-text-secondary">
            {items.length === 1 ? items[0].activityName ?? 'Deliberate walk' : `${items.length} deliberate walks`}
          </p>
        </div>
        <Badge variant="muted">Advisory</Badge>
      </div>
      <div className="space-y-4">
        {items.map((item) => (
          <div key={item.id} className="space-y-2 border-t border-border pt-3 first:border-t-0 first:pt-0">
            <p className="text-xs text-text-secondary">Generated {formatDateTime(item.generatedAtUtc)}</p>
            <Markdown>{item.outputMarkdown}</Markdown>
          </div>
        ))}
      </div>
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
        <Textarea
          id="actual-notes"
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

type WorkoutRowButton = {
  label: string;
  icon: LucideIcon;
  onClick: () => void;
  ariaExpanded?: boolean;
};

/**
 * The session card's action cluster (Batch 54): one primary + one secondary
 * button, with anything else tucked into a "More options" overflow menu — was
 * a flat five-button row (Approve, Ignore, Manual edit, Swap day, Skip).
 */
function WorkoutRowActions({
  hasPendingChange,
  isBike,
  panel,
  busy,
  onApprove,
  onIgnore,
  onTogglePanel,
}: {
  hasPendingChange: boolean;
  isBike: boolean;
  panel: 'none' | 'edit' | 'swap' | 'skip';
  busy: boolean;
  onApprove: () => void;
  onIgnore: () => void;
  onTogglePanel: (next: 'edit' | 'swap' | 'skip') => void;
}) {
  const primaryAction: WorkoutRowButton = hasPendingChange
    ? { label: 'Approve & upload', icon: Check, onClick: onApprove }
    : isBike
      ? { label: 'Edit', icon: Pencil, onClick: () => onTogglePanel('edit'), ariaExpanded: panel === 'edit' }
      : { label: 'Swap day', icon: ArrowLeftRight, onClick: () => onTogglePanel('swap'), ariaExpanded: panel === 'swap' };

  const secondaryAction: WorkoutRowButton = hasPendingChange
    ? { label: 'Ignore', icon: X, onClick: onIgnore }
    : isBike
      ? { label: 'Swap day', icon: ArrowLeftRight, onClick: () => onTogglePanel('swap'), ariaExpanded: panel === 'swap' }
      : { label: 'Skip', icon: Trash2, onClick: () => onTogglePanel('skip'), ariaExpanded: panel === 'skip' };

  const overflowActions: WorkoutRowButton[] = hasPendingChange
    ? [
        { label: 'Manual edit', icon: Pencil, onClick: () => onTogglePanel('edit') },
        { label: 'Swap day', icon: ArrowLeftRight, onClick: () => onTogglePanel('swap') },
        { label: 'Skip', icon: Trash2, onClick: () => onTogglePanel('skip') },
      ]
    : isBike
      ? [{ label: 'Skip', icon: Trash2, onClick: () => onTogglePanel('skip') }]
      : [];

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button
        type="button"
        size="sm"
        onClick={primaryAction.onClick}
        disabled={busy}
        aria-expanded={primaryAction.ariaExpanded}
      >
        <primaryAction.icon className="h-4 w-4" aria-hidden />
        {primaryAction.label}
      </Button>
      <Button
        type="button"
        size="sm"
        variant="outline"
        onClick={secondaryAction.onClick}
        disabled={busy}
        aria-expanded={secondaryAction.ariaExpanded}
      >
        <secondaryAction.icon className="h-4 w-4" aria-hidden />
        {secondaryAction.label}
      </Button>
      {overflowActions.length > 0 ? (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button type="button" size="sm" variant="ghost" disabled={busy} aria-label="More options">
              <MoreHorizontal className="h-4 w-4" aria-hidden />
              More options
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {overflowActions.map((action) => (
              <DropdownMenuItem key={action.label} disabled={busy} onSelect={action.onClick}>
                <action.icon className="h-4 w-4" aria-hidden />
                {action.label}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      ) : null}
    </div>
  );
}

/** A single planned session inside the day's Today card. Each row keeps its
 *  own local panel/ignored/dial state so multiple sessions on a mixed day
 *  expand independently and their controls never cross-wire (Batch 36). */
function WorkoutRow({
  workout,
  planAdjustments = [],
  subjectDate,
  busy,
  onEdit,
  onApprove,
  onSkip,
  onSwap,
}: {
  workout: TodayWorkout;
  planAdjustments?: string[];
  subjectDate: string;
} & TodayWorkoutActions) {
  const [panel, setPanel] = useState<'none' | 'edit' | 'swap' | 'skip'>('none');
  const [ignored, setIgnored] = useState(false);
  const [durationScalePct, setDurationScalePct] = useState('100');
  const [intensityScalePct, setIntensityScalePct] = useState('100');

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
    <>
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

        <WorkoutRowActions
          hasPendingChange={hasPendingChange}
          isBike={isBike}
          panel={panel}
          busy={busy}
          onApprove={() => onApprove({ workoutId: workout.id })}
          onIgnore={() => setIgnored(true)}
          onTogglePanel={togglePanel}
        />
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
    </>
  );
}

/** The expanded body of the After-your-ride section: each ride's check-in +
 *  analysis. */
type RideIntervalRow = DailyLoopData['postWorkoutAnalyses'][number]['intervals'][number];

function intervalAdherenceBadge(adherence: RideIntervalRow['adherence']) {
  if (adherence === 'on') return { variant: 'success' as const, label: 'On target' };
  if (adherence === 'over') return { variant: 'warning' as const, label: 'Over' };
  if (adherence === 'under') return { variant: 'warning' as const, label: 'Under' };
  return null;
}

function intervalTarget(interval: RideIntervalRow): string {
  const { targetPctFtpLow: low, targetPctFtpHigh: high } = interval;
  if (low == null || high == null) return '—';
  return low === high ? `${low}%` : `${low}–${high}%`;
}

// Batch 44: the graded work intervals, so the read is legible at a glance — warm-up,
// recovery, and cool-down are not graded, so the table shows work intervals only and
// renders nothing for a free/outdoor ride with no planned structure.
function RideIntervalTable({ intervals }: { intervals: RideIntervalRow[] }) {
  const work = intervals.filter((interval) => interval.role === 'work');
  if (work.length === 0) return null;
  return (
    <div className="space-y-2">
      <p className="text-sm font-semibold text-text-primary">Interval execution</p>
      <p className="text-xs text-text-secondary">
        Work intervals graded against their own %FTP targets. Warm-up, recovery, and cool-down are
        not graded.
      </p>
      <div className="overflow-hidden rounded-lg border border-border">
        <table className="w-full border-collapse text-left text-sm">
          <thead>
            <tr className="bg-surface-elevated text-xs text-text-muted">
              <th className="px-3 py-2 font-medium">Interval</th>
              <th className="px-3 py-2 font-medium">Target</th>
              <th className="px-3 py-2 font-medium">Held</th>
              <th className="px-3 py-2 font-medium">Read</th>
            </tr>
          </thead>
          <tbody>
            {work.map((interval) => {
              const badge = intervalAdherenceBadge(interval.adherence);
              return (
                <tr key={interval.index} className="border-t border-border">
                  <td className="px-3 py-2 text-text-primary">
                    {Math.round(interval.durationSec / 60)} min {interval.label}
                  </td>
                  <td className="px-3 py-2 text-text-secondary">{intervalTarget(interval)}</td>
                  <td className="px-3 py-2 text-text-secondary">
                    {interval.pctFtp != null ? `${Math.round(interval.pctFtp)}%` : '—'}
                    {interval.normalizedPowerWatts != null
                      ? ` · ${Math.round(interval.normalizedPowerWatts)} W`
                      : ''}
                  </td>
                  <td className="px-3 py-2">
                    <span className="flex flex-wrap items-center gap-1.5">
                      {badge ? <Badge variant={badge.variant}>{badge.label}</Badge> : null}
                      {interval.fade ? (
                        <span className="text-xs text-warning">fading</span>
                      ) : (
                        <span className="text-xs text-text-muted">steady</span>
                      )}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function PostRideBody({
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
    intervals?: RideIntervalRow[];
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
    <div className="space-y-4">
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
          <RideIntervalTable intervals={item.intervals ?? []} />
        </div>
      ))}
    </div>
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
          <Textarea
            id={`post-ride-notes-${activityId}`}
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

function TomorrowBody({ text }: { text: string }) {
  return <p className="text-sm leading-6 text-text-primary">{text}</p>;
}
