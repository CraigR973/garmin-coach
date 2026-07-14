import { Loader2 } from 'lucide-react';
import { Logomark } from '@/components/Brand';
import { cn } from '@/lib/utils';

/**
 * Batch 114: the Home hero slot for the async window between a submitted
 * check-in and the brief landing (Batch 97's background generation). Once
 * `manualEntry` exists, he's already said good morning — this replaces
 * `GoodMorningCta` so Home doesn't keep inviting a check-in that's done.
 */
export function BriefGeneratingCta({ dateLabel }: { dateLabel?: string }) {
  return (
    <section
      className={cn(
        'relative overflow-hidden rounded-2xl border border-border-strong bg-surface-elevated px-5 py-5 shadow-md',
        'bg-[radial-gradient(circle_at_20%_10%,rgba(255,255,255,0.08),transparent_34%)]',
      )}
      aria-label="Generating your brief"
    >
      <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-steele-mid/40 to-transparent" />
      <div className="relative flex items-center gap-4">
        <div className="relative grid h-20 w-20 shrink-0 place-items-center rounded-full bg-gradient-to-br from-warning via-steele-mid to-success p-[3px]">
          <div className="absolute inset-0 rounded-full bg-warning/20 blur-xl" />
          <div className="relative grid h-full w-full place-items-center rounded-full border border-white/10 bg-bg/85 shadow-sm">
            <Logomark size={48} decorative className="shadow-none" />
          </div>
        </div>
        <div className="min-w-0 flex-1">
          {dateLabel && (
            <p className="font-mono text-[10px] uppercase tracking-[0.25em] text-text-muted">
              {dateLabel}
            </p>
          )}
          <p className="mt-1 inline-flex items-center gap-2 text-2xl font-semibold tracking-tight text-text-primary">
            <Loader2 className="h-5 w-5 shrink-0 animate-spin text-warning" aria-hidden />
            <span>Writing your brief</span>
          </p>
          <p className="mt-0.5 text-sm text-text-secondary">
            You&apos;re checked in — I&apos;m reading today&apos;s data now, this lands in a moment.
          </p>
        </div>
      </div>
    </section>
  );
}
