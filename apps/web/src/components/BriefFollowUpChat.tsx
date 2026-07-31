import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import {
  briefMessageInputSchema,
  type BriefMessage,
  type BriefMessageTurn,
} from '@coach/shared';
import { apiFetch } from '@/lib/api';
import { CoachConversation } from '@/components/CoachConversation';

/**
 * The inline chat on a read (Batch 119, extended by 150/178/179).
 *
 * Since Batch 179 this is one view onto a single rolling conversation rather
 * than a chat of its own: it posts into the same thread as the app-wide coach
 * sheet, but lists only the turns asked from *this* read, so a brief keeps
 * showing its own exchange instead of everything Mark has ever asked. The
 * conversation itself lives in `CoachConversation`.
 */

export interface BriefFollowUpChatProps {
  analysisId: string;
}

export function BriefFollowUpChat({ analysisId }: BriefFollowUpChatProps) {
  const queryClient = useQueryClient();

  const historyQuery = useQuery({
    queryKey: ['brief-messages', analysisId],
    queryFn: () => apiFetch<{ data: BriefMessage[] }>(`/api/v1/briefs/${analysisId}/messages`),
  });

  const askMutation = useMutation({
    mutationFn: async (nextQuestion: string) => {
      const payload = briefMessageInputSchema.parse({ question: nextQuestion });
      return apiFetch<{ data: BriefMessageTurn }>(`/api/v1/briefs/${analysisId}/messages`, {
        method: 'POST',
        body: JSON.stringify(payload),
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['brief-messages', analysisId] });
      queryClient.invalidateQueries({ queryKey: ['coach-thread'] });
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : 'Could not send that question'),
  });

  return (
    <CoachConversation
      messages={historyQuery.data?.data ?? []}
      heading="Ask about this read"
      placeholder="Ask a follow-up — why, what if, should I…"
      inputLabel="Ask a follow-up question"
      pending={askMutation.isPending}
      onAsk={(question) => askMutation.mutate(question)}
    />
  );
}
