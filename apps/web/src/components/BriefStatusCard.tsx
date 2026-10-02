import { Loader2, TriangleAlert } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  BRIEF_RETRY_LABEL,
  BRIEF_UNWRITTEN_LINE,
  BRIEF_UNWRITTEN_TITLE,
  BRIEF_WRITING_LINE,
  BRIEF_WRITING_TITLE,
  NOTE_UNREAD_LINE,
} from '@/lib/copy';
import { cn } from '@/lib/utils';

interface BriefStatusCardProps {
  /** The morning is stored; its brief is being written, or did not finish. */
  state: 'writing' | 'failed';
  /** His note was not read, so the colour above was graded without it. */
  noteUnread?: boolean;
  /** Absent on a day that is over: only today's brief can be tried again. */
  onRetry?: () => void;
  retrying?: boolean;
}

/**
 * Batch 302: the slot under the colour for a morning whose brief is not written.
 *
 * Until this batch a morning with no brief had no colour either, so `BriefGeneratingCta`
 * and `BriefFailedCta` stood in the hero's place. The colour, the notices and the plan
 * are stored first now and show above this card; it says only where the written brief
 * is, and offers to try again. Those two components still stand in for a morning that
 * could not be graded at all.
 */
export function BriefStatusCard({ state, noteUnread = false, onRetry, retrying = false }: BriefStatusCardProps) {
  const failed = state === 'failed';
  return (
    <section
      className={cn(
        'flex items-start gap-3 rounded-2xl border bg-surface-elevated px-4 py-3 shadow-sm',
        failed ? 'border-warning/40' : 'border-border-strong',
      )}
      aria-label={failed ? 'Written brief did not finish' : 'Writing your brief'}
      role="status"
    >
      {failed ? (
        <TriangleAlert className="mt-0.5 h-5 w-5 shrink-0 text-warning" aria-hidden />
      ) : (
        <Loader2 className="mt-0.5 h-5 w-5 shrink-0 animate-spin text-warning" aria-hidden />
      )}
      <div className="min-w-0 flex-1 space-y-1">
        <p className="font-medium text-text-primary">
          {failed ? BRIEF_UNWRITTEN_TITLE : BRIEF_WRITING_TITLE}
        </p>
        <p className="text-sm text-text-secondary">
          {failed ? BRIEF_UNWRITTEN_LINE : BRIEF_WRITING_LINE}
        </p>
        {noteUnread ? <p className="text-sm text-text-secondary">{NOTE_UNREAD_LINE}</p> : null}
        {failed && onRetry ? (
          <div className="pt-2">
            <Button type="button" size="sm" onClick={onRetry} disabled={retrying}>
              {BRIEF_RETRY_LABEL}
            </Button>
          </div>
        ) : null}
      </div>
    </section>
  );
}
