/**
 * ScoringGuide — collapsible quick-reference on the Predictions page.
 *
 * All scoring data (rows, worked examples, specials) is sourced from the
 * shared scoringData module so it stays in sync with AboutPage.
 */

import { useState } from 'react';
import { ChevronDown } from 'lucide-react';
import { cn } from '@/lib/utils';
import { MATCH_SCORING_ROWS, WORKED_EXAMPLES } from '@/lib/scoringData';

const DEFAULT_STORAGE_KEY = 'sss_scoring_guide_open';

function getInitialOpen(storageKey: string, defaultOpen: boolean): boolean {
  try {
    const stored = localStorage.getItem(storageKey);
    return stored === null ? defaultOpen : stored !== 'false';
  } catch {
    return defaultOpen;
  }
}

function persistOpen(storageKey: string, open: boolean): void {
  try { localStorage.setItem(storageKey, String(open)); } catch { /* ignore */ }
}

interface ScoringGuideProps {
  /** localStorage key for the open/closed state. Defaults to the Predictions-page key. */
  storageKey?: string;
  /** Open state on first visit, before any stored value. Defaults to true. */
  defaultOpen?: boolean;
}

/**
 * Collapsible scoring quick-reference. Used on the Predictions page (default
 * open) and the Home page (passed defaultOpen={false} with its own storageKey).
 * Toggle state persisted in localStorage per key.
 */
export function ScoringGuide({
  storageKey = DEFAULT_STORAGE_KEY,
  defaultOpen = true,
}: ScoringGuideProps = {}) {
  const [open, setOpen] = useState(() => getInitialOpen(storageKey, defaultOpen));

  function toggle() {
    const next = !open;
    setOpen(next);
    persistOpen(storageKey, next);
  }

  return (
    <div className="rounded-lg border border-border bg-surface mb-4 overflow-hidden">
      {/* Header row — always visible */}
      <button
        type="button"
        onClick={toggle}
        aria-expanded={open}
        aria-controls="scoring-guide-body"
        className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-surface-elevated transition-colors focus-visible:outline-none focus-visible:shadow-glow"
      >
        <div className="flex items-center gap-2">
          <p className="font-mono text-[10px] tracking-[0.25em] uppercase text-text-muted">
            Scoring quick-ref
          </p>
          <span className="inline-block px-1.5 py-0.5 rounded bg-primary/15 text-primary font-mono text-[10px] font-semibold leading-4">
            max 10 / match
          </span>
        </div>
        <ChevronDown
          className={cn(
            'h-4 w-4 text-text-muted transition-transform duration-200',
            open && 'rotate-180',
          )}
          aria-hidden
        />
      </button>

      {/* Collapsible body */}
      {open && (
        <div id="scoring-guide-body">
          {/* Lock reminder */}
          <div className="mx-4 mb-3 flex items-start gap-2 rounded-md bg-warning/10 border border-warning/20 px-3 py-2">
            <span className="text-warning text-xs mt-px" aria-hidden>⏱</span>
            <p className="text-xs font-sans text-text-secondary leading-snug">
              <strong className="text-text-primary font-semibold">Predictions lock at each match's kickoff</strong> — not a single deadline. Submit before the whistle.
            </p>
          </div>

          {/* Scoring table */}
          <table className="w-full text-xs font-sans border-collapse px-1 mb-1" aria-label="Scoring criteria">
            <thead>
              <tr className="border-t border-b border-border">
                <th scope="col" className="text-left py-1.5 pl-4 text-text-muted font-medium uppercase tracking-wider text-[10px]">
                  Criteria
                </th>
                <th scope="col" className="text-right py-1.5 pr-4 text-text-muted font-medium uppercase tracking-wider text-[10px] w-12">
                  Pts
                </th>
              </tr>
            </thead>
            <tbody>
              {MATCH_SCORING_ROWS.map((r) => (
                <tr
                  key={r.label}
                  className={cn(
                    'border-b border-border/50',
                    r.accent && 'bg-surface-elevated/60',
                  )}
                >
                  <td className="py-2 pl-4">
                    <p className={cn('font-medium', r.accent ? 'text-text-primary' : 'text-text-secondary')}>
                      {r.label}
                    </p>
                    <p className="text-text-muted text-[11px]">{r.note}</p>
                  </td>
                  <td className="py-2 pr-4 text-right">
                    <span
                      className={cn(
                        'inline-block px-1.5 py-0.5 rounded-full font-mono font-semibold text-[11px] leading-4',
                        r.accent
                          ? 'bg-accent/15 text-accent'
                          : 'bg-primary/15 text-primary',
                      )}
                    >
                      {r.pts}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {/* Worked examples */}
          <div className="px-4 pb-4 mt-3">
            <p className="font-mono text-[10px] tracking-[0.2em] uppercase text-text-muted mb-2">
              Worked examples
            </p>
            <table className="w-full text-xs font-sans border-collapse" aria-label="Scoring worked examples">
              <thead>
                <tr className="border-b border-border">
                  <th scope="col" className="text-left py-1 text-text-muted font-medium uppercase tracking-wider text-[10px]">You</th>
                  <th scope="col" className="text-left py-1 px-2 text-text-muted font-medium uppercase tracking-wider text-[10px]">Actual</th>
                  <th scope="col" className="text-left py-1 text-text-muted font-medium uppercase tracking-wider text-[10px]">Breakdown</th>
                  <th scope="col" className="text-right py-1 text-text-muted font-medium uppercase tracking-wider text-[10px] w-12">Pts</th>
                </tr>
              </thead>
              <tbody>
                {WORKED_EXAMPLES.map((ex) => (
                  <tr
                    key={ex.total}
                    className={cn(
                      'border-b border-border/30',
                      ex.total === 10 && 'bg-accent/5',
                      ex.total === 0 && 'opacity-60',
                    )}
                  >
                    <td className="py-1.5 font-mono text-text-primary">{ex.predicted}</td>
                    <td className="py-1.5 px-2 font-mono text-text-primary">{ex.actual}</td>
                    <td className="py-1.5 text-text-muted text-[11px] leading-snug">{ex.breakdown}</td>
                    <td className="py-1.5 text-right">
                      <span
                        className={cn(
                          'inline-block px-1.5 py-0.5 rounded-full font-mono font-semibold text-[11px] leading-4',
                          ex.total === 10
                            ? 'bg-accent/15 text-accent'
                            : ex.total === 0
                              ? 'bg-border text-text-muted'
                              : 'bg-primary/15 text-primary',
                        )}
                        data-example-total={ex.total}
                      >
                        {ex.total}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
