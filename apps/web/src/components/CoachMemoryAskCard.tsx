import { Link } from 'react-router-dom';
import { Brain } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useConversationLearning, useReviewMemory } from '@/hooks/useCoachMemory';
import {
  MEMORY_ASK_LEFT_OUT,
  MEMORY_ASK_LIMIT,
  MEMORY_ASK_NO,
  MEMORY_ASK_REMEMBERED,
  MEMORY_ASK_SEE_ALL,
  MEMORY_ASK_TITLE,
  MEMORY_ASK_YES,
  memoryMoreLine,
  memorySaidLine,
} from '@/lib/coachMemory';
import { friendlyError } from '@/lib/friendlyError';

/** Batch 346: what the coach proposed overnight, answered in one tap on Home.
 *
 *  Only memories ask here; a proposed experiment stays on Coach memory, where its
 *  comparison is explained. Nothing shows when nothing is waiting or the list fails
 *  to load: Home never tells him memory is broken. */
export function CoachMemoryAskCard() {
  const learning = useConversationLearning();
  const review = useReviewMemory({
    onSuccess: (decision) => toast.success(decision === 'accept' ? MEMORY_ASK_REMEMBERED : MEMORY_ASK_LEFT_OUT),
  });
  const waiting = (learning.data?.data.proposals ?? []).filter(
    (proposal) => proposal.status === 'pending' && proposal.destination === 'learned_context',
  );
  if (!waiting.length) return null;
  const shown = waiting.slice(0, MEMORY_ASK_LIMIT);

  return (
    <Card aria-label={MEMORY_ASK_TITLE}>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Brain className="h-5 w-5 text-primary" aria-hidden />
          {MEMORY_ASK_TITLE}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 text-sm leading-6">
        {shown.map((proposal) => {
          const evidence = proposal.evidence[0];
          return (
            <div key={proposal.id} className="space-y-2 rounded-lg border border-border bg-bg/60 p-3">
              <p className="text-text-primary">{proposal.statement}</p>
              {evidence ? (
                <p className="text-xs text-text-secondary">{memorySaidLine(evidence.sourceDate, evidence.quote)}</p>
              ) : null}
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  size="sm"
                  disabled={review.isPending}
                  onClick={() =>
                    review.mutate(
                      { id: proposal.id, decision: 'accept' },
                      { onError: (error) => toast.error(friendlyError(error, 'save')) },
                    )
                  }
                >
                  {MEMORY_ASK_YES}
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={review.isPending}
                  onClick={() =>
                    review.mutate(
                      { id: proposal.id, decision: 'reject' },
                      { onError: (error) => toast.error(friendlyError(error, 'save')) },
                    )
                  }
                >
                  {MEMORY_ASK_NO}
                </Button>
              </div>
            </div>
          );
        })}
        {waiting.length > shown.length ? (
          <p className="text-text-secondary">{memoryMoreLine(waiting.length - shown.length)}</p>
        ) : null}
        <Link to="/coach-state" className="inline-block text-primary underline-offset-4 hover:underline">
          {MEMORY_ASK_SEE_ALL}
        </Link>
      </CardContent>
    </Card>
  );
}
