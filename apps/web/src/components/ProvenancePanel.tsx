import { ChevronDown } from 'lucide-react';
import { describeProvenance, provenanceEntries, type ProvenanceRow } from '@/lib/provenance';

interface ProvenancePanelProps {
  /** Raw provenance lists from the packet(s) behind this screen, in display order. */
  sources: unknown[];
  timeZone?: string;
}

/**
 * Batch 273.2 — "How these numbers were worked out".
 *
 * Layout decided by Craig on 23 Sep: one panel per screen, directly under the
 * prose, collapsed by default so a reader who is not arguing with a number never
 * sees it, with one expandable row per covered figure on that screen. An inline
 * expander under each figure was ruled out because the figures exist only inside
 * model-written markdown (273.1).
 */
export function ProvenancePanel({ sources, timeZone }: ProvenancePanelProps) {
  const rows = sources
    .flatMap((raw) => provenanceEntries(raw))
    .map((entry) => describeProvenance(entry, timeZone))
    .filter((row): row is ProvenanceRow => row !== null);
  if (rows.length === 0) return null;

  return (
    <details className="group rounded-xl border border-border bg-bg px-4 py-3" data-testid="provenance-panel">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 text-sm font-medium text-text-secondary transition hover:text-text-primary">
        How these numbers were worked out
        <ChevronDown className="h-4 w-4 shrink-0 transition-transform group-open:rotate-180" aria-hidden />
      </summary>
      <div className="mt-3 space-y-2">
        {rows.map((row) => (
          <details key={row.figure} className="group/row rounded-lg border border-border/70 px-3 py-2">
            <summary className="cursor-pointer text-sm font-medium text-text-primary">{row.title}</summary>
            <ul className="mt-2 space-y-1.5 border-l border-border pl-3 text-sm leading-6 text-text-secondary">
              {row.lines.map((line) => (
                <li key={line.label}>
                  <span className="font-medium text-text-primary">{line.label}:</span> {line.text}
                </li>
              ))}
            </ul>
            {row.warning ? (
              <p className="mt-2 text-sm leading-6 text-amber-700 dark:text-amber-300">⚠️ {row.warning}</p>
            ) : null}
          </details>
        ))}
      </div>
    </details>
  );
}
