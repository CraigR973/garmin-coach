import { useState } from 'react';
import type { PointsBreakdown } from '../lib/types';

interface Props {
  breakdown: PointsBreakdown | null | undefined;
  children: React.ReactNode;
}

/**
 * Wraps any trigger element. On tap, reveals a one-line breakdown below it.
 * Renders children as-is when no breakdown is available or no_prediction is true.
 */
export function PointsBreakdownPopover({ breakdown, children }: Props) {
  const [open, setOpen] = useState(false);
  const hasBreakdown = breakdown != null && !breakdown.no_prediction;

  if (!hasBreakdown) return <>{children}</>;

  const parts: string[] = [];
  if (breakdown.goals > 0) parts.push(`Goals ${breakdown.goals}`);
  if (breakdown.result > 0) parts.push(`Result ${breakdown.result}`);
  if (breakdown.exact > 0) parts.push(`Exact ${breakdown.exact}`);
  const detail = parts.length > 0 ? parts.join(' · ') : '—';

  return (
    <div className="inline-flex flex-col items-end gap-0.5">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="focus:outline-none"
        aria-expanded={open}
        aria-label={`${breakdown.total} pts — tap for breakdown`}
        data-testid="breakdown-trigger"
      >
        {children}
      </button>
      {open && (
        <span
          className="text-[10px] font-mono text-text-muted whitespace-nowrap"
          data-testid="breakdown-detail"
        >
          {detail}
        </span>
      )}
    </div>
  );
}
