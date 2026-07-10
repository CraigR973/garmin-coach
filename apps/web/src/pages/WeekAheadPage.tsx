import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  customBikeWorkoutInputSchema,
  planScheduleEnvelopeSchema,
  quickAddOptionsEnvelopeSchema,
} from '@coach/shared';
import { Bike, CalendarDays, Dumbbell, Moon, Plus, SlidersHorizontal, Trash2, Wind } from 'lucide-react';
import { toast } from 'sonner';
import { MoveWorkoutSheet } from '@/components/MoveWorkoutSheet';
import { QuickAddSheet } from '@/components/QuickAddSheet';
import { StructuredWorkoutSheet } from '@/components/StructuredWorkoutSheet';
import { PageHeader } from '@/components/PageHeader';
import { WeeklyMixCard } from '@/components/WeeklyMixCard';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { EmptyState, ErrorState } from '@/components/EmptyState';
import { Skeleton } from '@/components/ui/skeleton';
import { apiFetch } from '@/lib/api';
import { cn } from '@/lib/utils';
import { useDailyLoop } from '@/hooks/useDailyLoop';
import { categoryForWorkoutType, type DayCategory } from '@/lib/workoutCategories';

type PlanScheduleEnvelope = typeof planScheduleEnvelopeSchema._type;
type PlanDay = PlanScheduleEnvelope['data']['schedule'][number];
type PlanWorkout = PlanDay['workouts'][number];
type CustomBikeWorkoutInput = typeof customBikeWorkoutInputSchema._type;

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

interface MoveableWorkout extends PlanWorkout {
  day: string;
}

export function WeekAheadPage() {
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ['plan-schedule'], queryFn: fetchSchedule });
  const dailyLoop = useDailyLoop();
  const weeklyMix = dailyLoop.data?.data.morningAnalysis?.weeklyMix ?? null;
  const todayIso = new Date().toISOString().slice(0, 10);
  const [pickerWorkout, setPickerWorkout] = useState<MoveableWorkout | null>(null);
  const [quickAddTarget, setQuickAddTarget] = useState<{
    date: string;
    category: Exclude<DayCategory, 'rest'>;
  } | null>(null);
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
    mutationFn: ({ date, customBike }: { date: string; customBike: CustomBikeWorkoutInput }) =>
      apiFetch(`/api/v1/plan-actions/days/${date}/workouts`, {
        method: 'POST',
        body: JSON.stringify({ category: 'cycle', customBike }),
      }),
    onSuccess: async () => {
      setStructuredTarget(null);
      await invalidate();
      toast.success('Workout added');
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : 'Could not add workout'),
  });

  const structuredEditMutation = useMutation({
    mutationFn: ({ workoutId, customBike }: { workoutId: string; customBike: CustomBikeWorkoutInput }) =>
      apiFetch(`/api/v1/plan-actions/planned-workouts/${workoutId}/structured`, {
        method: 'POST',
        body: JSON.stringify(customBike),
      }),
    onSuccess: async () => {
      setStructuredTarget(null);
      await invalidate();
      toast.success('Structure saved');
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

  const busy =
    addMutation.isPending ||
    structuredAddMutation.isPending ||
    structuredEditMutation.isPending ||
    moveMutation.isPending ||
    skipDayMutation.isPending;
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
      <PageHeader title="Plan" />

      <p className="text-sm text-text-secondary">
        Move a workout onto any visible day, add light work, or skip a day.
      </p>
      <p className="text-sm text-text-secondary">
        Doing something different? Just ride it — I'll read it after.
      </p>

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
        <div className="space-y-3">
          {query.data.data.schedule.map((day) => (
            <ScheduleDayCard
              key={day.date}
              day={day}
              isToday={day.date === todayIso}
              busy={busy}
              onAdd={(category) => setQuickAddTarget({ date: day.date, category })}
              onBuildRide={() => setStructuredTarget({ mode: 'add', date: day.date })}
              onMove={(workout) => setPickerWorkout(workout)}
              onEditStructure={(workout) => setStructuredTarget({ mode: 'edit', workout })}
              onSkipDay={() => skipDayMutation.mutate(day.date)}
            />
          ))}
        </div>
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
}: {
  day: PlanDay;
  isToday: boolean;
  busy: boolean;
  onAdd: (category: Exclude<DayCategory, 'rest'>) => void;
  onBuildRide: () => void;
  onMove: (workout: MoveableWorkout) => void;
  onEditStructure: (workout: PlanWorkout) => void;
  onSkipDay: () => void;
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
              {hasCompletedWorkout ? 'Skip remaining' : 'Skip day'}
            </Button>
          )}
        </div>
        {hasCompletedWorkout ? (
          <p className="text-xs text-text-secondary">
            Completed sessions stay on the day. This skips only the sessions still left to do.
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
}: {
  workout: PlanWorkout;
  busy: boolean;
  onMove: () => void;
  onEditStructure: () => void;
}) {
  const Icon = iconFor(workout.workoutType);
  // Batch 60: a completed session can't be re-slotted — the Move control drops
  // out and a "Done" badge takes its place (the swap endpoint also 409s a
  // completed source or target, so this is UI clarity over an enforced guard).
  const isComplete = workout.status === 'completed';
  const isBike = categoryForWorkoutType(workout.workoutType) === 'cycle';
  const isOutdoor =
    isBike && (workout.structuredWorkout as { delivery?: string } | null)?.delivery === 'outdoor';
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
      {isComplete ? null : (
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
        </div>
      )}
    </div>
  );
}

function OutdoorDeliveryBadge({ delivery }: { delivery: PlanWorkout['outdoorDelivery'] | null }) {
  if (delivery?.status === 'pushed') {
    return (
      <p className="mt-2">
        <Badge variant="success">Sent to Garmin</Badge>
      </p>
    );
  }
  if (delivery?.status === 'failed') {
    return (
      <p className="mt-2">
        <Badge variant="error" title={delivery.lastError ?? undefined}>
          Garmin send failed — will retry
        </Badge>
      </p>
    );
  }
  return (
    <p className="mt-2">
      <Badge variant="muted">Outdoor · sends to Garmin</Badge>
    </p>
  );
}
