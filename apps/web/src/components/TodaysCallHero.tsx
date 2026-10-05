import {
  BatteryCharging,
  CalendarX,
  CheckCircle2,
  Gauge,
  Hourglass,
  OctagonAlert,
  type LucideIcon,
} from 'lucide-react';
import { Link } from 'react-router-dom';
import type { TodaysCall } from '@coach/shared';
import { Logomark } from '@/components/Brand';
import { NOT_READY_CALL } from '@/lib/todaysCall';
import { cn } from '@/lib/utils';

/**
 * The product's heartbeat: today's call, big and glanceable (Batch 313).
 *
 * The headline says what to do today and the chip how recovered he is (Recovered, Some
 * fatigue, Still recovering). The words are the stored morning's (`todaysCall`), picked
 * on the server by one rule, so Home, the brief page, the written brief and the coach
 * chat say the same thing. Signed off by Craig on Mark's behalf, 4 Oct 2026
 * (docs/drafts/2026-10-04-morning-call-wording.md). Red is kept for the two health
 * warnings; recovery and rest days are a calm blue.
 */

interface LookStyle {
  Icon: LucideIcon;
  container: string;
  ring: string;
  glow: string;
  tone: string;
}

const LOOKS: Record<string, LookStyle> = {
  // States 1-4: green and a tick.
  go: {
    Icon: CheckCircle2,
    container: 'border-success/35 bg-success/10 shadow-md',
    ring: 'from-success via-steele-mid to-success',
    glow: 'bg-success/20',
    tone: 'text-success-text',
  },
  // States 5-7: amber and a gauge.
  adjust: {
    Icon: Gauge,
    container: 'border-warning/35 bg-warning/10 shadow-md',
    ring: 'from-warning via-steele-mid to-success',
    glow: 'bg-warning/20',
    tone: 'text-warning-text',
  },
  // States 8-10 and 12-15: blue and a charging battery.
  recover: {
    Icon: BatteryCharging,
    container: 'border-recover/35 bg-recover/10 shadow-md',
    ring: 'from-recover via-steele-mid to-recover',
    glow: 'bg-recover/20',
    tone: 'text-recover-text',
  },
  // States 16 and 17: grey.
  neutral: {
    Icon: CalendarX,
    container: 'border-border-strong bg-surface-elevated shadow-md',
    ring: 'from-border-strong via-steele-mid to-border-strong',
    glow: 'bg-surface-overlay/70',
    tone: 'text-text-secondary',
  },
  // State 11, the two health warnings: red and the stop icon.
  warning: {
    Icon: OctagonAlert,
    container: 'border-error/35 bg-error/10 shadow-md',
    ring: 'from-error via-warning to-steele-mid',
    glow: 'bg-error/20',
    tone: 'text-error-text',
  },
};

interface TodaysCallHeroProps {
  call: TodaysCall | null | undefined;
  dateLabel?: string;
  /** Home puts "Good morning, Mark." in front of the line. */
  lead?: string;
  /** Replaces the call's line (the insufficient-data message). */
  line?: string;
  recap?: {
    title: string;
    text: string;
    ctaLabel?: string;
    ctaTo?: string;
  } | null;
}

export function TodaysCallHero({ call, dateLabel, lead, line, recap = null }: TodaysCallHeroProps) {
  const shown = call ?? NOT_READY_CALL;
  const style = LOOKS[shown.look] ?? LOOKS.neutral;
  // Grey covers two states: no session planned (a calendar) and not ready (as before).
  const Icon = shown.state === NOT_READY_CALL.state ? Hourglass : style.Icon;
  const text = line ?? shown.line;

  return (
    <section
      className={cn(
        'relative overflow-hidden rounded-2xl border px-5 py-5',
        'bg-[radial-gradient(circle_at_20%_10%,rgba(255,255,255,0.08),transparent_34%)]',
        style.container,
      )}
      aria-label="Today's call"
      data-testid="todays-call"
      data-state={shown.state}
      data-look={shown.look}
    >
      <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-steele-mid/40 to-transparent" />
      <div className="relative flex items-center gap-4">
        <div
          data-testid="call-mark-ring"
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
            <p className="font-mono text-xs uppercase tracking-[0.25em] text-text-muted">
              {dateLabel}
            </p>
          )}
          <p className={cn('mt-1 inline-flex items-center gap-2 text-2xl font-semibold tracking-tight', style.tone)}>
            <Icon className="h-5 w-5 shrink-0" aria-hidden data-testid={`call-icon-${shown.look}`} />
            <span>{shown.headline}</span>
          </p>
          <p className="mt-0.5 text-sm text-text-secondary">{lead ? `${lead} ${text}` : text}</p>
          {recap ? (
            <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl border border-white/10 bg-bg/45 px-3 py-2">
              <div className="min-w-0 flex-1">
                <p className="text-xs font-medium uppercase tracking-[0.12em] text-text-muted">
                  {recap.title}
                </p>
                <p className="text-sm text-text-primary">{recap.text}</p>
              </div>
              {recap.ctaLabel && recap.ctaTo ? (
                <Link
                  to={recap.ctaTo}
                  /* Batch 254 (UX241-13): this measured 49 x 20 px — the last
                     control in the app under its own 44 px floor, and it sits
                     inside the hero, the highest-traffic card there is. It is
                     the *correction* affordance, so it is reached precisely when
                     he has mis-tapped something already. */
                  className="tap-target inline-flex shrink-0 items-center justify-center px-2 text-sm font-medium text-primary-text underline-offset-4 hover:underline"
                >
                  {recap.ctaLabel}
                </Link>
              ) : null}
            </div>
          ) : null}
          <p className="mt-3 inline-flex rounded-full border border-border bg-surface/60 px-2.5 py-1 text-xs font-medium text-text-secondary">
            {shown.readingWords}
          </p>
        </div>
      </div>
    </section>
  );
}
