import { Link } from 'react-router-dom';
import { Sun } from 'lucide-react';
import { Logomark } from '@/components/Brand';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

/**
 * Batch 85: the Home hero slot before today's brief has been generated. The morning
 * now waits for Mark to "say good morning" and checking in generates the brief
 * off-request. Batch 222 makes the sync state explicit: the wake job usually has
 * the inputs ready, but the copy must not claim that when the payload proves otherwise.
 */
export function GoodMorningCta({
  dateLabel,
  overnightDataReady,
}: {
  dateLabel?: string;
  overnightDataReady: boolean;
}) {
  return (
    <section
      className={cn(
        'relative overflow-hidden rounded-2xl border border-border-strong bg-surface-elevated px-5 py-5 shadow-md',
        'bg-[radial-gradient(circle_at_20%_10%,rgba(255,255,255,0.08),transparent_34%)]',
      )}
      aria-label="Say good morning"
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
            <Sun className="h-5 w-5 shrink-0 text-warning" aria-hidden />
            <span>Say good morning</span>
          </p>
          <p className="mt-0.5 text-sm text-text-secondary">
            {overnightDataReady
              ? "Check in and I'll read your day — your overnight data's already in."
              : "Check in and I'll sync your overnight data before I read your day."}
          </p>
          <Button asChild size="sm" className="mt-3">
            <Link to="/check-in">Get today&apos;s brief</Link>
          </Button>
        </div>
      </div>
    </section>
  );
}
