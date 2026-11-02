import { useMutation } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { apiFetch } from '@/lib/api';
import {
  STRENGTH_ON_WATCH_BUTTON,
  STRENGTH_ON_WATCH_FAILED,
  strengthOnWatchToast,
} from '@/lib/strengthOnWatch';

/** Batch 340 (FC331-01): this week's Dumbbells A and B onto his watch, on his tap. Batch
 *  368.5 (UX362-08) puts the same button on Home on a dumbbell day, not only on Week. */
export function StrengthOnWatchButton({ className }: { className?: string }) {
  const watchMutation = useMutation({
    mutationFn: async () => {
      const response = await apiFetch<{
        data: { placed: string[]; alreadyThere: string[]; failed: string[] };
      }>('/api/v1/plan-actions/strength-on-watch', { method: 'POST' });
      return response.data;
    },
    onSuccess: (result) => toast.success(strengthOnWatchToast(result)),
    onError: () => toast.error(STRENGTH_ON_WATCH_FAILED),
  });
  return (
    <Button
      type="button"
      size="sm"
      variant="outline"
      className={className}
      disabled={watchMutation.isPending}
      onClick={() => watchMutation.mutate()}
    >
      {STRENGTH_ON_WATCH_BUTTON}
    </Button>
  );
}
