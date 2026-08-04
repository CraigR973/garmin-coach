import { Fragment, useMemo, useState } from 'react';
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
  pending,
  onAsk,
  scrollMessages = false,
}: CoachConversationProps) {
  const queryClient = useQueryClient();
  const [question, setQuestion] = useState('');
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
  const presentedMessages = useMemo(() => {
    // The query surfaces already fail closed to an empty history while loading.
    // Retain that boundary if a stale/malformed cached payload reaches this
    // presentation component; it must not take down the rest of a read page.
    if (!Array.isArray(messages)) return [];
    let previousDayKey: string | null = null;
    return messages.map((message) => {
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
  }, [dateKeyFormatter, dateLabelFormatter, messages, timeFormatter]);

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
