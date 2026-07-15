import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import {
  freeformBikeWorkoutInputSchema,
  planScheduleEnvelopeSchema,
  quickAddOptionsEnvelopeSchema,
  restructureEnvelopeSchema,
  workoutActionResponseSchema,
} from '@coach/shared';
import {
  Bike,
  CalendarDays,
  CheckCircle2,
  Dumbbell,
  Hammer,
  Moon,
  Plus,
  ShieldCheck,
  Shuffle,
  RotateCcw,
  SlidersHorizontal,
  Trash2,
  Umbrella,
  Wind,
} from 'lucide-react';
import { toast } from 'sonner';
import { MoveWorkoutSheet } from '@/components/MoveWorkoutSheet';
import { QuickAddSheet } from '@/components/QuickAddSheet';
import { StructuredWorkoutSheet } from '@/components/StructuredWorkoutSheet';
import { Tabs } from '@/components/ui/tabs';
import { WeekRestructureSheet } from '@/components/WeekRestructureSheet';
import { PageHeader } from '@/components/PageHeader';
import { WeeklyMixCard } from '@/components/WeeklyMixCard';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { EmptyState, ErrorState } from '@/components/EmptyState';
import { Skeleton } from '@/components/ui/skeleton';
import { useAuth } from '@/contexts/AuthContext';
import { apiFetch } from '@/lib/api';
import { cn } from '@/lib/utils';
import { useDailyLoop } from '@/hooks/useDailyLoop';
import { categoryForWorkoutType, type DayCategory } from '@/lib/workoutCategories';

type PlanScheduleEnvelope = typeof planScheduleEnvelopeSchema._type;
type PlanDay = PlanScheduleEnvelope['data']['schedule'][number];
type PlanWorkout = PlanDay['workouts'][number];
type FreeformBikeWorkoutInput = typeof freeformBikeWorkoutInputSchema._type;
type WorkoutActionResponse = typeof workoutActionResponseSchema._type;

// Batch 88: a successful free-form save can carry non-blocking advisories (power out
// of band, no ramp, VO2 on a Red day) — surface them without blocking the save.
function surfaceWarnings(response: WorkoutActionResponse): void {
  for (const warning of response.warnings ?? []) {
    toast.warning(warning.detail);
  }
}

function formatDate(value: string): string {
  return new Date(`${value}T00:00:00`).toLocaleDateString(undefined, {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
  });
}

function iconFor(workoutType: string) {
  const category = categoryForWorkoutType(workoutType);
  if (category === 'cycle') return Bike;
  if (category === 'weights') return Dumbbell;
  return Wind;
}

function prettyType(type: string): string {
  const cleaned = type.replace(/[_-]+/g, ' ').trim();
  return cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
}

async function fetchSchedule() {
  const response = await apiFetch<unknown>('/api/v1/plan-actions/schedule?days=14');
  return planScheduleEnvelopeSchema.parse(response);
}

async function fetchQuickAddOptions(category: string) {
  const response = await apiFetch<unknown>(
    `/api/v1/plan-actions/quick-add-options?category=${encodeURIComponent(category)}`,
  );
  return quickAddOptionsEnvelopeSchema.parse(response).data.options;
}

async function fetchRestructurePreview(weekStart: string) {
  const response = await apiFetch<unknown>(
    `/api/v1/restructure/week-ahead?week_start=${encodeURIComponent(weekStart)}`,
  );
  return restructureEnvelopeSchema.parse(response);
}

function weekStartForDate(value: string): string {
  const [year, month, day] = value.split('-').map(Number);
  const date = new Date(Date.UTC(year, (month ?? 1) - 1, day ?? 1));
  const weekday = date.getUTCDay() || 7;
  date.setUTCDate(date.getUTCDate() - (weekday - 1));
  return date.toISOString().slice(0, 10);
}

function formatWeekLabel(weekStart: string): string {
  return new Date(`${weekStart}T00:00:00`).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
  });
}

function reasonLabel(reason: string): string {
  if (reason === 'defer_fatigue') return 'Fatigue moved a hard session later';
  if (reason === 'no_stack') return 'Separated hard sessions';
  if (reason === 'reorder') return 'Rebalanced the week';
  return reason.replace(/[_-]+/g, ' ').trim();
}

