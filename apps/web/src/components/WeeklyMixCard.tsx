import { Target } from 'lucide-react';
import type { WeeklyMix } from '@coach/shared';
import { cn } from '@/lib/utils';

/** Batch 70 (#143): the week's protected quality mix (VO2 / Sweet-Spot / Zone-2)
 *  as done/target chips — at-risk buckets flagged amber, met buckets green. When
 *  a cautious morning eases today's hard session, the eased bucket shows where it
 *  re-patches to (e.g. "→ Sat"); `showShortfall` additionally renders the coach's
 *  full note (used on the Plan page, where the verdict text isn't shown). */
export function WeeklyMixCard({
  mix,
  showShortfall = false,
  className,
}: {
  mix: WeeklyMix;
  showShortfall?: boolean;
  className?: string;
}) {
  const buckets = mix.buckets ?? [];
  if (buckets.length === 0) return null;
  const shortfall = mix.shortfall ?? null;

  return (
    <div className={cn('rounded-xl border border-border bg-surface px-3 py-3 text-sm', className)}>
      <p className="mb-2 flex items-center gap-1.5 font-medium text-text-primary">
        <Target className="h-4 w-4 text-primary" aria-hidden />
        This week&apos;s mix
      </p>
      <div className="flex flex-wrap gap-2">
        {buckets.map((bucket) => {
          const met = bucket.done >= bucket.target && bucket.target > 0;
          const repatchTo =
            shortfall && shortfall.bucket === bucket.bucket && shortfall.repatched
              ? shortfall.moveToWeekday
              : null;
          return (
            <span
              key={bucket.bucket}
              className={cn(
                'inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-medium',
                bucket.atRisk
                  ? 'border-warning/40 bg-warning/10 text-warning'
                  : met
                    ? 'border-success/30 bg-success/10 text-success'
                    : 'border-border text-text-secondary',
              )}
            >
              {bucket.label} {bucket.done}/{bucket.target}
              {repatchTo ? <span className="opacity-80">→ {repatchTo.slice(0, 3)}</span> : null}
            </span>
          );
        })}
      </div>
      {showShortfall && shortfall ? (
        <p className="mt-2 text-xs text-text-secondary">{shortfall.message}</p>
      ) : null}
    </div>
  );
}
