import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { planScheduleEnvelopeSchema } from '@coach/shared';
import { Bike, CalendarDays, Dumbbell, Moon, Plus, Trash2, Wind } from 'lucide-react';
import { toast } from 'sonner';
import { MoveWorkoutSheet } from '@/components/MoveWorkoutSheet';
import { PageHeader } from '@/components/PageHeader';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { EmptyState, ErrorState } from '@/components/EmptyState';
import { Skeleton } from '@/components/ui/skeleton';
import { apiFetch } from '@/lib/api';
import { cn } from '@/lib/utils';
import { categoryForWorkoutType, type DayCategory } from '@/lib/workoutCategories';

type PlanScheduleEnvelope = typeof planScheduleEnvelopeSchema._type;
type PlanDay = PlanScheduleEnvelope['data']['schedule'][number];
type PlanWorkout = PlanDay['workouts'][number];

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

interface MoveableWorkout extends PlanWorkout {
  day: string;
}

export function WeekAheadPage() {
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ['plan-schedule'], queryFn: fetchSchedule });
  const todayIso = new Date().toISOString().slice(0, 10);
  const [pickerWorkout, setPickerWorkout] = useState<MoveableWorkout | null>(null);

  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['plan-schedule'] }),
      queryClient.invalidateQueries({ queryKey: ['daily-loop'] }),
      queryClient.invalidateQueries({ queryKey: ['week-ahead'] }),
    ]);
  };

  const addMutation = useMutation({
    mutationFn: ({ date, category }: { date: string; category: Exclude<DayCategory, 'rest'> }) =>
      apiFetch(`/api/v1/plan-actions/days/${date}/workouts`, {
        method: 'POST',
        body: JSON.stringify({ category }),
      }),
    onSuccess: async () => {
      await invalidate();
      toast.success('Workout added');
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : 'Could not add workout'),
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

  const busy = addMutation.isPending || moveMutation.isPending || skipDayMutation.isPending;
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
              onAdd={(category) => addMutation.mutate({ date: day.date, category })}
              onMove={(workout) => setPickerWorkout(workout)}
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
    </div>
  );
}

function ScheduleDayCard({
  day,
  isToday,
  busy,
  onAdd,
  onMove,
  onSkipDay,
}: {
  day: PlanDay;
  isToday: boolean;
  busy: boolean;
  onAdd: (category: Exclude<DayCategory, 'rest'>) => void;
  onMove: (workout: MoveableWorkout) => void;
  onSkipDay: () => void;
}) {
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
            />
          ))
        )}

        <div className="flex flex-wrap gap-2">
          <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => onAdd('cycle')}>
            <Plus className="h-4 w-4" aria-hidden />
            Cycle
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
              Skip day
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function WorkoutRow({
  workout,
  busy,
  onMove,
}: {
  workout: PlanWorkout;
  busy: boolean;
  onMove: () => void;
}) {
  const Icon = iconFor(workout.workoutType);
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
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button type="button" size="sm" variant="outline" disabled={busy} onClick={onMove}>
          Move
        </Button>
      </div>
    </div>
  );
}