interface MoveableWorkout extends PlanWorkout {
  day: string;
}

type WeekView = 'glance' | 'edit';

export function WeekAheadPage() {
  const { player } = useAuth();
  const isAdmin = player?.role === 'admin';
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ['plan-schedule'], queryFn: fetchSchedule });
  const dailyLoop = useDailyLoop();
  const weeklyMix = dailyLoop.data?.data.morningAnalysis?.weeklyMix ?? null;
  const todayIso = new Date().toISOString().slice(0, 10);
  const [view, setView] = useState<WeekView>('glance');
  const [pickerWorkout, setPickerWorkout] = useState<MoveableWorkout | null>(null);
  const [quickAddTarget, setQuickAddTarget] = useState<{
    date: string;
    category: Exclude<DayCategory, 'rest'>;
  } | null>(null);
  const [restructureWeekStart, setRestructureWeekStart] = useState<string | null>(null);
  const [structuredTarget, setStructuredTarget] = useState<
    { mode: 'add'; date: string } | { mode: 'edit'; workout: PlanWorkout } | null
  >(null);

  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['plan-schedule'] }),
      queryClient.invalidateQueries({ queryKey: ['daily-loop'] }),
      queryClient.invalidateQueries({ queryKey: ['week-ahead'] }),
    ]);
  };

  const quickAddOptionsQuery = useQuery({
    queryKey: ['quick-add-options', quickAddTarget?.category],
    queryFn: () => fetchQuickAddOptions(quickAddTarget!.category),
    enabled: quickAddTarget !== null,
  });

  const restructurePreviewQuery = useQuery({
    queryKey: ['week-restructure-preview', restructureWeekStart],
    queryFn: () => fetchRestructurePreview(restructureWeekStart!),
    enabled: restructureWeekStart !== null,
  });

  const addMutation = useMutation({
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
      await invalidate();
      toast.success('Workout added');
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : 'Could not add workout'),
  });

  const structuredAddMutation = useMutation({
    mutationFn: ({ date, customBike }: { date: string; customBike: FreeformBikeWorkoutInput }) =>
      apiFetch<WorkoutActionResponse>(`/api/v1/plan-actions/days/${date}/workouts`, {
        method: 'POST',
        body: JSON.stringify({ category: 'cycle', customBike }),
      }),
    onSuccess: async (response) => {
      setStructuredTarget(null);
      await invalidate();
      toast.success('Workout added');
      surfaceWarnings(response);
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : 'Could not add workout'),
  });

  const structuredEditMutation = useMutation({
    mutationFn: ({ workoutId, customBike }: { workoutId: string; customBike: FreeformBikeWorkoutInput }) =>
      apiFetch<WorkoutActionResponse>(`/api/v1/plan-actions/planned-workouts/${workoutId}/structured`, {
        method: 'POST',
        body: JSON.stringify(customBike),
      }),
    onSuccess: async (response) => {
      setStructuredTarget(null);
      await invalidate();
      toast.success('Structure saved');
      surfaceWarnings(response);
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : 'Could not save structure'),
  });

  const moveMutation = useMutation({
    mutationFn: ({ workoutId, targetDate }: { workoutId: string; targetDate: string }) =>
      apiFetch(`/api/v1/workout-delivery/planned-workouts/${workoutId}/swap`, {
        method: 'POST',
        body: JSON.stringify({ targetDate }),
      }),
    onError: (error) => toast.error(error instanceof Error ? error.message : 'Could not move workout'),
  });

  const skipDayMutation = useMutation({
    mutationFn: (date: string) => apiFetch(`/api/v1/plan-actions/days/${date}/skip`, { method: 'POST' }),
    onSuccess: async () => {
      await invalidate();
      toast.success('Day skipped');
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : 'Could not skip day'),
  });

  const skipMutation = useMutation({
    mutationFn: (workoutId: string) =>
      apiFetch(`/api/v1/workout-delivery/planned-workouts/${workoutId}/skip`, { method: 'POST' }),
    onSuccess: async () => {
      await invalidate();
      toast.success('Session skipped');
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : 'Could not skip the session'),
  });

  const removeMutation = useMutation({
    mutationFn: (workoutId: string) =>
      apiFetch(`/api/v1/workout-delivery/planned-workouts/${workoutId}/remove`, { method: 'POST' }),
    onSuccess: async () => {
      await invalidate();
      toast.success('Workout removed');
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : 'Could not remove the workout'),
  });

  const markResetMutation = useMutation({
    mutationFn: (date: string) =>
      apiFetch(`/api/v1/plan-actions/weeks/${date}/reset`, { method: 'POST' }),
    onSuccess: async () => {
      await invalidate();
      toast.success('Week marked as reset');
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : 'Could not reset the week'),
  });

  const unsetResetMutation = useMutation({
    mutationFn: (date: string) =>
      apiFetch(`/api/v1/plan-actions/weeks/${date}/reset`, { method: 'DELETE' }),
    onSuccess: async () => {
      await invalidate();
      toast.success('Week restored');
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : 'Could not restore the week'),
  });

  const restructureApplyMutation = useMutation({
    mutationFn: (weekStart: string) =>
      apiFetch(`/api/v1/restructure/apply?week_start=${encodeURIComponent(weekStart)}`, { method: 'POST' }),
    onSuccess: async () => {
      setRestructureWeekStart(null);
      await invalidate();
      toast.success('Week rearranged');
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : 'Could not rearrange the week'),
  });

  const busy =
    addMutation.isPending ||
    structuredAddMutation.isPending ||
    structuredEditMutation.isPending ||
    moveMutation.isPending ||
    skipDayMutation.isPending ||
    skipMutation.isPending ||
    removeMutation.isPending ||
    markResetMutation.isPending ||
    unsetResetMutation.isPending ||
    restructureApplyMutation.isPending;
  const moveOptions = useMemo(
    () =>
      pickerWorkout && query.data
        ? query.data.data.schedule.map((day) => ({
            date: day.date,
            label: formatDate(day.date),
            detail:
              day.workouts.length > 0 ? day.workouts.map((workout) => workout.title).join(' · ') : 'Rest',
            isToday: day.date === todayIso,
            isCurrent: day.date === pickerWorkout.day,
          }))
        : [],
    [pickerWorkout, query.data, todayIso],
  );

  const workoutById = useMemo(() => {
    const map = new Map<string, { title: string; workoutDate: string }>();
    for (const day of query.data?.data.schedule ?? []) {
      for (const workout of day.workouts) {
        map.set(workout.id, { title: workout.title, workoutDate: workout.workoutDate });
      }
    }
    return map;
  }, [query.data]);

  const restructurePreview = useMemo(() => {
    const data = restructurePreviewQuery.data?.data;
    if (!data) return null;
    return {
      changed: data.changed,
      fatigued: data.fatigued,
      reasons: data.signal.reasons,
      notes: data.notes,
      conflictsBefore: data.conflictsBefore,
      changes: data.changes.map((change) => {
        const incoming = workoutById.get(change.toWorkoutId);
        const outgoing = workoutById.get(change.fromWorkoutId);
        return {
          workoutDate: formatDate(change.workoutDate),
          incomingTitle: incoming?.title ?? 'Rescheduled ride',
          outgoingTitle: outgoing?.title ?? 'planned ride',
          reason: reasonLabel(change.reason),
        };
      }),
    };
  }, [restructurePreviewQuery.data, workoutById]);

  const schedule = query.data?.data.schedule ?? [];
  const glanceDays = schedule.slice(0, 7);
  const laterDays = schedule.slice(7);

  const closePicker = () => setPickerWorkout(null);

  const handleMove = (targetDate: string) => {
    if (!pickerWorkout) return;
    moveMutation.mutate(
      { workoutId: pickerWorkout.id, targetDate },
      {
        onSuccess: async () => {
          closePicker();
          await invalidate();
          toast.success('Schedule updated');
        },
      },
    );
  };

  return (
    <div className="space-y-5">
      <PageHeader title="Week" />

      <p className="text-sm text-text-secondary">This week at a glance: what’s on each day, what’s done, and what’s still to do.</p>

      {isAdmin ? (
        <Tabs<WeekView>
          items={[
            { value: 'glance', label: 'This week' },
            { value: 'edit', label: 'Edit week' },
          ]}
          value={view}
          onChange={setView}
          variant="segmented"
        />
      ) : null}

      {weeklyMix ? <WeeklyMixCard mix={weeklyMix} showShortfall /> : null}

      {query.isLoading ? (
        <div className="space-y-3">
          <Skeleton className="h-32 w-full rounded-2xl" />
          <Skeleton className="h-32 w-full rounded-2xl" />
        </div>
      ) : query.isError || !query.data ? (
        <ErrorState
          title="Plan couldn't load"
          description={query.error instanceof Error ? query.error.message : "We couldn't reach the server just now."}
          onRetry={() => query.refetch()}
        />
      ) : query.data.data.schedule.length === 0 ? (
        <EmptyState title="No plan window yet" description="Your schedule will show up here once it's set." />
      ) : (
        view === 'edit' && isAdmin ? (
          <div className="space-y-4">
            <Card>
              <CardContent className="space-y-3 pt-6">
                <p className="text-sm text-text-secondary">
                  The organiser keeps the full move, add, skip, remove, reset, and restructure rail one layer down.
                </p>
                <div className="flex flex-wrap gap-2">
                  <Button asChild size="sm" variant="outline">
                    <Link to="/holiday">
                      <Umbrella className="mr-1.5 h-4 w-4" aria-hidden />
                      Holiday
                    </Link>
                  </Button>
                  <Button asChild size="sm" variant="outline">
                    <Link to="/builder">
                      <Hammer className="mr-1.5 h-4 w-4" aria-hidden />
                      New training block
                    </Link>
                  </Button>
                </div>
                <p className="text-sm text-text-secondary">Doing something different? Just ride it — I&apos;ll read it after.</p>
              </CardContent>
            </Card>

            <div className="space-y-3">
              {schedule.map((day, index) => {
                const previous = schedule[index - 1];
                const showCharacter =
                  day.weekCharacter != null &&
                  (previous == null || previous.weekCharacter?.label !== day.weekCharacter.label);
                return (
                  <div key={day.date} className="space-y-3">
                    {showCharacter && day.weekCharacter ? (
                      <WeekCharacterBanner
                        day={day}
                        busy={busy}
                        onRestructure={() => setRestructureWeekStart(weekStartForDate(day.date))}
                        onMarkReset={() => markResetMutation.mutate(day.date)}
                        onUnsetReset={() => unsetResetMutation.mutate(day.date)}
                      />
                    ) : null}
                    <ScheduleDayCard
                      day={day}
                      isToday={day.date === todayIso}
                      busy={busy}
                      onAdd={(category) => setQuickAddTarget({ date: day.date, category })}
                      onBuildRide={() => setStructuredTarget({ mode: 'add', date: day.date })}
                      onMove={(workout) => setPickerWorkout(workout)}
                      onEditStructure={(workout) => setStructuredTarget({ mode: 'edit', workout })}
                      onSkipDay={() => skipDayMutation.mutate(day.date)}
                      onSkipWorkout={(workoutId) => skipMutation.mutate(workoutId)}
                      onRemoveWorkout={(workoutId) => removeMutation.mutate(workoutId)}
                    />
                  </div>
                );
              })}
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            <WeekGlanceCard days={glanceDays} todayIso={todayIso} />
            {laterDays.length > 0 ? <WeekPreviewCard days={laterDays} /> : null}
            {isAdmin ? (
              <Card className="border-dashed">
                <CardContent className="flex items-start gap-3 pt-6">
                  <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-primary" aria-hidden />
                  <div className="space-y-1">
                    <p className="text-sm font-medium text-text-primary">Admin tools stay one layer down.</p>
                    <p className="text-sm text-text-secondary">
                      Open <strong>Edit week</strong> for move, add, skip, reset, and restructure controls.
                    </p>
                  </div>
                </CardContent>
              </Card>
            ) : null}
          </div>
        )
      )}

      <MoveWorkoutSheet
        open={pickerWorkout !== null}
        workoutTitle={pickerWorkout?.title ?? 'workout'}
        busy={moveMutation.isPending}
        days={moveOptions}
        onClose={closePicker}
        onSelect={handleMove}
      />

      <QuickAddSheet
        open={quickAddTarget !== null}
        category={quickAddTarget?.category ?? null}
        options={quickAddOptionsQuery.data ?? []}
        loading={quickAddOptionsQuery.isLoading}
        busy={addMutation.isPending}
        onClose={() => setQuickAddTarget(null)}
        onConfirm={(subtype, durationMin) => {
          if (!quickAddTarget) return;
          addMutation.mutate({ date: quickAddTarget.date, category: quickAddTarget.category, subtype, durationMin });
        }}
      />

      <StructuredWorkoutSheet
        open={structuredTarget !== null}
        mode={structuredTarget?.mode ?? 'add'}
        workoutTitle={structuredTarget?.mode === 'edit' ? structuredTarget.workout.title : undefined}
        initialStructuredWorkout={
          structuredTarget?.mode === 'edit' ? structuredTarget.workout.structuredWorkout : null
        }
        busy={structuredAddMutation.isPending || structuredEditMutation.isPending}
        onClose={() => setStructuredTarget(null)}
        onConfirm={(customBike) => {
          if (structuredTarget?.mode === 'add') {
            structuredAddMutation.mutate({ date: structuredTarget.date, customBike });
          } else if (structuredTarget?.mode === 'edit') {
            structuredEditMutation.mutate({
              workoutId: structuredTarget.workout.id,
              customBike,
            });
          }
        }}
      />

      <WeekRestructureSheet
        open={restructureWeekStart !== null}
        busy={restructureApplyMutation.isPending}
        loading={restructurePreviewQuery.isLoading}
        weekLabel={restructureWeekStart ? formatWeekLabel(restructureWeekStart) : 'week'}
        preview={restructurePreview}
        onClose={() => setRestructureWeekStart(null)}
        onApply={() => restructureWeekStart && restructureApplyMutation.mutate(restructureWeekStart)}
      />
    </div>
  );
}

