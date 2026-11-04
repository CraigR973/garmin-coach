import { useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { dailyLoopEnvelopeSchema } from '@coach/shared';
import { apiFetch } from '@/lib/api';
import { friendlyError } from '@/lib/friendlyError';

export type MedicinesAnswer = 'none' | 'new';

/** Batch 370.3: his answer to Home's quarterly "Any new medicines?". Nothing is regraded. */
export async function answerMedicines({
  subjectDate,
  answer,
  words,
}: {
  subjectDate: string;
  answer: MedicinesAnswer;
  words?: string | null;
}) {
  const response = await apiFetch<unknown>(`/api/v1/daily-loop/${subjectDate}/medicines`, {
    method: 'POST',
    body: JSON.stringify(words?.trim() ? { answer, words: words.trim() } : { answer }),
  });
  return dailyLoopEnvelopeSchema.parse(response);
}

/** The two keys today's daily loop is read under: the check-in's, and every other page's. */
const TODAY_QUERY_KEYS = [['daily-loop'], ['daily-loop', 'today']] as const;

export function useAnswerMedicines(options?: { onError?: () => void }) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: answerMedicines,
    onSuccess: (envelope) => {
      for (const key of TODAY_QUERY_KEYS) queryClient.setQueryData(key, envelope);
    },
    // The app's existing line for a change that did not go through.
    onError: (error) => {
      toast.error(friendlyError(error, 'save'));
      options?.onError?.();
    },
  });
}
