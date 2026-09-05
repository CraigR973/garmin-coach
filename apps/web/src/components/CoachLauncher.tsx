import { useEffect, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { MessageCircle } from 'lucide-react';
import { toast } from 'sonner';
import { z } from 'zod';
import {
  briefMessageSchema,
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

const coachThreadSchema = z.object({
  data: z.array(briefMessageSchema),
  // Batch 254 (UX241-05): whether an older page exists. Optional so an older
  // API — or a cached envelope from before this shipped — still parses.
  meta: z.object({ hasMore: z.boolean().optional() }).optional(),
});

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

/**
 * A pushed review Mark has not answered yet, or null (Batch 255).
 *
 * This replaces `newestAssistant?.originKind === 'weekly_review'`, which read
 * "the newest assistant message happens to be a weekly review" as "Mark is
 * replying to the weekly review" — an inference with no affordance behind it,
 * because there is no reply control in this UI. It then beat both the screen's
 * origin and its registered read, and it could never release: the *answer* is
 * stored with `origin_kind='weekly_review'` too, so it became the newest
 * assistant message and re-armed the test that selected it. In production it
 * latched on 2026-08-23 and pinned **39 of 39 messages over twelve days** to a
 * six-day-stale review — including Mark asking about *this morning's* REM nine
 * minutes after that morning's brief was generated, and being told the nights
 * were not in front of the coach.
 *
 * Two conditions, and the pair is what makes it self-releasing. The push must be
 * the newest message in the thread, so it is genuinely unanswered; and it must
 * be a *proactive delivery* rather than a reply, which is exactly "no question
 * immediately before it" — a reply always has one. The moment Mark answers, the
 * newest turn is his answer's reply, preceded by his question, and the seed is
 * gone without anything having to expire it.
 */
function unansweredProactivePush(messages: BriefMessage[]): BriefMessage | null {
  const newest = messages[messages.length - 1];
  if (!newest || newest.role !== 'assistant' || !newest.analysisId) return null;
  if (newest.originKind !== 'weekly_review') return null;
  if (messages[messages.length - 2]?.role === 'user') return null;
  return newest;
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
    // Batch 253 (UX241-06): this was the one fetch in the app with no schema
    // guard. A 200 whose `data` is not an array made `messages.length` undefined,
    // took the falsy branch, and rendered the *empty* state — so after an API
    // change Mark's 268-message history read as deleted, with an invitation to
    // start over and no way to tell that from data loss. Parsing turns drift into
    // the honest error state Batch 193.2 already built, which could not fire
    // because nothing threw.
    queryFn: async () =>
      coachThreadSchema.parse(await apiFetch<unknown>('/api/v1/coach/messages')),
    enabled: Boolean(userId) && !launcherHidden,
  });

  // Batch 254 (UX241-05): the conversation was a fixed-size window over a growing
  // history — 276 messages stored, 60 shown, 216 unreachable and growing at about
  // four a day. Older pages accumulate here, oldest-first, in front of the window
  // the main query holds.
  const [olderMessages, setOlderMessages] = useState<BriefMessage[]>([]);
  const [loadingMore, setLoadingMore] = useState(false);
  const [reachedBeginning, setReachedBeginning] = useState(false);

  const anchoredAnalysisId = useCoachAnchor();
  const windowMessages = threadQuery.data?.data ?? [];
  const messages = [...olderMessages, ...windowMessages];
  const hasMore = !reachedBeginning && (threadQuery.data?.meta?.hasMore ?? false);

  // A new turn re-fetches the newest window; the pages Mark had already loaded
  // stay where they are, so asking a question does not undo his scroll-back.
  const loadEarlier = async () => {
    const oldest = messages[0];
    if (!oldest || loadingMore) return;
    setLoadingMore(true);
    try {
      const page = coachThreadSchema.parse(
        await apiFetch<unknown>(`/api/v1/coach/messages?before=${oldest.id}`),
      );
      setOlderMessages((current) => [...page.data, ...current]);
      if (!page.meta?.hasMore) setReachedBeginning(true);
    } catch {
      toast.error("Couldn't load your earlier messages — try again");
    } finally {
      setLoadingMore(false);
    }
  };
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
      // Batch 207: the inline per-read chats are gone, so this is the only box.
      // It still anchors to whatever read the screen is showing, so asking
      // "why?" while looking at a brief reaches the coach with that brief
      // attached — the useful half of the old anchoring, without the second
      // affordance that made a question vanish from the read it was about.
      //
      // Batch 255: an unanswered pushed review still wins the *first* question
      // after it, because its notification deep-links to `/?coach=open` and the
      // screen behind it is Home — so deferring to the screen there would answer
      // about the morning brief a man who just tapped "your weekly review is
      // ready". It wins that one question and no more.
      const seedingPush = unansweredProactivePush(messages);
      const payload = coachMessageInputSchema.parse({
        question,
        analysisId: seedingPush?.analysisId ?? anchoredAnalysisId ?? undefined,
        originKind: seedingPush ? 'weekly_review' : origin,
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
          hasMore={hasMore}
          loadingMore={loadingMore}
          onLoadMore={() => void loadEarlier()}
        />
      </Sheet>
    </>
  );
}
