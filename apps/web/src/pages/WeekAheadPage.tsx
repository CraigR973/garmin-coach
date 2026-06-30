import { useMemo } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { planScheduleEnvelopeSchema } from '@coach/shared';
import { Bike, CalendarDays, Dumbbell, Moon, Plus, Trash2, Wind } from 'lucide-react';
import { toast } from 'sonner';
import { PageHeader } from '@/components/PageHeader';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
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
  const response = await apiFetch<unknown>('/api/v1/plan-actions/schedule');
  return planScheduleEnvelopeSchema.parse(response);
}

export function WeekAheadPage() {
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ['plan-schedule'], queryFn: fetchSchedule });
  const todayIso = new Date().toISOString().slice(0, 10);

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
    onSuccess: async () => {
      await invalidate();
      toast.success('Schedule updated');
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : 'Could not move workout'),
  });

  const swapIntoMutation = useMutation({
    mutationFn: ({ workoutId, targetDate }: { workoutId: string; targetDate: string }) =>
      apiFetch(`/api/v1/plan-actions/days/${targetDate}/swap-in`, {
        method: 'POST',
        body: JSON.stringify({ plannedWorkoutId: workoutId }),
      }),
    onSuccess: async () => {
      await invalidate();
      toast.success('Workout moved into the day');
    },
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

  const allWorkouts = useMemo(
    () => query.data?.data.schedule.flatMap((day) => day.workouts.map((workout) => ({ ...workout, day: day.date }))) ?? [],
    [query.data],
  );
  const busy = addMutation.isPending || moveMutation.isPending || swapIntoMutation.isPending || skipDayMutation.isPending;

  return (
    <div className="space-y-5">
      <PageHeader title="Plan" />

      <Card className="bg-surface-elevated/60">
        <CardContent className="pt-6">
          <p className="text-sm text-text-secondary">
            This is the live week. Move one workout, swap a rest day with a planned session, add light work, or skip a day.
          </p>
        </CardContent>
      </Card>

      {query.isLoading ? (
        <Card>
          <CardHeader>
            <CardTitle>Loading your week…</CardTitle>
          </CardHeader>
        </Card>
      ) : query.isError || !query.data ? (
        <Card>
          <CardHeader>
            <CardTitle>Plan couldn&apos;t load</CardTitle>
            <CardDescription>
              {query.error instanceof Error ? query.error.message : 'Please try again in a moment.'}
            </CardDescription>
          </CardHeader>
        </Card>
      ) : (
        <div className="space-y-3">
          {query.data.data.schedule.map((day) => (
            <ScheduleDayCard
              key={day.date}
              day={day}
              isToday={day.date === todayIso}
              allWorkouts={allWorkouts.filter((workout) => workout.day !== day.date)}
              busy={busy}
              onAdd={(category) => addMutation.mutate({ date: day.date, category })}
              onMove={(workoutId, targetDate) => moveMutation.mutate({ workoutId, targetDate })}
              onSwapIn={(workoutId) => swapIntoMutation.mutate({ workoutId, targetDate: day.date })}
              onSkipDay={() => skipDayMutation.mutate(day.date)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function ScheduleDayCard({
  day,
  isToday,
  allWorkouts,
  busy,
  onAdd,
  onMove,
  onSwapIn,
  onSkipDay,
}: {
  day: PlanDay;
  isToday: boolean;
  allWorkouts: Array<PlanWorkout & { day: string }>;
  busy: boolean;
  onAdd: (category: Exclude<DayCategory, 'rest'>) => void;
  onMove: (workoutId: string, targetDate: string) => void;
  onSwapIn: (workoutId: string) => void;
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
              daysToMove={nextScheduleDates(day.date)}
              busy={busy}
              onMove={onMove}
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

        {day.dayState.isRest && allWorkouts.length > 0 && (
          <div className="rounded-lg border border-border bg-surface-elevated/60 px-3 py-3">
            <p className="mb-2 text-sm font-medium text-text-primary">Swap a workout into this rest day</p>
            <div className="flex flex-wrap gap-2">
              {allWorkouts.slice(0, 6).map((workout) => (
                <Button
                  key={workout.id}
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={busy}
                  onClick={() => onSwapIn(workout.id)}
                >
                  {formatDate(workout.day)} · {workout.title}
                </Button>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function WorkoutRow({
  workout,
  daysToMove,
  busy,
  onMove,
}: {
  workout: PlanWorkout;
  daysToMove: string[];
  busy: boolean;
  onMove: (workoutId: string, targetDate: string) => void;
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
        {daysToMove.map((targetDate) => (
          <Button
            key={targetDate}
            type="button"
            size="sm"
            variant="outline"
            disabled={busy}
            onClick={() => onMove(workout.id, targetDate)}
          >
            Move {formatDate(targetDate)}
          </Button>
        ))}
      </div>
    </div>
  );
}

function nextScheduleDates(currentDate: string): string[] {
  const base = new Date(`${currentDate}T00:00:00`);
  const days: string[] = [];
  for (let offset = 1; offset <= 3; offset += 1) {
    const next = new Date(base);
    next.setDate(base.getDate() + offset);
    days.push(next.toISOString().slice(0, 10));
  }
  return days;
}
