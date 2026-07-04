import { useId, useState, type ReactNode } from 'react';
import { motion, useReducedMotionConfig } from 'framer-motion';
import { ChevronDown } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import { truncateWords } from '@/lib/truncate';

const SUMMARY_MAX_LENGTH = 72;

/**
 * A Home section that is always present but can be collapsed to a one-line
 * summary (Batch 37 — collapse-not-remove). This is the object-permanence
 * primitive: nothing disappears from Home as the day changes; a non-primary
 * section just shows its `summary` in the header until it's tapped open.
 *
 * The body is rendered only while open, so a data-heavy section (e.g. the
 * bedroom-overnight query inside the sleep card) costs nothing while collapsed.
 * `defaultOpen` is derived from the day's data state on each load — there is no
 * sticky manual collapse state in this batch (avoids a stale-open-panel feeling).
 *
 * A `tone` of `warning` marks a section that needs a tap (Batch 50 — action-first):
 * while collapsed it shows a warning dot in the header so a closed section can
 * signal it holds a pending action, even when a different section is the one
 * expanded. When open, the section's own content carries the state, so the dot
 * is suppressed.
 *
 * A `variant` of `secondary` (Batch 54) visually recedes a card under a quiet
 * "More detail" grouping — a lighter title and a borderless/transparent card —
 * for every section except the one primary/expanded card, so the eye lands on
 * verdict → action → Today first.
 */
export function CollapsibleSection({
  title,
  icon,
  summary,
  tone = 'default',
  variant = 'default',
  defaultOpen = false,
  id,
  className,
  children,
}: {
  title: ReactNode;
  icon?: ReactNode;
  /** One-line glance shown in the header while collapsed; hidden once open. */
  summary?: ReactNode;
  /** `warning` shows a "needs a tap" dot in the header while collapsed. */
  tone?: 'default' | 'warning';
  /** `secondary` recedes the card visually (Batch 54 "More detail" grouping). */
  variant?: 'default' | 'secondary';
  defaultOpen?: boolean;
  /** DOM id on the section card, so the Next strip can scroll to it. */
  id?: string;
  /** Extra classes on the outer Card — used by the Batch 51 desktop grid to
   *  place a section in the act/context column without unmounting it. */
  className?: string;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const bodyId = useId();
  const prefersReducedMotion = useReducedMotionConfig();
  const showSummary = !open && summary != null && summary !== '';
  const showDot = !open && tone === 'warning';
  const isSecondary = variant === 'secondary';
  return (
    <Card
      id={id}
      className={cn(isSecondary && 'border-transparent bg-transparent shadow-none', className)}
    >
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-controls={bodyId}
        className="flex w-full items-center gap-3 rounded-lg p-5 text-left focus-visible:outline-none focus-visible:shadow-glow"
      >
        <span className="min-w-0 flex-1">
          <span
            className={cn(
              'flex items-center gap-2 leading-tight tracking-tight',
              isSecondary
                ? 'text-base font-medium text-text-secondary'
                : 'text-lg font-semibold text-text-primary',
            )}
          >
            {icon}
            {title}
            {showDot ? (
              <span
                className="h-2 w-2 shrink-0 rounded-full bg-warning"
                role="status"
                aria-label="Needs attention"
              />
            ) : null}
          </span>
          {showSummary ? (
            <span className="mt-1.5 block truncate text-sm text-text-secondary">
              {typeof summary === 'string' ? truncateWords(summary, SUMMARY_MAX_LENGTH) : summary}
            </span>
          ) : null}
        </span>
        <ChevronDown
          className={cn(
            'h-5 w-5 shrink-0 text-text-muted transition-transform',
            open && 'rotate-180',
          )}
          aria-hidden
        />
      </button>
      {open ? (
        // Batch 54: a subtle open animation (fade + settle), not a real measured
        // height tween — height:auto keyframe measurement pulls in jsdom-unsafe
        // browser APIs for no visible benefit here, since the body only ever
        // mounts on open (there is no matching close animation to choreograph).
        <motion.div
          key={bodyId}
          initial={{ opacity: 0, y: prefersReducedMotion ? 0 : -6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: prefersReducedMotion ? 0 : 0.2, ease: 'easeOut' }}
        >
          <CardContent id={bodyId} className="pt-0">
            {children}
          </CardContent>
        </motion.div>
      ) : null}
    </Card>
  );
}
