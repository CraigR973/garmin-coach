import { CheckCircle2, AlertTriangle, OctagonAlert, Hourglass, type LucideIcon } from 'lucide-react';
import { verdictCopy, type Verdict } from '@/lib/copy';
import { cn } from '@/lib/utils';

/**
 * The product's heartbeat: today's Green/Amber/Red verdict, big and glanceable.
 * Replaces the small status Badge that was easy to miss in the old dashboard.
 */

interface VerdictStyle {
  Icon: LucideIcon;
  container: string;
  iconColor: string;
  label: string;
  line: string;
}

const STYLES: Record<Verdict, VerdictStyle> = {
  green: {
    Icon: CheckCircle2,
    container: 'border-success/30 bg-success/10',
    iconColor: 'text-success',
    label: verdictCopy.green.label,
    line: verdictCopy.green.line,
  },
  amber: {
    Icon: AlertTriangle,
    container: 'border-warning/30 bg-warning/10',
    iconColor: 'text-warning',
    label: verdictCopy.amber.label,
    line: verdictCopy.amber.line,
  },
  red: {
    Icon: OctagonAlert,
    container: 'border-error/30 bg-error/10',
    iconColor: 'text-error',
    label: verdictCopy.red.label,
    line: verdictCopy.red.line,
  },
};

const PENDING: VerdictStyle = {
  Icon: Hourglass,
  container: 'border-border bg-surface-elevated/60',
  iconColor: 'text-text-muted',
  label: 'Not ready yet',
  line: "Your verdict lands automatically once your overnight metrics finish syncing after you wake.",
};

interface VerdictHeroProps {
  verdict: string | null | undefined;
  dateLabel?: string;
  /** Optional override for the plain-English line (e.g. a one-line sleep summary). */
  line?: string;
}

export function VerdictHero({ verdict, dateLabel, line }: VerdictHeroProps) {
  const style =
    verdict === 'green' || verdict === 'amber' || verdict === 'red' ? STYLES[verdict] : PENDING;
  const { Icon } = style;

  return (
    <section
      className={cn('rounded-2xl border px-5 py-5 shadow-sm', style.container)}
      aria-label="Today's verdict"
    >
      <div className="flex items-center gap-4">
        <Icon className={cn('h-10 w-10 shrink-0', style.iconColor)} aria-hidden />
        <div className="min-w-0">
          {dateLabel && (
            <p className="font-mono text-[10px] uppercase tracking-[0.25em] text-text-muted">
              {dateLabel}
            </p>
          )}
          <p className={cn('text-2xl font-semibold tracking-tight', style.iconColor)}>
            {style.label}
          </p>
          <p className="mt-0.5 text-sm text-text-secondary">{line ?? style.line}</p>
        </div>
      </div>
    </section>
  );
}
