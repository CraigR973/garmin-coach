import { useEffect, useState, type ReactNode } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import {
  Activity,
  ArrowLeftRight,
  ArrowRight,
  BedDouble,
  Bike,
  BookOpen,
  CalendarDays,
  Check,
  ChevronDown,
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
import {
  plannedWorkoutAdherenceInputSchema,
  postRideCheckInInputSchema,
  quickAddOptionsEnvelopeSchema,
} from '@coach/shared';
import { toast } from 'sonner';
import type { AgeComparison, MetricBaselineRow } from '@/components/MetricComparisonTable';
import { QuickAddSheet } from '@/components/QuickAddSheet';
import { IntervalWorkoutEditor } from '@/components/IntervalWorkoutEditor';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { CollapsibleSection } from '@/components/CollapsibleSection';
import { ErrorState, OfflineNotice, StaleDataNotice } from '@/components/EmptyState';
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
import { GoodMorningCta } from '@/components/GoodMorningCta';
import { BriefGeneratingCta } from '@/components/BriefGeneratingCta';
import { BriefFailedCta } from '@/components/BriefFailedCta';
import { FeedbackControl } from '@/components/FeedbackControl';
import { SleepSnapshotBody } from '@/components/SleepSnapshotBody';
import { SleepPrepBody } from '@/components/SleepPrepBody';
import { BedroomBody } from '@/components/BedroomBody';
import { DetailLinkCard } from '@/components/DetailLinkCard';
import { WeeklyMixCard } from '@/components/WeeklyMixCard';
import { TodayActions } from '@/components/TodayActions';
import { useAuth } from '@/contexts/AuthContext';
import { isBikeWorkout, useDailyPhase } from '@/hooks/useDailyPhase';
import { fetchDailyLoop, useDailyLoop, type DailyLoopData } from '@/hooks/useDailyLoop';
import { useOnlineStatus } from '@/hooks/useOnlineStatus';
import { apiFetch } from '@/lib/api';
import { postWorkoutReadFailure } from '@/lib/postWorkoutRead';
import { bedroomLiveSummary } from '@/lib/bedroom';
import { cn } from '@/lib/utils';
import {
  formatDateTime,
  friendlyDate,
  hm,
  localTodayIso,
  nextDays,
  remContext,
} from '@/lib/dailyFlow';
import { greetingForNow, personalStatusLine, verdictLabel } from '@/lib/copy';
import { dayStateForWorkouts, workoutTypeLabel, type DayCategory } from '@/lib/workoutCategories';
import { actionSection, nextAction, type NextAction } from '@/lib/homeActions';
import { hasReviewedSleep } from '@/lib/sleepReview';
import { hasReviewedBrief } from '@/lib/briefReview';
import { hasSeenWalkRead, markWalkReadSeen } from '@/lib/walkRead';
import { subjectiveFeelLabel } from '@/lib/subjectiveFeel';
import { visibleTodayActions } from '@/lib/todayActions';
import {
  isEveningNow,
  orderedSections,
  primarySection,
  sectionLane,
  splitPrimaryDetail,
  type HomeSectionKey,
} from '@/lib/homeSections';

const SLEEP_PREP_SUMMARY = 'Keep the bedroom and bedtime routine working for you.';

function holidayResumeLabel(endDate: string | null | undefined): string {
  return endDate ? friendlyDate(endDate) : 'when you are back';
}

function holidayDormantSummary(endDate: string | null | undefined): string {
  return `Away on holiday — resumes ${holidayResumeLabel(endDate)}.`;
}

function HolidayDormantBody({
  kind,
  endDate,
}: {
  kind: 'sleep' | 'bedroom';
  endDate: string | null | undefined;
}) {
  const description =
    kind === 'sleep'
      ? "Tonight's wind-down stays paused while you are away."
      : 'The bedroom fan and room checks stay paused while you are away.';
  return (
    <div className="space-y-4">
      <div className="rounded-2xl border border-dashed border-border bg-bg px-4 py-4">
        <p className="font-medium text-text-primary">Away on holiday</p>
        <p className="mt-1 text-sm text-text-secondary">
          {description} These surfaces resume {holidayResumeLabel(endDate)}.
        </p>
      </div>
      <DetailLinkCard
        to="/holiday"
        title="Open Holiday"
        description="Review or resume your holiday window."
      />
    </div>
  );
}

function workoutIcon(type: string): LucideIcon {
  const t = type.toLowerCase();
  if (/dumbbell|bodyweight|strength|resist/.test(t)) return Dumbbell;
  if (/bike|cycl|ride|vo2|z2|sweet|endurance|tempo|threshold/.test(t)) return Bike;
  return Activity;
}


function morningFeelRecap(manualEntry: DailyLoopData['manualEntry']) {
  const label = subjectiveFeelLabel(manualEntry?.subjectiveScore);
  const feel = manualEntry?.feel?.trim();

  if (!label) return null;

  return {
    title: 'How you feel today',
    text: `You said: ${label}${feel ? ` · ${feel}` : ''}`,
    ctaLabel: 'Change',
    ctaTo: '/check-in',
  };
}

/**
 * Batch 96: today's brief has landed but Mark hasn't opened it yet — lead
 * above the Today action block (and the thermal/plan nudges inside it) with a
 * prominent read-it CTA, so the freshly generated read outranks "Pre-cool the
 * bedroom" rather than sitting one tap under it. Clears (via `/brief`'s own
 * `markBriefReviewed`) the moment he opens the brief; a per-day flag, mirroring
 * the Sleep review rung, so it never nags once read.
 */
function UnviewedBriefCta() {
  return (
    <Link
      to="/brief"
      className="flex items-center gap-3 rounded-2xl border border-border-strong bg-surface-elevated px-4 py-3 shadow-sm transition-colors hover:bg-surface-elevated/80"
      aria-label="Your morning brief is ready — read it"
    >
      <BookOpen className="h-5 w-5 shrink-0 text-primary" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="font-medium text-text-primary">Your morning brief is ready</p>
        <p className="text-sm text-text-secondary">Read it</p>
      </div>
      <ArrowRight className="h-4 w-4 shrink-0 text-text-muted" aria-hidden />
    </Link>
  );
}

async function fetchQuickAddOptions(category: Exclude<DayCategory, 'rest'>) {
  const response = await apiFetch<unknown>(
    `/api/v1/plan-actions/quick-add-options?category=${encodeURIComponent(category)}`,
  );
  return quickAddOptionsEnvelopeSchema.parse(response).data.options;
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
  // Batch 138: the persisted React Query cache + the service worker's NetworkFirst
  // fallback can paint an earlier day's brief on a cold/slow open. Detect that the
  // served brief is for a day other than local-today (derived from the profile
  // timezone, matching the backend, not the browser's UTC date) and let the user
  // force a genuinely fresh, cache-bypassing refetch.
  const isStale =
    isOnline &&
    data != null &&
    data.subjectDate !== localTodayIso(player?.timezone);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const refreshDailyLoop = async () => {
    setIsRefreshing(true);
    try {
      await queryClient.fetchQuery({
        queryKey: ['daily-loop', 'today'],
        queryFn: () => fetchDailyLoop(undefined, { forceFresh: true }),
      });
    } finally {
      setIsRefreshing(false);
    }
  };
  const [quickAddTarget, setQuickAddTarget] = useState<{
    date: string;
    category: Exclude<DayCategory, 'rest'>;
  } | null>(null);
  const quickAddOptionsQuery = useQuery({
    queryKey: ['quick-add-options', quickAddTarget?.category],
    queryFn: () => fetchQuickAddOptions(quickAddTarget!.category),
    enabled: quickAddTarget !== null,
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
  const removeMutation = useMutation({
    mutationFn: ({ workoutId }: { workoutId: string }) =>
      apiFetch(`/api/v1/workout-delivery/planned-workouts/${workoutId}/remove`, { method: 'POST' }),
    onSuccess: async () => {
      await invalidateLoop();
      toast.success('Workout removed');
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : 'Could not remove the workout'),
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
    mutationFn: ({
      date,
      category,
      subtype,
      durationMin,
    }: {
      date: string;
      category: Exclude<DayCategory, 'rest'>;
      subtype: string;
      durationMin: number;
    }) =>
      apiFetch(`/api/v1/plan-actions/days/${date}/workouts`, {
        method: 'POST',
        body: JSON.stringify({ category, subtype, durationMin }),
      }),
    onSuccess: async () => {
      setQuickAddTarget(null);
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
    onSuccess: async (result) => {
      await queryClient.invalidateQueries({ queryKey: ['daily-loop'] });
      // Batch 143: the check-in saved, but a day-time Anthropic outage can leave
      // the read ungenerated (a non-fatal errors[] note). Show an honest retry
      // toast instead of a false "read ready" — the pending card is the retry.
      const readFailure = postWorkoutReadFailure(result);
      if (readFailure) toast.error(readFailure);
      else toast.success('Workout read ready');
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : 'Could not read the workout'),
  });
  const completedRideLogMutation = useMutation({
    mutationFn: async ({
      workoutId,
      activityId,
      subjectiveScore,
      rpe,
      feel,
      notes,
      status,
      completedDurationMin,
      changedType,
      intensity,
      changeSummary,
    }: CompletedRideLogPayload) => {
      if (!data) throw new Error('Daily loop not loaded');
      const ridePayload = postRideCheckInInputSchema.parse({
        subjectiveScore,
        rpe,
        feel,
        notes,
      });
      const adherencePayload = plannedWorkoutAdherenceInputSchema.parse({
        status,
        rpe,
        feel,
        notes,
        actualWorkoutJson: {
          completedDurationMin,
          type: changedType,
          intensity,
          changeSummary,
        },
      });
      // Save adherence first so the check-in-triggered read grades the actual
      // workout Mark logged, not the pre-submit planned state (Batch 87).
      await apiFetch(`/api/v1/daily-loop/${data.subjectDate}/planned-workouts/${workoutId}/adherence`, {
        method: 'PUT',
        body: JSON.stringify(adherencePayload),
      });
      return apiFetch(`/api/v1/daily-loop/${data.subjectDate}/activities/${activityId}/post-ride-check-in`, {
        method: 'PUT',
        body: JSON.stringify(ridePayload),
      });
    },
    onSuccess: async (result) => {
      await queryClient.invalidateQueries({ queryKey: ['daily-loop'] });
      // Batch 143: honest retry toast when the read couldn't generate (the ride
      // log + check-in still saved). See postRideCheckInMutation.
      const readFailure = postWorkoutReadFailure(result);
      if (readFailure) toast.error(readFailure);
      else toast.success('Workout read ready');
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : 'Could not save ride log'),
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
  const holiday = daily.holiday;
  const awayTonight = holiday.awayTonight ?? false;
  const holidayEndDate = holiday.activeWindow?.endDate ?? null;
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
  const pendingPostActivities = daily.pendingPostWorkoutActivities ?? [];
  // Batch 140: the payload now carries one analysis per activity (the backend keeps
  // the latest — see `_post_activity_analyses`). Belt-and-braces on the client too:
  // dedupe to the newest read per activity before splitting into planned/unplanned,
  // so a stray duplicate can never resurface a stale read (the "changed RPE 7→4 but
  // the read still says 7" bug, where the old last-write-wins map picked the oldest
  // of two rows). `postWorkouts` arrives newest-first, so the first row seen for an
  // activity is its newest.
  const seenRideActivityIds = new Set<string>();
  const latestRides = postWorkouts.filter((ride) => {
    if (!ride.activityId) return true;
    if (seenRideActivityIds.has(ride.activityId)) return false;
    seenRideActivityIds.add(ride.activityId);
    return true;
  });
  // Batch 60: a completed ride's read attaches to its Today-card session row
  // (matched by plannedWorkoutId, set when the coach analysed the ride). Only
  // *unplanned* rides — with no planned row to attach to — keep the standalone
  // "After your ride" section, so a planned ride no longer shows in two places.
  const rideByWorkoutId = new Map<string, RideAnalysis>();
  for (const ride of latestRides) {
    if (ride.plannedWorkoutId) rideByWorkoutId.set(ride.plannedWorkoutId, ride);
  }
  const unplannedRides = latestRides.filter((ride) => !ride.plannedWorkoutId);
  const hasRide = unplannedRides.length > 0;
  const todaysWorkouts = daily.plannedWorkouts;
  const dayState = dayStateForWorkouts(todaysWorkouts);
  const actionsBusy =
    approveMutation.isPending ||
    skipMutation.isPending ||
    removeMutation.isPending ||
    swapMutation.isPending ||
    addWorkoutMutation.isPending ||
    skipDayMutation.isPending ||
    actualMutation.isPending;
  const todayActions = {
    busy: actionsBusy,
    onApprove: (payload: { workoutId: string }) => approveMutation.mutate(payload),
    onSkip: (payload: { workoutId: string }) => skipMutation.mutate(payload),
    onRemove: (payload: { workoutId: string }) => removeMutation.mutate(payload),
    onSwap: (payload: { workoutId: string; targetDate: string }) => swapMutation.mutate(payload),
  };
  const dayActions = {
    busy: actionsBusy,
    onAddWorkout: (category: Exclude<DayCategory, 'rest'>) =>
      setQuickAddTarget({ date: daily.subjectDate, category }),
    onSkipDay: () => skipDayMutation.mutate({ date: daily.subjectDate }),
    onRecordActual: (payload: { label: string; notes: string | null }) =>
      actualMutation.mutate({ date: daily.subjectDate, ...payload }),
  };
  // Batch 69: planned rides now use the combined completed-ride logger on their
  // Today row; the standalone ride check-in mutation remains for unplanned rides.
  const completedRideLog: CompletedRideLogHandlers = {
    onSave: (payload) => completedRideLogMutation.mutate(payload),
    savingWorkoutId: completedRideLogMutation.variables?.workoutId ?? null,
    isSaving: completedRideLogMutation.isPending,
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
    hasSeenWalkRead: hasSeenWalkRead(daily.subjectDate),
  });
  // Batch 95: before today's brief exists, don't auto-expand last night's raw
  // sleep — `rest_day`'s phase primary would otherwise pre-empt the coached
  // read with the un-narrated snapshot before he's even checked in. Fall back
  // to `today` (already the pre_training default) until the brief lands.
  const primary =
    actionSection(action) ??
    (analysis == null && phase === 'rest_day' ? 'today' : primarySection(phase, { hasRide }));
  // Batch 37: render the full section set every load; exactly one is expanded
  // (the action/phase primary). Presence is only ever gated by hasRide.
  const order = orderedSections(phase, { hasRide, isEvening, primary });
  // Batch 103: before today's brief exists, Home should show one clear
  // "Say good morning" and keep the raw last-night sleep snapshot hidden.
  const visibleOrder = analysis == null ? order.filter((key) => key !== 'lastNight') : order;
  // Batch 54: the lead section stays prominent; the rest recede under "More detail".
  const { lead, detail } = splitPrimaryDetail(visibleOrder, primary);
  const hasUnreadBriefCta = Boolean(analysis && !hasReviewedBrief(daily.subjectDate));
  const hasVisibleTodayActions = Boolean(
    analysis && visibleTodayActions(analysis.todayActions, todaysWorkouts).length > 0,
  );
  const stripTargetSection: HomeSectionKey | null =
    action.sectionKey ??
    (action.key === 'review-sleep'
      ? 'lastNight'
      : action.key === 'protect-sleep'
        ? 'tonight'
        : null);
  const showNextActionStrip =
    Boolean(analysis) &&
    !hasUnreadBriefCta &&
    !hasVisibleTodayActions &&
    action.key !== 'all-set' &&
    stripTargetSection !== lead;
  const scrollToSection = (key: HomeSectionKey) => {
    document
      .getElementById(sectionDomId(key))
      ?.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
  };

  const todaySummaryValue = todaySummary(todaysWorkouts);
  const afterRideSummaryValue = afterRideSummary(unplannedRides);

  const sections: Record<
    HomeSectionKey,
    { title: string; icon: ReactNode; summary: ReactNode; tone?: SummaryTone; body: ReactNode }
  > = {
    lastNight: {
      title: "Last night's sleep",
      icon: <BedDouble className="h-4 w-4 text-primary" aria-hidden />,
      summary: sleepSummary(sleep),
      body: (
        <div className="space-y-4">
          <SleepSnapshotBody
            metricsVsBaselines={metricsVsBaselines}
            ageComparison={ageComparison}
            chronicSuggestions={chronicSuggestions}
            morningBriefLink="/brief"
            holiday={{ isActive: holiday.isActive, endDate: holidayEndDate }}
          />
          {analysis?.id ? (
            <div className="rounded-xl border border-dashed border-border bg-bg/60 px-4 py-3">
              <FeedbackControl
                analysisId={analysis.id}
                kind={(analysis.planAdjustments?.length ?? 0) > 0 ? 'suggestion' : 'summary'}
              />
            </div>
          ) : null}
        </div>
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
          swapSuggestion={analysis?.swapSuggestion ?? null}
          weeklyMix={analysis?.weeklyMix ?? null}
          flexibilityAnalyses={postFlexibilityAnalyses}
          strengthAnalyses={postStrengthAnalyses}
          walkAnalyses={postWalkAnalyses}
          subjectDate={daily.subjectDate}
          workoutActions={todayActions}
          dayActions={dayActions}
          completedRides={rideByWorkoutId}
          completedRideLog={completedRideLog}
          pendingPostActivities={pendingPostActivities}
          checkInHandlers={{
            onSave: (payload) => postRideCheckInMutation.mutate(payload),
            savingActivityId: postRideCheckInMutation.variables?.activityId ?? null,
            isSaving: postRideCheckInMutation.isPending,
          }}
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
          items={unplannedRides}
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
      summary: awayTonight
        ? holidayDormantSummary(holidayEndDate)
        : daily.sleepProjection?.headline ?? SLEEP_PREP_SUMMARY,
      // Batch 50: Home's evening cards stay compact and defer to the Sleep hub
      // (Batch 49) rather than duplicating the full wind-down controls.
      body: awayTonight ? (
        <HolidayDormantBody kind="sleep" endDate={holidayEndDate} />
      ) : (
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
      summary: awayTonight ? holidayDormantSummary(holidayEndDate) : bedroomLiveSummary(thermal),
      body: awayTonight ? (
        <HolidayDormantBody kind="bedroom" endDate={holidayEndDate} />
      ) : (
        <BedroomBody thermal={thermal} />
      ),
    },
  };

  return (
    <div className="space-y-5">
      {!isOnline && (
        <OfflineNotice
          description={`You're offline — showing your last saved brief for ${friendlyDate(daily.subjectDate)}.`}
        />
      )}

      {isStale && (
        <StaleDataNotice
          description={`Showing ${friendlyDate(daily.subjectDate)}'s brief — refresh for today's.`}
          onRefresh={refreshDailyLoop}
          isRefreshing={isRefreshing}
        />
      )}

      {/* Batch 54: a compact greeting lockup (was the full PageHeader h1) so the
          verdict sits higher on cold load.
          Batch 110: dropped the date here — VerdictHero/GoodMorningCta right below
          already carry it, so it was showing twice.
          Batch 115: once a verdict exists, the greeting/verdict restate folds into
          VerdictHero's own line instead of a separate paragraph above it — the two
          were saying "good to go" twice. Pre-verdict, the CTAs below carry no
          greeting of their own, so the plain greeting line stays here. */}
      {!analysis && <p className="text-sm font-medium text-text-secondary">{greeting}</p>}

      {/* Batch 85: the verdict no longer lands on its own — until today's brief is
          generated (his check-in, or the 09:30 backstop), Home invites him to say
          good morning rather than showing an auto-pending verdict.
          Batch 114: once he's checked in (Batch 97's background generation is the
          usual path there), the invite is stale — swap it for a "writing your
          brief" state instead of still asking him to say good morning. */}
      {analysis ? (
        <VerdictHero
          verdict={analysis.verdict}
          dateLabel={friendlyDate(daily.subjectDate)}
          line={personalStatusLine(
            analysis.verdict,
            player?.displayName,
            undefined,
            dayState.isRest || holiday.isActive,
          )}
          recap={morningFeelRecap(daily.manualEntry ?? null)}
        />
      ) : daily.briefGeneration?.status === 'failed' ? (
        // Batch 141: a failed generation is a retryable error here too, not an
        // endless "Writing your brief" — outranks the generating state (a failure
        // always has a check-in behind it).
        <BriefFailedCta dateLabel={friendlyDate(daily.subjectDate)} />
      ) : daily.manualEntry != null ? (
        <BriefGeneratingCta dateLabel={friendlyDate(daily.subjectDate)} />
      ) : (
        <GoodMorningCta dateLabel={friendlyDate(daily.subjectDate)} />
      )}

      {/* Batch 96: an unviewed brief outranks every action card, including the
          thermal/plan nudges inside TodayActions. */}
      {hasUnreadBriefCta ? <UnviewedBriefCta /> : null}

      {/* Batch 86: the day's actions lead — workout adjustment first-class and
          tappable-to-approve, plus swap/sleep/thermal — above the reasoning the
          Today/Sleep cards still carry below. Renders nothing until a brief exists
          or when nothing is actionable. */}
      {analysis && !hasUnreadBriefCta ? (
        <TodayActions actions={analysis.todayActions} workouts={todaysWorkouts} />
      ) : null}

      {/* Batch 115: on a rest/holiday day the Today card already says "Rest is the
          plan today" (or is dormant on holiday) — an all-clear Next strip right
          above it repeats that same "nothing to do" read a second time. Only
          suppress the quiet all-set state; an active Next action still surfaces
          regardless of the day type. */}
      {showNextActionStrip ? (
        <NextActionStrip action={action} onGoToSection={scrollToSection} />
      ) : null}

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
          <p className="font-mono text-xs uppercase tracking-[0.25em] text-text-muted md:col-span-2">
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

      <QuickAddSheet
        open={quickAddTarget !== null}
        category={quickAddTarget?.category ?? null}
        options={quickAddOptionsQuery.data ?? []}
        loading={quickAddOptionsQuery.isLoading}
        busy={addWorkoutMutation.isPending}
        onClose={() => setQuickAddTarget(null)}
        onConfirm={(subtype, durationMin) => {
          if (!quickAddTarget) return;
          addWorkoutMutation.mutate({
            date: quickAddTarget.date,
            category: quickAddTarget.category,
            subtype,
            durationMin,
          });
        }}
      />
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
        <p className={cn('font-mono text-xs uppercase tracking-[0.25em]', isWarning ? 'text-warning' : 'text-accent')}>
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
type SwapSuggestionData = NonNullable<DailyLoopData['morningAnalysis']>['swapSuggestion'];
type WeeklyMixData = NonNullable<DailyLoopData['morningAnalysis']>['weeklyMix'];

type TodayWorkoutActions = {
  busy: boolean;
  onApprove: (payload: { workoutId: string }) => void;
  onSkip: (payload: { workoutId: string }) => void;
  onRemove: (payload: { workoutId: string }) => void;
  onSwap: (payload: { workoutId: string; targetDate: string }) => void;
};

type RideAnalysis = DailyLoopData['postWorkoutAnalyses'][number];

type RideCheckInPayload = {
  activityId: string;
  subjectiveScore: number | null;
  rpe: number | null;
  feel: string | null;
  notes: string | null;
};

type RideCheckInHandlers = {
  onSave: (payload: RideCheckInPayload) => void;
  savingActivityId: string | null;
  isSaving: boolean;
};

type CompletedRideLogPayload = RideCheckInPayload & {
  workoutId: string;
  status: 'completed' | 'modified' | 'skipped';
  completedDurationMin: number | null;
  changedType: string | null;
  intensity: string | null;
  changeSummary: string | null;
};

type CompletedRideLogHandlers = {
  onSave: (payload: CompletedRideLogPayload) => void;
  savingWorkoutId: string | null;
  isSaving: boolean;
};

/** Batch 66 (#139): the swap-first recovery lead — on a cautious morning with a
 *  hard session scheduled, recommend rearranging the week (move the hard session,
 *  pull an easier one forward) in one tap instead of only offering to soften.
 *  The tap reuses the day card's category-scoped swap (Batch 65-safe on split
 *  days); softening the ride stays available on the session row below. */
function SwapSuggestionCard({
  suggestion,
  busy,
  onSwap,
}: {
  suggestion: NonNullable<SwapSuggestionData>;
  busy: boolean;
  onSwap: (payload: { workoutId: string; targetDate: string }) => void;
}) {
  return (
    <div className="rounded-xl border border-warning/30 bg-warning/10 px-3 py-3 text-sm">
      <p className="mb-1 flex items-center gap-1.5 font-medium text-warning">
        <ArrowLeftRight className="h-4 w-4" aria-hidden />
        Rearrange the week
      </p>
      <p className="text-text-primary">
        Today isn&apos;t the day to force {suggestion.hardTitle}. Move it to{' '}
        {suggestion.moveToWeekday} and bring {suggestion.bringForwardTitle} forward to today
        — keeping the week&apos;s volume instead of softening the ride.
      </p>
      <Button
        type="button"
        size="sm"
        className="mt-3"
        disabled={busy}
        onClick={() =>
          onSwap({ workoutId: suggestion.hardWorkoutId, targetDate: suggestion.moveToDate })
        }
      >
        <ArrowLeftRight className="h-4 w-4" aria-hidden />
        Move it to {suggestion.moveToWeekday}
      </Button>
    </div>
  );
}

/** The expanded body of the Today section: the day's session rows plus the
 *  day-level footer. The day label + verdict badge live in the section header
 *  (Batch 36 unified card, Batch 37 collapse). */
function DayPlanBody({
  workouts,
  planAdjustments,
  swapSuggestion,
  weeklyMix,
  flexibilityAnalyses,
  strengthAnalyses,
  walkAnalyses,
  subjectDate,
  workoutActions,
  dayActions,
  completedRides,
  completedRideLog,
  pendingPostActivities,
  checkInHandlers,
}: {
  workouts: TodayWorkout[];
  planAdjustments: string[];
  swapSuggestion: SwapSuggestionData;
  weeklyMix: WeeklyMixData;
  flexibilityAnalyses: DailyLoopData['postFlexibilityAnalyses'];
  strengthAnalyses: DailyLoopData['postStrengthAnalyses'];
  walkAnalyses: DailyLoopData['postWalkAnalyses'];
  subjectDate: string;
  workoutActions: TodayWorkoutActions;
  dayActions: {
    busy: boolean;
    onAddWorkout: (category: Exclude<DayCategory, 'rest'>) => void;
    onSkipDay: () => void;
    onRecordActual: (payload: { label: string; notes: string | null }) => void;
  };
  completedRides: Map<string, RideAnalysis>;
  completedRideLog: CompletedRideLogHandlers;
  pendingPostActivities: PendingPostActivity[];
  checkInHandlers: RideCheckInHandlers;
}) {
  const hasWorkouts = workouts.length > 0;
  // Batch 132: the empty-plan copy assumed a rest day meant nothing happened —
  // wrong on a day he walked, lifted, or stretched. Any logged/pending activity
  // (not just a walk) earns the acknowledging copy instead of the ride-centric one.
  const hasLoggedActivity =
    flexibilityAnalyses.length > 0 ||
    strengthAnalyses.length > 0 ||
    walkAnalyses.length > 0 ||
    pendingPostActivities.length > 0;
  const pendingByWorkoutId = new Map(
    pendingPostActivities
      .filter((activity) => activity.plannedWorkoutId)
      .map((activity) => [activity.plannedWorkoutId!, activity]),
  );
  const standalonePending = pendingPostActivities.filter((activity) => !activity.plannedWorkoutId);
  return (
    <div className="space-y-4">
      {swapSuggestion ? (
        <SwapSuggestionCard
          suggestion={swapSuggestion}
          busy={workoutActions.busy}
          onSwap={workoutActions.onSwap}
        />
      ) : null}
      {weeklyMix ? <WeeklyMixCard mix={weeklyMix} /> : null}
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
                analysis={completedRides.get(workout.id)}
                completedRideLog={completedRideLog}
                pendingActivity={pendingByWorkoutId.get(workout.id)}
                checkInHandlers={checkInHandlers}
                {...workoutActions}
              />
            </div>
          ))}
        </div>
      ) : hasLoggedActivity ? (
        <p className="rounded-xl border border-dashed border-border px-4 py-4 text-sm text-text-secondary">
          Rest is still the plan today — I've got what you logged below.
        </p>
      ) : (
        <p className="rounded-xl border border-dashed border-border px-4 py-4 text-sm text-text-secondary">
          Rest is the plan today. Add something light, swap a workout in from the week, or just record what happened.
          Doing something different? Just ride it — I'll read it after.
        </p>
      )}

      {standalonePending.length > 0 ? (
        <PendingWorkoutCheckIns items={standalonePending} handlers={checkInHandlers} />
      ) : null}

      {flexibilityAnalyses.length > 0 ? <FlexibilityReadList items={flexibilityAnalyses} /> : null}
      {strengthAnalyses.length > 0 ? <StrengthReadList items={strengthAnalyses} /> : null}
      {walkAnalyses.length > 0 ? <WalkReadList items={walkAnalyses} subjectDate={subjectDate} /> : null}

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
            <FeedbackControl analysisId={item.id} kind="summary" feedback={item.feedback ?? null} />
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
            <FeedbackControl analysisId={item.id} kind="summary" feedback={item.feedback ?? null} />
          </div>
        ))}
      </div>
    </div>
  );
}

function WalkReadList({
  items,
  subjectDate,
}: {
  items: DailyLoopData['postWalkAnalyses'];
  subjectDate: string;
}) {
  // Batch 132: rendering the read (only mounted while the Today section is
  // open — CollapsibleSection unmounts its body while closed) is Home's "seen"
  // signal for the walk rung, mirroring `markBriefReviewed`'s mount-time mark.
  useEffect(() => {
    markWalkReadSeen(subjectDate);
  }, [subjectDate]);
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
            <FeedbackControl analysisId={item.id} kind="summary" feedback={item.feedback ?? null} />
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
  isRemovable,
  panel,
  busy,
  onApprove,
  onIgnore,
  onTogglePanel,
}: {
  hasPendingChange: boolean;
  isBike: boolean;
  isRemovable: boolean;
  panel: 'none' | 'edit' | 'swap' | 'skip' | 'remove';
  busy: boolean;
  onApprove: () => void;
  onIgnore: () => void;
  onTogglePanel: (next: 'edit' | 'swap' | 'skip' | 'remove') => void;
}) {
  const primaryAction: WorkoutRowButton = hasPendingChange
    ? { label: 'Approve & upload', icon: Check, onClick: onApprove }
    : isBike
      ? { label: 'Edit', icon: Pencil, onClick: () => onTogglePanel('edit'), ariaExpanded: panel === 'edit' }
      : { label: 'Swap day', icon: ArrowLeftRight, onClick: () => onTogglePanel('swap'), ariaExpanded: panel === 'swap' };

  const secondaryAction: WorkoutRowButton = hasPendingChange
    ? { label: 'Ignore', icon: X, onClick: onIgnore }
    : isRemovable
      ? { label: 'Remove', icon: Trash2, onClick: () => onTogglePanel('remove'), ariaExpanded: panel === 'remove' }
    : isBike
      ? { label: 'Swap day', icon: ArrowLeftRight, onClick: () => onTogglePanel('swap'), ariaExpanded: panel === 'swap' }
      : { label: 'Skip', icon: Trash2, onClick: () => onTogglePanel('skip'), ariaExpanded: panel === 'skip' };

  const overflowActions: WorkoutRowButton[] = hasPendingChange
    ? [
        { label: 'Manual edit', icon: Pencil, onClick: () => onTogglePanel('edit') },
        { label: 'Swap day', icon: ArrowLeftRight, onClick: () => onTogglePanel('swap') },
        { label: 'Skip', icon: Trash2, onClick: () => onTogglePanel('skip') },
      ]
    : isRemovable
      ? [{ label: 'Swap day', icon: ArrowLeftRight, onClick: () => onTogglePanel('swap') }]
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
  analysis,
  completedRideLog,
  pendingActivity,
  checkInHandlers,
  busy,
  onApprove,
  onSkip,
  onRemove,
  onSwap,
}: {
  workout: TodayWorkout;
  planAdjustments?: string[];
  subjectDate: string;
  analysis?: RideAnalysis;
  completedRideLog: CompletedRideLogHandlers;
  pendingActivity?: PendingPostActivity;
  checkInHandlers: RideCheckInHandlers;
} & TodayWorkoutActions) {
  const [panel, setPanel] = useState<'none' | 'edit' | 'swap' | 'skip' | 'remove'>('none');
  const [ignored, setIgnored] = useState(false);

  const Icon = workoutIcon(workout.workoutType);
  const isBike = isBikeWorkout(workout.workoutType);
  const isRemovable = workout.source === 'plan_action_add';
  const delivery = workout.delivery ?? null;
  const inZwift = Boolean(delivery?.intervalsEventId);
  // The two-state split: a coach adjustment is waiting (bike only), unless Mark
  // has dismissed it for this view (Ignore is a pure front-end dismiss — #99).
  const hasPendingChange = Boolean(delivery?.changed) && isBike && !ignored;
  const togglePanel = (next: 'edit' | 'swap' | 'skip' | 'remove') =>
    setPanel((current) => (current === next ? 'none' : next));

  if (pendingActivity) {
    return (
      <div id={`post-workout-${pendingActivity.activityId}`} className="space-y-3">
        <div className="rounded-xl border border-warning/30 bg-warning/10 px-3 py-3">
          <div className="flex items-center gap-3">
            <Icon className="h-5 w-5 shrink-0 text-primary" aria-hidden />
            <div className="min-w-0 flex-1">
              <p className="font-medium text-text-primary">{workout.title}</p>
              <p className="text-sm text-text-secondary">
                Synced from Garmin · {pendingActivity.durationMin ? `${pendingActivity.durationMin} min` : 'finished'}
              </p>
            </div>
            <Badge variant="warning">Check in</Badge>
          </div>
        </div>
        {pendingActivity.activityKind === 'ride' ? (
          <CompletedRideLogForm
            workoutId={workout.id}
            activityId={pendingActivity.activityId}
            checkIn={pendingActivity.checkIn ?? null}
            adherence={workout.adherence ?? null}
            handlers={completedRideLog}
          />
        ) : (
          <ActivityCheckIn
            activity={pendingActivity}
            handlers={checkInHandlers}
          />
        )}
      </div>
    );
  }

  // Batch 60: once the session is done its row shows the read, not the
  // approve/upload/edit/swap/skip controls — and it can no longer be moved. The
  // ride's coach read + check-in attach here (matched by plannedWorkoutId).
  if (workout.status === 'completed') {
    return (
      <>
        <div className="rounded-xl border border-border bg-bg px-3 py-3">
          <div className="flex items-center gap-3">
            <Icon className="h-5 w-5 shrink-0 text-primary" aria-hidden />
            <div className="min-w-0 flex-1">
              <p className="font-medium text-text-primary">{workout.title}</p>
              <p className="text-sm text-text-secondary">
                {workoutTypeLabel(workout.workoutType)}
                {workout.plannedDurationMin ? ` · ${workout.plannedDurationMin} min` : ''}
                {workout.intensityTarget ? ` · ${workout.intensityTarget}` : ''}
              </p>
            </div>
            <Badge variant="success" className="shrink-0">
              <Check className="mr-1 h-3.5 w-3.5" aria-hidden />
              Completed
            </Badge>
          </div>
        </div>
        {analysis ? (
          <CompletedRideRead
            analysis={analysis}
            workout={workout}
            completedRideLog={completedRideLog}
          />
        ) : null}
      </>
    );
  }

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
                {workoutTypeLabel(workout.workoutType)}
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
          isRemovable={isRemovable}
          panel={panel}
          busy={busy}
          onApprove={() => onApprove({ workoutId: workout.id })}
          onIgnore={() => setIgnored(true)}
          onTogglePanel={togglePanel}
        />
        {panel === 'edit' ? (
          <IntervalWorkoutEditor
            workoutId={workout.id}
            onApproved={() => setPanel('none')}
          />
        ) : null}

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

        {panel === 'remove' && (
          <div className="rounded-lg border border-error/30 bg-error/10 px-3 py-3">
            <p className="text-sm text-text-primary">
              Remove this added workout?{' '}
              {isBike && inZwift ? 'It will be removed from Zwift.' : 'It will disappear from your plan.'}
            </p>
            <div className="mt-2 flex gap-2">
              <Button
                type="button"
                size="sm"
                variant="destructive"
                disabled={busy}
                onClick={() => onRemove({ workoutId: workout.id })}
              >
                {busy ? 'Removing…' : 'Confirm remove'}
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

type RideCheckInValue = {
  subjectiveScore?: number | null;
  rpe?: number | null;
  feel?: string | null;
  notes?: string | null;
} | null;
type PendingPostActivity = NonNullable<DailyLoopData['pendingPostWorkoutActivities']>[number];

type PlannedRideAdherenceValue = TodayWorkout['adherence'] | null;
type PostRideFormValue = {
  subjectiveScore: string;
  rpe: string;
  feel: string;
  notes: string;
  status?: 'completed' | 'modified' | 'skipped';
  completedDurationMin?: string;
  changedType?: string;
  intensity?: string;
  changeSummary?: string;
};

/** One ride's "how did it feel" check-in, owning its own draft so it can drop
 *  into both a completed Today-card row and the unplanned-ride section without a
 *  shared drafts map. */
function RideCheckIn({
  activityId,
  checkIn,
  handlers,
}: {
  activityId: string;
  checkIn: RideCheckInValue;
  handlers: RideCheckInHandlers;
}) {
  const [value, setValue] = useState({
    subjectiveScore: checkIn?.subjectiveScore != null ? String(checkIn.subjectiveScore) : '',
    rpe: checkIn?.rpe != null ? String(checkIn.rpe) : '',
    feel: checkIn?.feel ?? '',
    notes: checkIn?.notes ?? '',
  });
  return (
    <PostRideCheckInForm
      activityId={activityId}
      value={value}
      logged={Boolean(checkIn)}
      onChange={(patch) => setValue((current) => ({ ...current, ...patch }))}
      onSave={(next) =>
        handlers.onSave({
          activityId,
          subjectiveScore: next.subjectiveScore === '' ? null : Number(next.subjectiveScore),
          rpe: next.rpe ? Number(next.rpe) : null,
          feel: next.feel || null,
          notes: next.notes || null,
        })
      }
      isSaving={handlers.isSaving && handlers.savingActivityId === activityId}
    />
  );
}

/** The completed-ride read attached to its Today-card session row (Batch 60):
 *  the one-line tomorrow-impact and the check-in stay compact; the full coach
 *  read + interval table sit behind a "View analysis" disclosure. */
function CompletedRideRead({
  analysis,
  workout,
  completedRideLog,
}: {
  analysis: RideAnalysis;
  workout: TodayWorkout;
  completedRideLog: CompletedRideLogHandlers;
}) {
  const [showRead, setShowRead] = useState(false);
  return (
    <div className="space-y-3">
      {analysis.tomorrowImpact ? (
        <p className="text-sm text-text-secondary">
          <span className="font-medium text-text-primary">Tomorrow:</span> {analysis.tomorrowImpact}
        </p>
      ) : null}
      {analysis.activityId ? (
        <CompletedRideLogForm
          workoutId={workout.id}
          activityId={analysis.activityId}
          checkIn={analysis.postRideCheckIn ?? null}
          adherence={workout.adherence ?? null}
          handlers={completedRideLog}
        />
      ) : null}
      <div>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          onClick={() => setShowRead((current) => !current)}
          aria-expanded={showRead}
        >
          <ChevronDown className={cn('h-4 w-4 transition-transform', showRead && 'rotate-180')} aria-hidden />
          {showRead ? 'Hide analysis' : 'View analysis'}
        </Button>
        {showRead ? (
          <div className="mt-3 space-y-4">
            <Markdown>{analysis.outputMarkdown}</Markdown>
            <RideIntervalTable intervals={analysis.intervals ?? []} />
            <FeedbackControl analysisId={analysis.id} kind="summary" feedback={analysis.feedback ?? null} />
          </div>
        ) : null}
      </div>
    </div>
  );
}

function CompletedRideLogForm({
  workoutId,
  activityId,
  checkIn,
  adherence,
  handlers,
}: {
  workoutId: string;
  activityId: string;
  checkIn: RideCheckInValue;
  adherence: PlannedRideAdherenceValue;
  handlers: CompletedRideLogHandlers;
}) {
  const [value, setValue] = useState({
    subjectiveScore: checkIn?.subjectiveScore != null ? String(checkIn.subjectiveScore) : '',
    rpe:
      checkIn?.rpe != null
        ? String(checkIn.rpe)
        : adherence?.rpe != null
          ? String(adherence.rpe)
          : '',
    feel: checkIn?.feel ?? adherence?.feel ?? '',
    notes: checkIn?.notes ?? adherence?.notes ?? '',
    status: (adherence?.adherenceStatus as 'completed' | 'modified' | 'skipped' | null) ?? 'completed',
    completedDurationMin:
      typeof adherence?.actualWorkoutJson?.completedDurationMin === 'number'
        ? String(adherence.actualWorkoutJson.completedDurationMin)
        : '',
    changedType:
      typeof adherence?.actualWorkoutJson?.type === 'string' ? adherence.actualWorkoutJson.type : '',
    intensity:
      typeof adherence?.actualWorkoutJson?.intensity === 'string'
        ? adherence.actualWorkoutJson.intensity
        : '',
    changeSummary:
      typeof adherence?.actualWorkoutJson?.changeSummary === 'string'
        ? adherence.actualWorkoutJson.changeSummary
        : '',
  });

  return (
    <PostRideCheckInForm
      activityId={activityId}
      value={value}
      logged={Boolean(checkIn) || Boolean(adherence)}
      onChange={(patch) => setValue((current) => ({ ...current, ...patch }))}
      onSave={(next) =>
        handlers.onSave({
          workoutId,
          activityId,
          subjectiveScore: next.subjectiveScore === '' ? null : Number(next.subjectiveScore),
          rpe: next.rpe ? Number(next.rpe) : null,
          feel: next.feel || null,
          notes: next.notes || null,
          status: next.status ?? 'completed',
          completedDurationMin: next.completedDurationMin ? Number(next.completedDurationMin) : null,
          changedType: next.changedType || null,
          intensity: next.intensity || null,
          changeSummary: next.changeSummary || null,
        })
      }
      isSaving={handlers.isSaving && handlers.savingWorkoutId === workoutId}
      saveLabel="Read my workout"
      includeAdherence
    />
  );
}

function ActivityCheckIn({
  activity,
  handlers,
}: {
  activity: PendingPostActivity;
  handlers: RideCheckInHandlers;
}) {
  const [value, setValue] = useState<PostRideFormValue>({
    subjectiveScore: '',
    rpe: activity.checkIn?.rpe != null ? String(activity.checkIn.rpe) : '',
    feel: activity.checkIn?.feel ?? '',
    notes: activity.checkIn?.notes ?? '',
  });
  return (
    <PostRideCheckInForm
      activityId={activity.activityId}
      value={value}
      logged={Boolean(activity.checkIn)}
      onChange={(patch) => setValue((current) => ({ ...current, ...patch }))}
      onSave={(next) =>
        handlers.onSave({
          activityId: activity.activityId,
          subjectiveScore: null,
          rpe: next.rpe ? Number(next.rpe) : null,
          feel: next.feel || null,
          notes: next.notes || null,
        })
      }
      isSaving={handlers.isSaving && handlers.savingActivityId === activity.activityId}
      includeSubjectiveScore={false}
      saveLabel="Read my workout"
    />
  );
}

function PendingWorkoutCheckIns({
  items,
  handlers,
}: {
  items: PendingPostActivity[];
  handlers: RideCheckInHandlers;
}) {
  return (
    <div className="space-y-4">
      {items.map((activity) => (
        <div
          id={`post-workout-${activity.activityId}`}
          key={activity.activityId}
          className="space-y-3 rounded-xl border border-warning/30 bg-warning/10 px-3 py-3"
        >
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="font-semibold text-text-primary">{activity.activityName}</p>
              <p className="text-sm text-text-secondary">
                Synced from Garmin{activity.durationMin ? ` · ${activity.durationMin} min` : ''}
              </p>
            </div>
            <Badge variant="warning">Check in</Badge>
          </div>
          {activity.activityKind === 'ride' ? (
            <RideCheckIn
              activityId={activity.activityId}
              checkIn={activity.checkIn ?? null}
              handlers={handlers}
            />
          ) : (
            <ActivityCheckIn activity={activity} handlers={handlers} />
          )}
        </div>
      ))}
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
    postRideCheckIn?: RideCheckInValue;
    feedback?: RideAnalysis['feedback'];
  }>;
  onSaveCheckIn: (payload: RideCheckInPayload) => void;
  savingActivityId: string | null;
  isSaving: boolean;
}) {
  const handlers: RideCheckInHandlers = { onSave: onSaveCheckIn, savingActivityId, isSaving };
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
            <RideCheckIn activityId={item.activityId} checkIn={item.postRideCheckIn ?? null} handlers={handlers} />
          ) : null}
          <div>
            <Markdown>{item.outputMarkdown}</Markdown>
          </div>
          <RideIntervalTable intervals={item.intervals ?? []} />
          <FeedbackControl analysisId={item.id} kind="summary" feedback={item.feedback ?? null} />
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
  saveLabel = 'Read my workout',
  includeAdherence = false,
  includeSubjectiveScore = true,
}: {
  activityId: string;
  value: PostRideFormValue;
  logged: boolean;
  onChange: (patch: Partial<PostRideFormValue>) => void;
  onSave: (value: PostRideFormValue) => void;
  isSaving: boolean;
  saveLabel?: string;
  includeAdherence?: boolean;
  includeSubjectiveScore?: boolean;
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
        {includeSubjectiveScore ? (
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
        ) : null}
        <div className="space-y-1.5 sm:col-span-2">
          <Label htmlFor={`post-ride-feel-${activityId}`}>Feel</Label>
          <Input
            id={`post-ride-feel-${activityId}`}
            value={value.feel}
            onChange={(event) => onChange({ feel: event.target.value })}
          />
        </div>
        <div className="space-y-1.5 sm:col-span-2">
          <Label htmlFor={`post-ride-notes-${activityId}`}>Notes or a question</Label>
          <Textarea
            id={`post-ride-notes-${activityId}`}
            value={value.notes}
            onChange={(event) => onChange({ notes: event.target.value })}
          />
        </div>
        {includeAdherence ? (
          <>
            <div className="space-y-1.5">
              <Label>Outcome</Label>
              <div className="flex flex-wrap gap-2" role="group" aria-label="Outcome">
                {[
                  ['completed', 'Did it as planned'],
                  ['modified', 'Changed it'],
                  ['skipped', 'Skipped it'],
                ].map(([status, label]) => {
                  const selected = (value.status ?? 'completed') === status;
                  return (
                    <Button
                      key={status}
                      type="button"
                      size="sm"
                      variant={selected ? 'default' : 'outline'}
                      aria-pressed={selected}
                      onClick={() =>
                        onChange({ status: status as 'completed' | 'modified' | 'skipped' })
                      }
                    >
                      {label}
                    </Button>
                  );
                })}
              </div>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor={`post-ride-duration-${activityId}`}>Actual minutes</Label>
              <Input
                id={`post-ride-duration-${activityId}`}
                inputMode="numeric"
                value={value.completedDurationMin ?? ''}
                onChange={(event) => onChange({ completedDurationMin: event.target.value })}
              />
            </div>
            {value.status === 'modified' ? (
              <>
                <div className="space-y-1.5">
                  <Label htmlFor={`post-ride-type-${activityId}`}>What did you do instead?</Label>
                  <Input
                    id={`post-ride-type-${activityId}`}
                    placeholder="e.g. Recovery substitution"
                    value={value.changedType ?? ''}
                    onChange={(event) => onChange({ changedType: event.target.value })}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor={`post-ride-intensity-${activityId}`}>Target / intensity</Label>
                  <Input
                    id={`post-ride-intensity-${activityId}`}
                    placeholder="e.g. Capped at 60% FTP"
                    value={value.intensity ?? ''}
                    onChange={(event) => onChange({ intensity: event.target.value })}
                  />
                </div>
                <div className="space-y-1.5 sm:col-span-2">
                  <Label htmlFor={`post-ride-change-summary-${activityId}`}>What changed?</Label>
                  <Textarea
                    id={`post-ride-change-summary-${activityId}`}
                    value={value.changeSummary ?? ''}
                    onChange={(event) => onChange({ changeSummary: event.target.value })}
                  />
                </div>
              </>
            ) : null}
          </>
        ) : null}
      </div>
      <div className="mt-3 flex justify-end">
        <Button type="button" variant="outline" onClick={() => onSave(value)} disabled={isSaving}>
          {isSaving ? 'Reading your workout…' : saveLabel}
        </Button>
      </div>
    </div>
  );
}

function TomorrowBody({ text }: { text: string }) {
  return <p className="text-sm leading-6 text-text-primary">{text}</p>;
}
