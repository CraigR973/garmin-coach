import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { MessageCircle, Send } from 'lucide-react';
import { toast } from 'sonner';
import {
  briefMessageInputSchema,
  type BriefMessage,
  type BriefMessageTurn,
} from '@coach/shared';
import { apiFetch } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Markdown } from '@/components/Markdown';

/**
 * Follow-up chat on a brief (Batch 119). Grounded in the same context packet
 * the brief itself was generated from — "why", "what if", "should I…" — with
 * a small per-brief turn cap enforced server-side. A follow-up that reads as
 * wanting a plan adjustment can carry a `proposedPlannedWorkoutId`; tapping
 * "Propose this" calls the *existing* workout-delivery propose endpoint
 * (Decision #29's propose→approve→push gate is untouched — this only adds a
 * new entry point into the same first step).
 */

const MAX_QUESTION_LENGTH = 1000;

export interface BriefFollowUpChatProps {
  analysisId: string;
}

export function BriefFollowUpChat({ analysisId }: BriefFollowUpChatProps) {
  const queryClient = useQueryClient();
  const [question, setQuestion] = useState('');

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
      setQuestion('');
      queryClient.invalidateQueries({ queryKey: ['brief-messages', analysisId] });
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : 'Could not send that question'),
  });

  const proposeMutation = useMutation({
    mutationFn: (plannedWorkoutId: string) =>
      apiFetch(`/api/v1/workout-delivery/planned-workouts/${plannedWorkoutId}/proposals`, {
        method: 'POST',
      }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['daily-loop'] }),
        queryClient.invalidateQueries({ queryKey: ['workout-delivery'] }),
      ]);
      toast.success('Proposed — review and approve it on Delivery');
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : 'Could not propose that adjustment'),
  });

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const trimmed = question.trim();
    if (!trimmed || askMutation.isPending) return;
    askMutation.mutate(trimmed);
  }

  const messages = historyQuery.data?.data ?? [];

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-sm font-medium text-text-secondary">
        <MessageCircle className="h-4 w-4" aria-hidden />
        Ask about this brief
      </div>

      {messages.length > 0 ? (
        <ol className="space-y-3" aria-label="Follow-up conversation">
          {messages.map((message) => (
            <li
              key={message.id}
              className={
                message.role === 'user'
                  ? 'ml-auto max-w-[85%] rounded-2xl bg-primary/10 px-3 py-2 text-sm'
                  : 'max-w-[85%] rounded-2xl bg-surface px-3 py-2 text-sm'
              }
            >
              {message.role === 'assistant' ? (
                <Markdown>{message.content}</Markdown>
              ) : (
                <p>{message.content}</p>
              )}
              {message.role === 'assistant' && message.proposedPlannedWorkoutId ? (
                <div className="mt-2">
                  <Button
                    type="button"
                    size="sm"
                    variant="subtle"
                    disabled={proposeMutation.isPending}
                    onClick={() => proposeMutation.mutate(message.proposedPlannedWorkoutId as string)}
                  >
                    Propose this adjustment
                  </Button>
                </div>
              ) : null}
            </li>
          ))}
        </ol>
      ) : null}

      <form onSubmit={handleSubmit} className="space-y-2">
        <Textarea
          aria-label="Ask a follow-up question"
          placeholder="Ask a follow-up — why, what if, should I…"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          maxLength={MAX_QUESTION_LENGTH}
          className="min-h-[64px]"
          disabled={askMutation.isPending}
        />
        <div className="flex justify-end">
          <Button type="submit" size="sm" disabled={askMutation.isPending || !question.trim()}>
            <Send className="mr-2 h-4 w-4" aria-hidden />
            Ask
          </Button>
        </div>
      </form>
    </div>
  );
}
