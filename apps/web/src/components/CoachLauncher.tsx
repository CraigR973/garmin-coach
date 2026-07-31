import { useEffect, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { MessageCircle } from 'lucide-react';
import { toast } from 'sonner';
import {
  coachMessageInputSchema,
  type BriefMessage,
  type BriefMessageTurn,
} from '@coach/shared';
import { apiFetch } from '@/lib/api';
import { Sheet } from '@/components/ui/sheet';
import { CoachConversation } from '@/components/CoachConversation';
import { ORIGIN_PROMPTS, originForPath } from '@/lib/coachOrigin';
import { cn } from '@/lib/utils';

/**
 * The coach, reachable from anywhere (Batch 179.4).
 *
 * Before this, a conversation could only exist where a generated read existed —
 * so there was no way to just ask a question, and the pages with no `analyses`
 * row of their own (Sleep, the breathwork/strength/walking briefs) could not
 * host one at all. This is one rolling thread: opening it from a page seeds the
 * subject ("we're talking about last night's sleep") without fencing it, and
 * the conversation survives a read rolling over because it was never tied to
 * one.
 */

const ROUTES_WITHOUT_LAUNCHER = ['/access', '/activate', '/offline'];

export function CoachLauncher() {
  const { pathname } = useLocation();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const origin = originForPath(pathname);

  // Close on navigation — same behaviour as the More sheet in the tab bar.
  useEffect(() => {
    setOpen(false);
  }, [pathname]);

  const threadQuery = useQuery({
    queryKey: ['coach-thread'],
    queryFn: () => apiFetch<{ data: BriefMessage[] }>('/api/v1/coach/messages'),
    enabled: open,
  });

  const askMutation = useMutation({
    mutationFn: async (question: string) => {
      const payload = coachMessageInputSchema.parse({ question, originKind: origin });
      return apiFetch<{ data: BriefMessageTurn }>('/api/v1/coach/messages', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['coach-thread'] });
      queryClient.invalidateQueries({ queryKey: ['brief-messages'] });
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : 'Could not send that question'),
  });

  if (ROUTES_WITHOUT_LAUNCHER.some((route) => pathname.startsWith(route))) return null;

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label={ORIGIN_PROMPTS[origin]}
        className={cn(
          'fixed right-4 z-tabbar tap-target',
          'bottom-[calc(60px+env(safe-area-inset-bottom)+1rem)] md:bottom-6',
          'inline-flex items-center justify-center h-12 w-12 rounded-full',
          'bg-primary text-white shadow-sheet press-down',
          'focus-visible:outline-none focus-visible:shadow-glow',
        )}
      >
        <MessageCircle className="h-5 w-5" aria-hidden />
      </button>

      <Sheet open={open} onClose={() => setOpen(false)} title="Your coach">
        <CoachConversation
          messages={threadQuery.data?.data ?? []}
          heading={ORIGIN_PROMPTS[origin]}
          placeholder="Ask anything — your plan, your sleep, how a session went…"
          inputLabel="Ask your coach a question"
          emptyHint={
            threadQuery.isLoading
              ? 'Loading your conversation…'
              : "Nothing here yet. Ask whatever's on your mind."
          }
          pending={askMutation.isPending}
          onAsk={(question) => askMutation.mutate(question)}
          scrollMessages
        />
      </Sheet>
    </>
  );
}
