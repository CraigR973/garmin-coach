import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { MessageCircle, Send } from 'lucide-react';
import { toast } from 'sonner';
import type { BriefMessage } from '@coach/shared';
import { apiFetch } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Markdown } from '@/components/Markdown';

/**
 * The conversation itself — messages, composer, and the confirm-before-apply
 * propose button (Batch 179.4).
 *
 * Extracted from `BriefFollowUpChat` so the inline chat on a read and the
 * app-wide coach sheet are literally the same conversation UI over the same
 * thread; only the view differs (one read's turns vs the rolling thread).
 *
 * A `proposedPlannedWorkoutId` on an assistant turn is decided server-side by a
 * deterministic check on Mark's own question plus today's real plan state — the
 * model never triggers it, and the button calls the *existing* workout-delivery
 * propose endpoint, so Decision #29's propose→approve→push gate is unchanged.
 */

const MAX_QUESTION_LENGTH = 1000;

export interface CoachConversationProps {
  messages: BriefMessage[];
  heading: string;
  placeholder: string;
  /** Accessible name for the composer — each surface says what it is asking about. */
  inputLabel: string;
  emptyHint?: string;
  pending: boolean;
  onAsk: (question: string) => void;
  /** Rendered in a scrolling pane when the thread can grow unbounded. */
  scrollMessages?: boolean;
}

export function CoachConversation({
  messages,
  heading,
  placeholder,
  inputLabel,
  emptyHint,
  pending,
  onAsk,
  scrollMessages = false,
}: CoachConversationProps) {
  const queryClient = useQueryClient();
  const [question, setQuestion] = useState('');

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
    if (!trimmed || pending) return;
    onAsk(trimmed);
    setQuestion('');
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-sm font-medium text-text-secondary">
        <MessageCircle className="h-4 w-4" aria-hidden />
        {heading}
      </div>

      {messages.length > 0 ? (
        <ol
          className={
            scrollMessages
              ? 'space-y-3 max-h-[46vh] overflow-y-auto pr-1'
              : 'space-y-3'
          }
          aria-label="Coach conversation"
        >
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
                    onClick={() =>
                      proposeMutation.mutate(message.proposedPlannedWorkoutId as string)
                    }
                  >
                    Propose this adjustment
                  </Button>
                </div>
              ) : null}
            </li>
          ))}
        </ol>
      ) : emptyHint ? (
        <p className="text-sm text-text-muted">{emptyHint}</p>
      ) : null}

      <form onSubmit={handleSubmit} className="space-y-2">
        <Textarea
          aria-label={inputLabel}
          placeholder={placeholder}
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          maxLength={MAX_QUESTION_LENGTH}
          className="min-h-[64px]"
          disabled={pending}
        />
        <div className="flex justify-end">
          <Button type="submit" size="sm" disabled={pending || !question.trim()}>
            <Send className="mr-2 h-4 w-4" aria-hidden />
            Ask
          </Button>
        </div>
      </form>
    </div>
  );
}