function WeekGlanceCard({ days, todayIso }: { days: PlanDay[]; todayIso: string }) {
  const workoutCount = days.reduce((total, day) => total + day.workouts.length, 0);
  const doneCount = days.reduce(
    (total, day) => total + day.workouts.filter((workout) => workout.status === 'completed').length,
    0,
  );
  const todoCount = Math.max(workoutCount - doneCount, 0);

  return (
    <Card>
      <CardHeader className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <CardTitle>This week</CardTitle>
          <Badge variant="muted">{workoutCount === 0 ? 'Rest week' : `${workoutCount} sessions`}</Badge>
        </div>
        <div className="flex flex-wrap gap-2 text-sm">
          <Badge variant={doneCount > 0 ? 'success' : 'muted'}>
            <CheckCircle2 className="mr-1 h-3.5 w-3.5" aria-hidden />
            {doneCount} done
          </Badge>
          <Badge variant={todoCount > 0 ? 'accent' : 'muted'}>{todoCount} to do</Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {days.map((day) => (
          <GlanceDayRow key={day.date} day={day} isToday={day.date === todayIso} />
        ))}
      </CardContent>
    </Card>
  );
}

function WeekPreviewCard({ days }: { days: PlanDay[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Coming up</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {days.map((day) => (
          <GlanceDayRow key={day.date} day={day} isToday={false} compact />
        ))}
      </CardContent>
    </Card>
  );
}

function GlanceDayRow({
  day,
  isToday,
  compact = false,
}: {
  day: PlanDay;
  isToday: boolean;
  compact?: boolean;
}) {
  return (
    <div className="rounded-xl border border-border bg-bg px-3 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <p className="font-medium text-text-primary">{formatDate(day.date)}</p>
        {isToday ? <Badge variant="default">Today</Badge> : null}
        <Badge variant={day.dayState.isRest ? 'muted' : 'accent'}>{day.dayState.label}</Badge>
      </div>
      {day.workouts.length === 0 ? (
        <p className="mt-2 text-sm text-text-secondary">Rest day</p>
      ) : (
        <div className={cn('mt-3 space-y-2', compact && 'space-y-1.5')}>
          {day.workouts.map((workout) => {
            const isDone = workout.status === 'completed';
            return (
              <div key={workout.id} className="flex items-start justify-between gap-3 rounded-lg bg-surface px-3 py-2">
                <div className="min-w-0">
                  <p className="text-sm font-medium text-text-primary">{workout.title}</p>
                  <p className="text-xs text-text-secondary">
                    {prettyType(workout.workoutType)}
                    {workout.plannedDurationMin ? ` · ${workout.plannedDurationMin} min` : ''}
                  </p>
                </div>
                <Badge variant={isDone ? 'success' : 'muted'} className="shrink-0">
                  {isDone ? 'Done' : 'To do'}
                </Badge>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function WeekCharacterBanner({
  day,
  busy,
  onRestructure,
  onMarkReset,
  onUnsetReset,
}: {
  day: PlanDay;
  busy: boolean;
  onRestructure: () => void;
  onMarkReset: () => void;
  onUnsetReset: () => void;
}) {
  const character = day.weekCharacter;
  if (!character) return null;
  const isReset = character.isReset;
  return (
    <div className="flex flex-wrap items-center gap-2 px-1">
      <Badge variant={character.isHoliday || isReset ? 'accent' : 'muted'}>{character.label}</Badge>
      {!character.isHoliday ? (
        <Button type="button" size="sm" variant="outline" disabled={busy} onClick={onRestructure}>
          <Shuffle className="h-4 w-4" aria-hidden />
          Rearrange week
        </Button>
      ) : null}
      {!character.isHoliday ? (
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={busy}
          onClick={isReset ? onUnsetReset : onMarkReset}
        >
          <RotateCcw className="h-4 w-4" aria-hidden />
          {isReset ? 'Restore week' : 'Light reset'}
        </Button>
      ) : null}
    </div>
  );
}

function ScheduleDayCard({
  day,
  isToday,
  busy,
  onAdd,
  onBuildRide,
  onMove,
  onEditStructure,
  onSkipDay,
  onSkipWorkout,
  onRemoveWorkout,
}: {
  day: PlanDay;
  isToday: boolean;
  busy: boolean;
  onAdd: (category: Exclude<DayCategory, 'rest'>) => void;
  onBuildRide: () => void;
  onMove: (workout: MoveableWorkout) => void;
  onEditStructure: (workout: PlanWorkout) => void;
  onSkipDay: () => void;
  onSkipWorkout: (workoutId: string) => void;
  onRemoveWorkout: (workoutId: string) => void;
}) {
  const hasCompletedWorkout = day.workouts.some((workout) => workout.status === 'completed');
  return (
    <Card className={cn(isToday && 'border-primary/50')}>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          <CalendarDays className="h-4 w-4 text-primary" aria-hidden />
          {formatDate(day.date)}
          {isToday && <Badge variant="default">Today</Badge>}
          <Badge variant={day.dayState.isRest ? 'muted' : 'accent'}>{day.dayState.label}</Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {day.workouts.length === 0 ? (
          <div className="flex items-center gap-3 rounded-xl border border-dashed border-border px-3 py-3 text-sm text-text-secondary">
            <Moon className="h-4 w-4" aria-hidden />
            Rest day
          </div>
        ) : (
          day.workouts.map((workout) => (
            <WorkoutRow
              key={workout.id}
              workout={workout}
              busy={busy}
              onMove={() => onMove({ ...workout, day: day.date })}
              onEditStructure={() => onEditStructure(workout)}
              onSkip={() => onSkipWorkout(workout.id)}
              onRemove={() => onRemoveWorkout(workout.id)}
            />
          ))
        )}

        <div className="flex flex-wrap gap-2">
          <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => onAdd('cycle')}>
            <Plus className="h-4 w-4" aria-hidden />
            Cycle
          </Button>
          <Button type="button" size="sm" variant="outline" disabled={busy} onClick={onBuildRide}>
            <SlidersHorizontal className="h-4 w-4" aria-hidden />
            Build ride
          </Button>
          <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => onAdd('weights')}>
            <Plus className="h-4 w-4" aria-hidden />
            Weights
          </Button>
          <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => onAdd('flexibility')}>
            <Plus className="h-4 w-4" aria-hidden />
            Flexibility
          </Button>
          {day.workouts.length > 0 && (
            <Button type="button" size="sm" variant="outline" disabled={busy} onClick={onSkipDay}>
              <Trash2 className="h-4 w-4" aria-hidden />
              {hasCompletedWorkout ? 'Skip remaining' : 'Skip whole day'}
            </Button>
          )}
        </div>
        {day.workouts.length > 0 ? (
          <p className="text-xs text-text-secondary">
            {hasCompletedWorkout
              ? 'Completed sessions stay on the day. This skips only the sessions still left to do.'
              : 'Use a session’s own Skip or Remove to get rid of just that one — Skip whole day clears everything.'}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

function WorkoutRow({
  workout,
  busy,
  onMove,
  onEditStructure,
  onSkip,
  onRemove,
}: {
  workout: PlanWorkout;
  busy: boolean;
  onMove: () => void;
  onEditStructure: () => void;
  onSkip: () => void;
  onRemove: () => void;
}) {
  const [confirming, setConfirming] = useState<'skip' | 'remove' | null>(null);
  const Icon = iconFor(workout.workoutType);
  // Batch 60: a completed session can't be re-slotted — the Move control drops
  // out and a "Done" badge takes its place (the swap endpoint also 409s a
  // completed source or target, so this is UI clarity over an enforced guard).
  const isComplete = workout.status === 'completed';
  const isBike = categoryForWorkoutType(workout.workoutType) === 'cycle';
  const isOutdoor =
    isBike && (workout.structuredWorkout as { delivery?: string } | null)?.delivery === 'outdoor';
  // Batch 79: Remove only applies to workouts the user added (`remove_workout`
  // 409s on anything else); coach-planned sessions use Skip instead.
  const isAdded = workout.source === 'plan_action_add';
  return (
    <div className="rounded-xl border border-border bg-bg px-3 py-3">
      <div className="flex items-start gap-3">
        <Icon className="mt-0.5 h-5 w-5 shrink-0 text-primary" aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="font-medium text-text-primary">{workout.title}</p>
          <p className="text-sm text-text-secondary">
            {prettyType(workout.workoutType)}
            {workout.plannedDurationMin ? ` · ${workout.plannedDurationMin} min` : ''}
            {workout.intensityTarget ? ` · ${workout.intensityTarget}` : ''}
          </p>
        </div>
        {isComplete ? (
          <Badge variant="success" className="shrink-0">
            Done
          </Badge>
        ) : null}
      </div>
      {isOutdoor ? <OutdoorDeliveryBadge delivery={workout.outdoorDelivery ?? null} /> : null}
      {isComplete ? null : confirming === null ? (
        <div className="mt-3 flex flex-wrap gap-2">
          <Button type="button" size="sm" variant="outline" disabled={busy} onClick={onMove}>
            Move
          </Button>
          {isBike ? (
            <Button type="button" size="sm" variant="outline" disabled={busy} onClick={onEditStructure}>
              <SlidersHorizontal className="h-4 w-4" aria-hidden />
              Edit structure
            </Button>
          ) : null}
          <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => setConfirming('skip')}>
            <Trash2 className="h-4 w-4" aria-hidden />
            Skip
          </Button>
          {isAdded ? (
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={busy}
              onClick={() => setConfirming('remove')}
            >
              <Trash2 className="h-4 w-4" aria-hidden />
              Remove
            </Button>
          ) : null}
        </div>
      ) : (
        <div className="mt-3 rounded-lg border border-error/30 bg-error/10 px-3 py-3">
          <p className="text-sm text-text-primary">
            {confirming === 'skip'
              ? 'Skip just this session? It will be marked as skipped.'
              : 'Remove this added workout? It will disappear from your plan.'}
          </p>
          <div className="mt-2 flex gap-2">
            <Button
              type="button"
              size="sm"
              variant="destructive"
              disabled={busy}
              onClick={() => {
                setConfirming(null);
                if (confirming === 'skip') onSkip();
                else onRemove();
              }}
            >
              {busy ? 'Working…' : confirming === 'skip' ? 'Confirm skip' : 'Confirm remove'}
            </Button>
            <Button type="button" size="sm" variant="outline" onClick={() => setConfirming(null)}>
              Cancel
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

function OutdoorDeliveryBadge({ delivery }: { delivery: PlanWorkout['outdoorDelivery'] | null }) {
  if (delivery?.status === 'pushed') {
    return (
      <div className="mt-2">
        <Badge variant="success">Sent to Garmin</Badge>
      </div>
    );
  }
  if (delivery?.status === 'failed') {
    return (
      <div className="mt-2">
        <Badge variant="error" title={delivery.lastError ?? undefined}>
          Garmin send failed — will retry
        </Badge>
      </div>
    );
  }
  return (
    <div className="mt-2">
      <Badge variant="muted">Outdoor · sends to Garmin</Badge>
    </div>
  );
}
