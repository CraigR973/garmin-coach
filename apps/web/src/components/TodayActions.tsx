import { type ReactNode } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  ArrowLeftRight,
  Bike,
  ChevronRight,
  ListChecks,
  MoonStar,
  Thermometer,
  type LucideIcon,
} from 'lucide-react';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { isBikeWorkout } from '@/hooks/useDailyPhase';
import { type DailyLoopData } from '@/hooks/useDailyLoop';
import { apiFetch } from '@/lib/api';

type TodayAction = NonNullable<DailyLoopData['morningAnalysis']>['todayActions'][number];
type TodayWorkout = DailyLoopData['plannedWorkouts'][number];

const ICONS: Record<TodayAction['kind'], LucideIcon> = {
  approve_ride: Bike,
  apply_swap: ArrowLeftRight,
  sleep: MoonStar,
  thermal: Thermometer,
};

/**
 * Batch 86 (#159): the deterministic "Today" action block rendered at the top of
 * the morning brief (Home and /brief). The structured actions are assembled by the
 * backend and ride on `morningAnalysis.todayActions`; this component only decides
 * their layout, so the format can be tuned after Mark reacts without touching the
 * contract. A workout action taps through the exact rail Home already uses — the
 * approve affordance is gated live on the workout's delivery state, so an eased ride
 * that has already been approved drops out of the list rather than offering a stale
 * "Approve".
 */
export function TodayActions({
  actions,
  workouts,
}: {
  actions: readonly TodayAction[];
  workouts: readonly TodayWorkout[];
}) {
  const queryClient = useQueryClient();
  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['daily-loop'] }),
      queryClient.invalidateQueries({ queryKey: ['week-ahead'] }),
    ]);
  };

  const approveMutation = useMutation({
    mutationFn: ({ workoutId }: { workoutId: string }) =>
      apiFetch(`/api/v1/workout-delivery/planned-workouts/${workoutId}/approve-adjustment`, {
        method: 'POST',
      }),
    onSuccess: async () => {
      await invalidate();
      toast.success("Coach's adjustment uploaded to Zwift");
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : 'Could not approve the adjustment'),
  });

  const swapMutation = useMutation({
    mutationFn: ({ workoutId, targetDate }: { workoutId: string; targetDate: string }) =>
      apiFetch(`/api/v1/workout-delivery/planned-workouts/${workoutId}/swap`, {
        method: 'POST',
        body: JSON.stringify({ targetDate }),
      }),
    onSuccess: async () => {
      await invalidate();
      toast.success('Day swapped');
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : 'Could not swap the day'),
  });

  const busy = approveMutation.isPending || swapMutation.isPending;

  const rows: ReactNode[] = [];
  actions.forEach((action, index) => {
    const Icon = ICONS[action.kind];
    const key = `${action.kind}-${index}`;

    if (action.kind === 'approve_ride') {
      const workout = workouts.find((item) => item.id === action.plannedWorkoutId);
      const pending =
        Boolean(workout?.delivery?.changed) && isBikeWorkout(workout?.workoutType ?? null);
      if (!workout || !pending || !action.plannedWorkoutId) {
        return;
      }
      const workoutId = action.plannedWorkoutId;
      rows.push(
        <ActionRow key={key} icon={Icon} action={action}>
          <Button
            type="button"
            size="sm"
            disabled={busy}
            onClick={() => approveMutation.mutate({ workoutId })}
          >
            Approve
          </Button>
        </ActionRow>,
      );
      return;
    }

    if (action.kind === 'apply_swap') {
      if (!action.plannedWorkoutId || !action.targetDate) {
        return;
      }
      const workoutId = action.plannedWorkoutId;
      const targetDate = action.targetDate;
      rows.push(
        <ActionRow key={key} icon={Icon} action={action}>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={busy}
            onClick={() => swapMutation.mutate({ workoutId, targetDate })}
          >
            Apply
          </Button>
        </ActionRow>,
      );
      return;
    }

    // sleep / thermal — informational nudges that deep-link to the relevant hub.
    const href = action.href ?? '/sleep';
    rows.push(
      <li key={key}>
        <Link
          to={href}
          className="flex items-center gap-3 rounded-xl border border-border bg-bg px-3 py-3 transition-colors hover:bg-surface-elevated"
        >
          <Icon className="h-4 w-4 shrink-0 text-primary" aria-hidden />
          <ActionText action={action} />
          <ChevronRight className="h-4 w-4 shrink-0 text-text-muted" aria-hidden />
        </Link>
      </li>,
    );
  });

  if (rows.length === 0) {
    return null;
  }

  return (
    <section
      className="space-y-3 rounded-2xl border border-border bg-surface-elevated/60 p-4"
      data-testid="today-actions"
      aria-label="Today's actions"
    >
      <div className="flex items-center gap-2">
        <ListChecks className="h-4 w-4 text-primary" aria-hidden />
        <h2 className="text-sm font-semibold text-text-primary">Today</h2>
      </div>
      <ul className="space-y-2">{rows}</ul>
    </section>
  );
}

function ActionRow({
  icon: Icon,
  action,
  children,
}: {
  icon: LucideIcon;
  action: TodayAction;
  children: ReactNode;
}) {
  return (
    <li className="flex items-center gap-3 rounded-xl border border-border bg-bg px-3 py-3">
      <Icon className="h-4 w-4 shrink-0 text-primary" aria-hidden />
      <ActionText action={action} />
      <div className="shrink-0">{children}</div>
    </li>
  );
}

function ActionText({ action }: { action: TodayAction }) {
  return (
    <div className="min-w-0 flex-1">
      <p className="font-medium text-text-primary">{action.title}</p>
      {action.detail ? <p className="text-sm text-text-secondary">{action.detail}</p> : null}
    </div>
  );
}
