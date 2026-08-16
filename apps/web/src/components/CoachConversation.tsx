import { Fragment, useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { MessageCircle, Send } from 'lucide-react';
import { toast } from 'sonner';
import type { BriefMessage } from '@coach/shared';
import { apiFetch } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Markdown } from '@/components/Markdown';

/** Three distinct presentations for the thread fetch — Batch 193.3 / UX192-03:
 * a failed fetch previously fell through the same "nothing here" copy an
 * empty-but-healthy thread uses, so 82 real messages read as deleted. */
export type CoachConversationStatus = 'loading' | 'error' | 'ready';

/**
 * The conversation itself — messages, composer, and the confirm-before-apply
 * propose button (Batch 179.4).
 *
 * Originally extracted so the inline per-read chat and the app-wide sheet could
 * share one transcript. Batch 207 retired the inline views entirely — there is
 * one coach and one thread now — so this renders the launcher's sheet alone.
 *
 * A `proposedPlannedWorkoutId` on an assistant turn is decided server-side by a
 * deterministic check on Mark's own question plus today's real plan state — the
 * model never triggers it, and the button calls the *existing* workout-delivery
 * propose endpoint, so Decision #29's propose→approve→push gate is unchanged.
 */

const MAX_QUESTION_LENGTH = 1000;

function localDateKey(formatter: Intl.DateTimeFormat, date: Date): string {
  const parts = Object.fromEntries(
    formatter
      .formatToParts(date)
      .filter((part) => part.type === 'year' || part.type === 'month' || part.type === 'day')
      .map((part) => [part.type, part.value]),
  );
  return `${parts.year}-${parts.month}-${parts.day}`;
}

export interface CoachConversationProps {
  messages: BriefMessage[];
  /** IANA timezone from the authenticated profile. */
  timeZone?: string;
  heading: string;
  placeholder: string;
  /** Accessible name for the composer — each surface says what it is asking about. */
  inputLabel: string;
  emptyHint?: string;
  /** Defaults to `'ready'` — the inline per-read chat has no separate fetch to fail against. */
  status?: CoachConversationStatus;
  /** Shown next to the error copy when `status === 'error'`. */
  onRetry?: () => void;
  pending: boolean;
  onAsk: (question: string) => void;
  /** Rendered in a scrolling pane when the thread can grow unbounded. */
  scrollMessages?: boolean;
}

