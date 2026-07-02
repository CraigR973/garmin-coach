import { useId, useState, type ReactNode } from 'react';
import { ChevronDown } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { cn } from '@/lib/utils';

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
 */
export function CollapsibleSection({
  title,
  icon,
  summary,
  headerAccessory,
  defaultOpen = false,
  children,
}: {
  title: ReactNode;
  icon?: ReactNode;
  /** One-line glance shown in the header while collapsed; hidden once open. */
  summary?: ReactNode;
  /** Optional trailing element in the header (e.g. the verdict badge). */
  headerAccessory?: ReactNode;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const bodyId = useId();
  const showSummary = !open && summary != null && summary !== '';
  return (
    <Card>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-controls={bodyId}
        className="flex w-full items-center gap-3 rounded-lg p-5 text-left focus-visible:outline-none focus-visible:shadow-glow"
      >
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-2 text-lg font-semibold leading-tight tracking-tight text-text-primary">
            {icon}
            {title}
          </span>
          {showSummary ? (
            <span className="mt-1.5 block truncate text-sm text-text-secondary">{summary}</span>
          ) : null}
        </span>
        {headerAccessory}
        <ChevronDown
          className={cn(
            'h-5 w-5 shrink-0 text-text-muted transition-transform',
            open && 'rotate-180',
          )}
          aria-hidden
        />
      </button>
      {open ? (
        <CardContent id={bodyId} className="pt-0">
          {children}
        </CardContent>
      ) : null}
    </Card>
  );
}
