import { useMutation, useQueryClient } from '@tanstack/react-query';
import { RotateCcw } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { useZwiftRail } from '@/hooks/useZwiftRail';
import { apiFetch } from '@/lib/api';
import { friendlyError } from '@/lib/friendlyError';
import {
  LIVE_RIDE_NOT_THIS_DAY,
  NOT_THIS_DAY_LINE,
  RESTORE_PLAN_RIDE_LABEL,
  liveRideLine,
  restoredToast,
  showsLiveRide,
  type LiveRide,
} from '@/lib/liveRide';

/**
 * Batch 335 (UX333-01): the ride Zwift holds, when it is not the plan row's. A change
 * made for this day (an easing he approved, a pick, his own edit) is named; a ride that
 * belongs to another day, or to an older version of the plan, is named with the one
 * action that reconciles it. Nothing renders for the plan's own ride.
 */
export function ZwiftRideLine({
  ride,
  workoutId,
}: {
  ride: LiveRide | null | undefined;
  workoutId: string;
}) {
  const queryClient = useQueryClient();
  const rail = useZwiftRail();
  const restore = useMutation({
    mutationFn: () =>
      apiFetch(`/api/v1/workout-delivery/planned-workouts/${workoutId}/restore-plan-ride`, {
        method: 'POST',
      }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['daily-loop'] }),
        queryClient.invalidateQueries({ queryKey: ['plan-schedule'] }),
      ]);
      toast.success(restoredToast(rail));
    },
    onError: (error) => toast.error(friendlyError(error, 'save')),
  });

  if (!showsLiveRide(ride)) return null;
  if (ride.state !== LIVE_RIDE_NOT_THIS_DAY) {
    return (
      <p className="mt-1 text-xs text-text-secondary" data-testid="zwift-ride">
        {liveRideLine(ride, rail)}
      </p>
    );
  }
  return (
    <div
      className="mt-2 rounded-lg border border-warning/30 bg-warning/10 px-3 py-2 text-sm"
      data-testid="zwift-ride"
      role="note"
    >
      <p className="text-warning-text">
        {liveRideLine(ride, rail)} {NOT_THIS_DAY_LINE}
      </p>
      <Button
        type="button"
        size="sm"
        variant="outline"
        className="mt-2"
        disabled={restore.isPending}
        onClick={() => restore.mutate()}
      >
        <RotateCcw className="h-4 w-4" aria-hidden />
        {RESTORE_PLAN_RIDE_LABEL}
      </Button>
    </div>
  );
}
