import { useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { dailyLoopEnvelopeSchema } from '@coach/shared';
import { apiFetch } from '@/lib/api';

/**
 * Batch 302: "Try again" is its own request, and saves nothing.
 *
 * It used to re-save the check-in. A save is an answer: it moves the check-in's
 * timestamp past a stored note reading, after which the preselected "None" governs and
 * a symptom found in his note is dropped. This asks only for the brief; the server
 * writes it into the morning Mark was already shown, so the colour cannot move under
 * him either.
 */
export async function retryBrief(subjectDate: string) {
  const response = await apiFetch<unknown>(`/api/v1/daily-loop/${subjectDate}/brief/retry`, {
    method: 'POST',
  });
  return dailyLoopEnvelopeSchema.parse(response);
}

/** The two keys today's daily loop is read under: the check-in's, and every other page's. */
const TODAY_QUERY_KEYS = [['daily-loop'], ['daily-loop', 'today']] as const;

export function useRetryBrief(options?: { onStarted?: () => void }) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: retryBrief,
    onSuccess: async (envelope) => {
      // The reply already says a brief is on its way. It replaces the failure on
      // screen before anything starts waiting, or the wait would end on the old
      // failure the moment it began.
      for (const key of TODAY_QUERY_KEYS) queryClient.setQueryData(key, envelope);
      options?.onStarted?.();
      await queryClient.invalidateQueries({ queryKey: ['daily-loop'] });
    },
    // The fallback is the app's existing line for a brief that did not finish.
    onError: (error) =>
      toast.error(
        error instanceof Error ? error.message : "I couldn't finish your brief — tap to try again",
      ),
  });
}
