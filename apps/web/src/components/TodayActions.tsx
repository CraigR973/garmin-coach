import { friendlyError } from '@/lib/friendlyError';
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
import { type DailyLoopData } from '@/hooks/useDailyLoop';
import { apiFetch } from '@/lib/api';
import { useZwiftRail } from '@/hooks/useZwiftRail';
import { CHOOSE_ONE_LINE, CHOOSE_ONE_TITLE } from '@/lib/liveRide';
import { visibleTodayActions } from '@/lib/todayActions';
import { adjustmentSentToast } from '@/lib/zwiftRail';

type TodayAction = NonNullable<DailyLoopData['morningAnalysis']>['todayActions'][number];
type TodayWorkout = DailyLoopData['plannedWorkouts'][number];

const EASE_KINDS: ReadonlySet<TodayAction['kind']> = new Set(['approve_ride', 'pick_ride']);

const ICONS: Record<TodayAction['kind'], LucideIcon> = {
  approve_ride: Bike,
  pick_ride: Bike,
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
  const zwiftRail = useZwiftRail();
  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['daily-loop'] }),
      queryClient.invalidateQueries({ queryKey: ['week-ahead'] }),
    ]);
  };

  const approveMutation = useMutation({
    // Batch 306: a tired morning's pick names the version he chose.
    mutationFn: ({ workoutId, variant }: { workoutId: string; variant?: string }) =>
      apiFetch(
        `/api/v1/workout-delivery/planned-workouts/${workoutId}/approve-adjustment${
          variant ? `?variant=${encodeURIComponent(variant)}` : ''
        }`,
        { method: 'POST' },
      ),
    onSuccess: async () => {
      await invalidate();
      toast.success(adjustmentSentToast(zwiftRail));
    },
    onError: (error) =>
      toast.error(friendlyError(error, 'save')),
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
      toast.error(friendlyError(error, 'save')),
  });

  const busy = approveMutation.isPending || swapMutation.isPending;

  const renderRow = (action: TodayAction, key: string): ReactNode => {
    const Icon = ICONS[action.kind];

    if (action.kind === 'approve_ride') {
      const workoutId = action.plannedWorkoutId!;
      return (
        <ActionRow key={key} icon={Icon} action={action}>
          <Button
            type="button"
            size="sm"
            disabled={busy}
            onClick={() => approveMutation.mutate({ workoutId })}
          >
            Approve
          </Button>
        </ActionRow>
      );
    }

    if (action.kind === 'pick_ride') {
      const workoutId = action.plannedWorkoutId!;
      return (
        <li
          key={key}
          className="flex items-start gap-3 rounded-xl border border-border bg-bg px-3 py-3"
          data-testid="pick-ride"
        >
          <Icon className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden />
          <div className="min-w-0 flex-1 space-y-2">
            <ActionText action={action} />
            <div className="flex flex-wrap gap-2">
              {(action.choices ?? []).map((choice) => (
                <Button
                  key={choice.variant}
                  type="button"
                  size="sm"
                  variant={choice.variant === 'zone2' ? 'default' : 'outline'}
                  disabled={busy}
                  onClick={() => approveMutation.mutate({ workoutId, variant: choice.variant })}
                >
                  {choice.label}
                </Button>
              ))}
            </div>
          </div>
        </li>
      );
    }

    if (action.kind === 'apply_swap') {
      const workoutId = action.plannedWorkoutId!;
      const targetDate = action.targetDate!;
      return (
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
        </ActionRow>
      );
    }

    // sleep / thermal — informational nudges that deep-link to the relevant hub.
    const href = action.href ?? '/sleep';
    return (
      <li key={key}>
        <Link
          to={href}
          className="flex items-center gap-3 rounded-xl border border-border bg-bg px-3 py-3 transition-colors hover:bg-surface-elevated"
        >
          <Icon className="h-4 w-4 shrink-0 text-primary" aria-hidden />
          <ActionText action={action} />
          <ChevronRight className="h-4 w-4 shrink-0 text-text-muted" aria-hidden />
        </Link>
      </li>
    );
  };

  // Batch 335 (UX333-02): a move and an easier ride offered for one session are two
  // fixes, not two steps. They share one "Choose one" card; the API withdraws the move
  // once either is taken, and the easier ride leaves once it is approved.
  const visible = visibleTodayActions(actions, workouts);
  const choiceFor = (action: TodayAction): TodayAction | undefined =>
    action.plannedWorkoutId
      ? visible.find(
          (other) =>
            other.plannedWorkoutId === action.plannedWorkoutId &&
            (action.kind === 'apply_swap'
              ? EASE_KINDS.has(other.kind)
              : EASE_KINDS.has(action.kind) && other.kind === 'apply_swap'),
        )
      : undefined;
  const rows: ReactNode[] = [];
  const grouped = new Set<TodayAction>();
  visible.forEach((action, index) => {
    if (grouped.has(action)) return;
    const key = `${action.kind}-${index}`;
    const other = choiceFor(action);
    if (other === undefined) {
      rows.push(renderRow(action, key));
      return;
    }
    grouped.add(other);
    rows.push(
      <li
        key={key}
        className="space-y-2 rounded-xl border border-warning/30 bg-warning/10 p-3"
        data-testid="choose-one"
      >
        <div>
          <p className="font-medium text-warning-text">{CHOOSE_ONE_TITLE}</p>
          <p className="text-sm text-text-secondary">{CHOOSE_ONE_LINE}</p>
        </div>
        <ul className="space-y-2">
          {renderRow(action, `${key}-a`)}
          {renderRow(other, `${key}-b`)}
        </ul>
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
