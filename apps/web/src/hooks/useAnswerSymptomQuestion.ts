import { type QueryClient, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { dailyLoopEnvelopeSchema, type SymptomAnswer } from '@coach/shared';
import { apiFetch } from '@/lib/api';
import { storedMorning } from '@/lib/storedMorning';
import { fetchDailyLoop } from './useDailyLoop';

/**
 * Batch 303: Home's symptom question is answered in one tap, and saves nothing else.
 *
 * The answer used to be "any later save of the check-in". None is preselected on that
 * form, so saving it again for any reason, to add his breakfast say, counted as
 * answering "None" and dropped a symptom his note had named. This records the answer
 * with a time of its own; the server regrades today on it.
 */
export async function answerSymptomQuestion({
  subjectDate,
  answer,
}: {
  subjectDate: string;
  answer: SymptomAnswer;
}) {
  const response = await apiFetch<unknown>(`/api/v1/daily-loop/${subjectDate}/symptom-answer`, {
    method: 'POST',
    body: JSON.stringify({ answer }),
  });
  return dailyLoopEnvelopeSchema.parse(response);
}

/** How often, and for how long, Home looks for the regraded morning after an answer. */
export const REGRADE_POLL_MS = 3000;
export const REGRADE_POLL_ATTEMPTS = 30;

/** The two keys today's daily loop is read under: the check-in's, and every other page's. */
const TODAY_QUERY_KEYS = [['daily-loop'], ['daily-loop', 'today']] as const;

/**
 * Look for the regraded morning. The reply to the answer still carries the morning as it
 * was, with its brief, so nothing else on Home is waiting: the regrade stores a new
 * morning a few seconds later. Once it is there, the day's own polling follows its brief
 * (`useDailyLoop`). Resolves false if none arrived, so the card can ask again.
 */
export async function waitForRegrade(
  queryClient: QueryClient,
  beforeId: string | null,
  options: { intervalMs?: number; attempts?: number } = {},
): Promise<boolean> {
  const intervalMs = options.intervalMs ?? REGRADE_POLL_MS;
  const attempts = options.attempts ?? REGRADE_POLL_ATTEMPTS;
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
    try {
      const fresh = await fetchDailyLoop();
      for (const key of TODAY_QUERY_KEYS) queryClient.setQueryData(key, fresh);
      if ((storedMorning(fresh.data)?.id ?? null) !== beforeId) return true;
    } catch {
      // A failed look is not an answer; keep looking until the attempts run out.
    }
  }
  return false;
}

export function useAnswerSymptomQuestion(options?: { onSettled?: (regraded: boolean) => void }) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: answerSymptomQuestion,
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