export function CoachConversation({
  messages,
  timeZone,
  heading,
  placeholder,
  inputLabel,
  emptyHint,
  status = 'ready',
  onRetry,
  pending,
  onAsk,
  scrollMessages = false,
}: CoachConversationProps) {
  const queryClient = useQueryClient();
  const [question, setQuestion] = useState('');
  // The turn Mark just sent, shown immediately rather than waiting for the
  // round trip and thread-invalidation to bring it back (Batch 193.5 /
  // UX192-06) — cleared as soon as `pending` drops, whether that is success
  // (the real turns replace it) or failure (the toast covers it).
  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null);
  const scrollRef = useRef<HTMLOListElement>(null);

  useEffect(() => {
    if (!pending) setPendingQuestion(null);
  }, [pending]);
  const dateKeyFormatter = useMemo(
    () =>
      new Intl.DateTimeFormat('en-GB', {
        timeZone: timeZone || undefined,
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
      }),
    [timeZone],
  );
  const dateLabelFormatter = useMemo(
    () =>
      new Intl.DateTimeFormat('en-GB', {
        timeZone: timeZone || undefined,
        weekday: 'long',
        year: 'numeric',
        month: 'long',
        day: 'numeric',
      }),
    [timeZone],
  );
  const timeFormatter = useMemo(
    () =>
      new Intl.DateTimeFormat('en-GB', {
        timeZone: timeZone || undefined,
        hour: '2-digit',
        minute: '2-digit',
        hourCycle: 'h23',
      }),
    [timeZone],
  );
  // Typing in the composer updates local state on every keystroke. Keep the
  // timezone work out of that hot path, especially for the unbounded rolling
  // thread in the app-wide launcher.
  const sourceMessages = useMemo(() => {
    // The query surfaces already fail closed to an empty history while loading.
    // Retain that boundary if a stale/malformed cached payload reaches this
    // presentation component; it must not take down the rest of a read page.
    if (!Array.isArray(messages)) return [];
    if (!pendingQuestion) return messages;
    const optimisticTurn: BriefMessage = {
      id: 'optimistic-pending-turn',
      analysisId: null,
      originKind: null,
      originDate: null,
      role: 'user',
      content: pendingQuestion,
      proposedPlannedWorkoutId: null,
      createdAtUtc: new Date().toISOString(),
    };
    return [...messages, optimisticTurn];
  }, [messages, pendingQuestion]);

  const presentedMessages = useMemo(() => {
    let previousDayKey: string | null = null;
    return sourceMessages.map((message) => {
      const sentAt = new Date(message.createdAtUtc);
      const dayKey = localDateKey(dateKeyFormatter, sentAt);
      const presentation = {
        message,
        dayKey,
        dayLabel: dateLabelFormatter.format(sentAt),
        timeLabel: timeFormatter.format(sentAt),
        startsDay: dayKey !== previousDayKey,
      };
      previousDayKey = dayKey;
      return presentation;
    });
  }, [dateKeyFormatter, dateLabelFormatter, sourceMessages, timeFormatter]);

  // Scroll the newest turn into view on open and after every reply (Batch
  // 193.2 / UX192-02) — the pane previously opened at `scrollTop: 0`, so the
  // one place a proactive message lands was also the one place never on
  // screen. Only the unbounded rolling thread scrolls internally; the inline
  // per-read chat is short enough to live in the page's own scroll.
  useEffect(() => {
    if (!scrollMessages) return;
    const node = scrollRef.current;
    if (!node) return;
    node.scrollTop = node.scrollHeight;
  }, [scrollMessages, presentedMessages.length, pending]);

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
    setPendingQuestion(trimmed);
    onAsk(trimmed);
    setQuestion('');
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-sm font-medium text-text-secondary">
        <MessageCircle className="h-4 w-4" aria-hidden />
        {heading}
      </div>

      {status === 'loading' ? (
        <p className="text-sm text-text-muted" role="status">
          Loading your conversation…
        </p>
      ) : status === 'error' ? (
        <div className="space-y-2" role="alert">
          <p className="text-sm text-error-text">
            Could not load your conversation. Your past messages are still there.
          </p>
          {onRetry ? (
            <Button type="button" size="sm" variant="subtle" onClick={onRetry}>
              Try again
            </Button>
          ) : null}
        </div>
      ) : presentedMessages.length > 0 ? (
        <ol
          ref={scrollRef}
          className={
            scrollMessages
              ? 'space-y-3 max-h-[46vh] overflow-y-auto pr-1'
              : 'space-y-3'
          }
          aria-label="Coach conversation"
        >
          {presentedMessages.map(({ message, dayKey, dayLabel, timeLabel, startsDay }) => {
            return (
              <Fragment key={message.id}>
                {startsDay ? (
                  <li
                    role="separator"
                    aria-label={dayLabel}
                    className="flex items-center gap-3 py-1 text-xs text-text-muted"
                  >
                    <span className="h-px flex-1 bg-border" aria-hidden />
                    <time dateTime={dayKey}>{dayLabel}</time>
                    <span className="h-px flex-1 bg-border" aria-hidden />
                  </li>
                ) : null}
                <li
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
                  <time
                    dateTime={message.createdAtUtc}
                    aria-label={`Sent ${dayLabel} at ${timeLabel}`}
                    className={
                      message.role === 'user'
                        ? 'mt-1 block text-right text-[11px] text-text-muted'
                        : 'mt-1 block text-[11px] text-text-muted'
                    }
                  >
                    {timeLabel}
                  </time>
                </li>
              </Fragment>
            );
          })}
          {pending ? (
            <li
              aria-live="polite"
              aria-label="Your coach is thinking"
              className="max-w-[85%] rounded-2xl bg-surface px-3 py-2 text-sm"
            >
              <span className="inline-flex items-center gap-1" aria-hidden>
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-text-muted [animation-delay:-0.3s]" />
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-text-muted [animation-delay:-0.15s]" />
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-text-muted" />
              </span>
            </li>
          ) : null}
        </ol>
      ) : emptyHint ? (
        <p className="text-sm text-text-muted">{emptyHint}</p>
      ) : (
        <p className="text-sm text-text-muted">Nothing here yet. Ask whatever&apos;s on your mind.</p>
      )}

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
