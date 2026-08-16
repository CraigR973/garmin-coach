import { useEffect, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { MessageCircle } from 'lucide-react';
import { toast } from 'sonner';
import {
  coachMessageInputSchema,
  PROACTIVE_COACH_ORIGIN_KINDS,
  type BriefMessage,
  type BriefMessageTurn,
} from '@coach/shared';
import { useCoachAnchor } from '@/contexts/CoachAnchorContext';
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
const LAST_SEEN_ASSISTANT_KEY_VERSION = 'v1';

function lastSeenAssistantKey(userId: string): string {
  return `coach:last-seen-assistant:${LAST_SEEN_ASSISTANT_KEY_VERSION}:${userId}`;
}

function readLastSeenAssistant(userId: string | undefined): string | null {
  if (!userId || typeof window === 'undefined') return null;
  return window.localStorage.getItem(lastSeenAssistantKey(userId));
}

function latestAssistant(messages: BriefMessage[]): BriefMessage | null {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (messages[index]?.role === 'assistant') return messages[index] ?? null;
  }
  return null;
}

export function CoachLauncher({ userId, timeZone }: { userId?: string; timeZone?: string }) {
  const { pathname, search } = useLocation();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [lastSeenAssistantId, setLastSeenAssistantId] = useState<string | null>(() =>
    readLastSeenAssistant(userId),
  );
  const origin = originForPath(pathname);
  const launcherHidden = ROUTES_WITHOUT_LAUNCHER.some((route) => pathname.startsWith(route));
  const deepLinkedOpen = new URLSearchParams(search).get('coach') === 'open';

  // Close on navigation — same behaviour as the More sheet in the tab bar.
  useEffect(() => {
    setOpen(false);
  }, [pathname]);

  useEffect(() => {
    setLastSeenAssistantId(readLastSeenAssistant(userId));
  }, [userId]);

  useEffect(() => {
    if (deepLinkedOpen) setOpen(true);
  }, [deepLinkedOpen]);

  const threadQuery = useQuery({
    queryKey: ['coach-thread'],
    queryFn: () => apiFetch<{ data: BriefMessage[] }>('/api/v1/coach/messages'),
    enabled: Boolean(userId) && !launcherHidden,
  });

  const anchoredAnalysisId = useCoachAnchor();
  const messages = threadQuery.data?.data ?? [];
  const newestAssistant = latestAssistant(messages);
  const hasUnreadAssistant = Boolean(
    newestAssistant &&
      (PROACTIVE_COACH_ORIGIN_KINDS as readonly string[]).includes(newestAssistant.originKind ?? '') &&
      newestAssistant.id !== lastSeenAssistantId,
  );

  useEffect(() => {
    if (!open || !userId || !newestAssistant) return;
    const key = lastSeenAssistantKey(userId);
    window.localStorage.setItem(key, newestAssistant.id);
    setLastSeenAssistantId(newestAssistant.id);
  }, [newestAssistant, open, userId]);

  const askMutation = useMutation({
    mutationFn: async (question: string) => {
      const replyingToWeeklyReview =
        newestAssistant?.originKind === 'weekly_review' && newestAssistant.analysisId
          ? newestAssistant
          : null;
      // Batch 207: the inline per-read chats are gone, so this is the only box.
      // It still anchors to whatever read the screen is showing, so asking
      // "why?" while looking at a brief reaches the coach with that brief
      // attached — the useful half of the old anchoring, without the second
      // affordance that made a question vanish from the read it was about.
      // Replying to a weekly review still wins, because that reply is
      // explicitly to a message rather than to the page behind it.
      const payload = coachMessageInputSchema.parse({
        question,
        analysisId: replyingToWeeklyReview?.analysisId ?? anchoredAnalysisId ?? undefined,
        originKind: replyingToWeeklyReview ? 'weekly_review' : origin,
      });
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

  if (launcherHidden) return null;

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label={
          hasUnreadAssistant ? `${ORIGIN_PROMPTS[origin]} — new coach message` : ORIGIN_PROMPTS[origin]
        }
        className={cn(
          'fixed right-4 z-tabbar tap-target',
          'bottom-[calc(60px+env(safe-area-inset-bottom)+1rem)] md:bottom-6',
          'inline-flex items-center justify-center h-12 w-12 rounded-full',
          'bg-primary text-white shadow-sheet press-down',
          'focus-visible:outline-none focus-visible:shadow-glow',
        )}
      >
        <MessageCircle className="h-5 w-5" aria-hidden />
        {hasUnreadAssistant ? (
          <span
            className="absolute right-0 top-0 h-3 w-3 rounded-full border-2 border-white bg-danger"
            aria-hidden
          />
        ) : null}
      </button>

      <Sheet open={open} onClose={() => setOpen(false)} title="Your coach">
        <CoachConversation
          messages={messages}
          timeZone={timeZone}
          heading={ORIGIN_PROMPTS[origin]}
          placeholder="Ask anything — your plan, your sleep, how a session went…"
          inputLabel="Ask your coach a question"
          status={threadQuery.isLoading ? 'loading' : threadQuery.isError ? 'error' : 'ready'}
          onRetry={() => threadQuery.refetch()}
          pending={askMutation.isPending}
          onAsk={(question) => askMutation.mutate(question)}
          scrollMessages
        />
      </Sheet>
    </>
  );
}
