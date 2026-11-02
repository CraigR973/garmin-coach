import { Link } from 'react-router-dom';
import { TriangleAlert } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { BRIEF_NO_DATA_NO_CALL_LINE, BRIEF_NO_DATA_TITLE, briefWaitsForData } from '@/lib/copy';
import { cn } from '@/lib/utils';

/**
 * Batch 141: Home's hero slot when today's brief generation failed. Replaces the
 * {@link BriefGeneratingCta} "Writing your brief" spinner so a failed generation
 * is an honest, retryable state — the 2026-07-21 Anthropic credit outage froze
 * this slot too. "Try again" links to check-in, where the retry re-triggers
 * generation (the check-in PUT is the app's only generate trigger).
 */
export function BriefFailedCta({ dateLabel, reason = null }: { dateLabel?: string; reason?: string | null }) {
  // Batch 364 (UX362-01): last night's data has not arrived, which is not a writing fault.
  const noData = briefWaitsForData(reason);
  return (
    <section
      className={cn(
        'relative overflow-hidden rounded-2xl border border-warning/40 bg-surface-elevated px-5 py-5 shadow-md',
      )}
      aria-label="Brief generation failed"
    >
      <div className="relative flex items-center gap-4">
        <div className="grid h-20 w-20 shrink-0 place-items-center rounded-full bg-warning/15">
          <TriangleAlert className="h-8 w-8 text-warning" aria-hidden />
        </div>
        <div className="min-w-0 flex-1">
          {dateLabel && (
            <p className="font-mono text-2xs uppercase tracking-[0.25em] text-text-muted">
              {dateLabel}
            </p>
          )}
          <p className="mt-1 text-2xl font-semibold tracking-tight text-text-primary">
            {noData ? BRIEF_NO_DATA_TITLE : <>Couldn&apos;t finish your brief</>}
          </p>
          <p className="mt-0.5 text-sm text-text-secondary">
            {noData ? (
              BRIEF_NO_DATA_NO_CALL_LINE
            ) : (
              <>Something went wrong while writing today&apos;s brief. Your check-in is saved.</>
            )}
          </p>
          <div className="mt-3">
            <Button asChild size="sm">
              <Link to="/check-in">Try again</Link>
            </Button>
          </div>
        </div>
      </div>
    </section>
  );
}
