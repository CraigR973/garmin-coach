import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { conversationLearningEnvelopeSchema } from '@coach/shared';
import { apiFetch } from '@/lib/api';

export const COACH_MEMORY_QUERY_KEY = ['coach-memory'];
export const LEARNING_QUERY_KEY = ['coach-memory-learning'];

export async function fetchConversationLearning() {
  const response = await apiFetch<unknown>('/api/v1/coach-memory/learning');
  return conversationLearningEnvelopeSchema.parse(response);
}

export function useConversationLearning() {
  return useQuery({ queryKey: LEARNING_QUERY_KEY, queryFn: fetchConversationLearning });
}

/** Batch 346: Mark answers one memory proposal in one tap, from Home. */
export function useReviewMemory({ onSuccess }: { onSuccess?: (decision: 'accept' | 'reject') => void } = {}) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, decision }: { id: string; decision: 'accept' | 'reject' }) => {
      const response = await apiFetch<unknown>(`/api/v1/coach-memory/learning/${id}`, {
        method: 'PATCH',
        body: JSON.stringify({ decision }),
      });
      return conversationLearningEnvelopeSchema.parse(response);
    },
    onSuccess: async (response, variables) => {
      queryClient.setQueryData(LEARNING_QUERY_KEY, response);
      await queryClient.invalidateQueries({ queryKey: COACH_MEMORY_QUERY_KEY });
      onSuccess?.(variables.decision);
    },
  });
}

/** Batch 346: Mark removes one thing the coach remembers. */
export function useForgetMemory({ onSuccess }: { onSuccess?: () => void } = {}) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (itemId: string) => {
      const response = await apiFetch<unknown>(`/api/v1/coach-memory/learning/memories/${itemId}`, {
        method: 'DELETE',
      });
      return conversationLearningEnvelopeSchema.parse(response);
    },
    onSuccess: async (response) => {
      queryClient.setQueryData(LEARNING_QUERY_KEY, response);
      await queryClient.invalidateQueries({ queryKey: COACH_MEMORY_QUERY_KEY });
      onSuccess?.();
    },
  });
}
