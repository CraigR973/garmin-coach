import { CheckCircle2, AlertTriangle, OctagonAlert, Hourglass, type LucideIcon } from 'lucide-react';
import { Link } from 'react-router-dom';
import { Logomark } from '@/components/Brand';
import { verdictCopy, type Verdict } from '@/lib/copy';
import { cn } from '@/lib/utils';

/**
 * The product's heartbeat: today's Green/Amber/Red verdict, big and glanceable.
 * Replaces the small status Badge that was easy to miss in the old dashboard.
 */

interface VerdictStyle {
  Icon: LucideIcon;
  container: string;
  ring: string;
  glow: string;
  tone: string;
  eyebrow: string;
  label: string;
  line: string;
}

const STYLES: Record<Verdict, VerdictStyle> = {
  green: {
    Icon: CheckCircle2,
    container: 'border-success/35 bg-success/10 shadow-md',
    ring: 'from-success via-steele-mid to-success',
    glow: 'bg-success/20',
    tone: 'text-success',
    eyebrow: 'Green verdict',
    label: verdictCopy.green.label,
    line: verdictCopy.green.line,
  },
  amber: {
    Icon: AlertTriangle,
    container: 'border-warning/35 bg-warning/10 shadow-md',
    ring: 'from-warning via-steele-mid to-success',
    glow: 'bg-warning/20',
    tone: 'text-warning',
    eyebrow: 'Amber verdict',
    label: verdictCopy.amber.label,
    line: verdictCopy.amber.line,
  },
  red: {
    Icon: OctagonAlert,
    container: 'border-error/35 bg-error/10 shadow-md',
    ring: 'from-error via-warning to-steele-mid',
    glow: 'bg-error/20',
    tone: 'text-error',
    eyebrow: 'Red verdict',
    label: verdictCopy.red.label,
    line: verdictCopy.red.line,
  },
};

const PENDING: VerdictStyle = {
  Icon: Hourglass,
  container: 'border-border-strong bg-surface-elevated shadow-md',
  ring: 'from-border-strong via-steele-mid to-border-strong',
  glow: 'bg-surface-overlay/70',
  tone: 'text-text-secondary',
  eyebrow: 'Verdict pending',
  label: 'Not ready yet',
  line: "Your verdict lands automatically once your overnight metrics finish syncing after you wake.",
};

interface VerdictHeroProps {
  verdict: string | null | undefined;
  dateLabel?: string;
  /** Optional override for the plain-English line (e.g. a one-line sleep summary). */
  line?: string;
  recap?: {
    title: string;
    text: string;
    ctaLabel?: string;
    ctaTo?: string;
  } | null;
}

export function VerdictHero({ verdict, dateLabel, line, recap = null }: VerdictHeroProps) {
  const style =
    verdict === 'green' || verdict === 'amber' || verdict === 'red' ? STYLES[verdict] : PENDING;
  const { Icon } = style;

  return (
    <section
      className={cn(
        'relative overflow-hidden rounded-2xl border px-5 py-5',
        'bg-[radial-gradient(circle_at_20%_10%,rgba(255,255,255,0.08),transparent_34%)]',
        style.container,
      )}
      aria-label="Today's verdict"
    >
      <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-steele-mid/40 to-transparent" />
      <div className="relative flex items-center gap-4">
        <div
          data-testid="verdict-mark-ring"
          className={cn(
            'relative grid h-20 w-20 shrink-0 place-items-center rounded-full bg-gradient-to-br p-[3px]',
            style.ring,
          )}
        >
          <div className={cn('absolute inset-0 rounded-full blur-xl', style.glow)} />
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
          <p className={cn('mt-1 inline-flex items-center gap-2 text-2xl font-semibold tracking-tight', style.tone)}>
            <Icon className="h-5 w-5 shrink-0" aria-hidden />
            <span>{style.label}</span>
          </p>
          <p className="mt-0.5 text-sm text-text-secondary">{line ?? style.line}</p>
          {recap ? (
            <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl border border-white/10 bg-bg/45 px-3 py-2">
              <div className="min-w-0 flex-1">
                <p className="text-[11px] font-medium uppercase tracking-[0.12em] text-text-muted">
                  {recap.title}
                </p>
                <p className="text-sm text-text-primary">{recap.text}</p>
              </div>
              {recap.ctaLabel && recap.ctaTo ? (
                <Link
                  to={recap.ctaTo}
                  className="text-sm font-medium text-primary underline-offset-4 hover:underline"
                >
                  {recap.ctaLabel}
                </Link>
              ) : null}
            </div>
          ) : null}
          <p className="mt-3 inline-flex rounded-full border border-border bg-surface/60 px-2.5 py-1 text-[11px] font-medium text-text-secondary">
            {style.eyebrow}
          </p>
        </div>
      </div>
    </section>
  );
}
