import { useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { type ChestFollowUpAnswer, dailyLoopEnvelopeSchema } from '@coach/shared';
import { apiFetch } from '@/lib/api';
import { storedMorning } from '@/lib/storedMorning';
import { waitForRegrade } from './useAnswerSymptomQuestion';

/**
 * Batch 315: Home's chest or heart follow-up is answered in one tap, and saves nothing
 * else. The answer has a row of its own, not the check-in, so he can answer on a morning
 * he has not checked in; the server regrades today on it.
 */
export async function answerChestFollowUp({
  subjectDate,
  answer,
}: {
  subjectDate: string;
  answer: ChestFollowUpAnswer;
}) {
  const response = await apiFetch<unknown>(
    `/api/v1/daily-loop/${subjectDate}/symptom-follow-up`,
    {
      method: 'POST',
      body: JSON.stringify({ answer }),
    },
  );
  return dailyLoopEnvelopeSchema.parse(response);
}

/** The two keys today's daily loop is read under: the check-in's, and every other page's. */
const TODAY_QUERY_KEYS = [['daily-loop'], ['daily-loop', 'today']] as const;

export function useAnswerChestFollowUp(options?: { onSettled?: (regraded: boolean) => void }) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: answerChestFollowUp,
    onSuccess: async (envelope) => {
      for (const key of TODAY_QUERY_KEYS) queryClient.setQueryData(key, envelope);
      const regraded = await waitForRegrade(queryClient, storedMorning(envelope.data)?.id ?? null);
      options?.onSettled?.(regraded);
    },
    // The app's existing line for a change that did not go through.
    onError: (error) => {
      toast.error(error instanceof Error ? error.message : 'Could not make that change');
      options?.onSettled?.(false);
    },
  });
}
