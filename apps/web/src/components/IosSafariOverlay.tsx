import { useEffect, useRef } from 'react';
import { Share, Plus, MoreHorizontal } from 'lucide-react';
import { cn } from '@/lib/utils';

/**
 * Full-screen blocking gate for iOS Safari.
 * No dismiss — the user must install to continue.
 * Shown whenever the app is not running in standalone mode on iOS Safari.
 */
export function IosSafariOverlay() {
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Install required"
      className="fixed inset-0 z-[70] flex flex-col items-center justify-end bg-bg/95 backdrop-blur-sm"
    >
      {/* Sheet */}
      <div className="w-full max-w-sm mx-auto mb-safe-or-6 px-4 pb-2 animate-in slide-in-from-bottom-4 duration-300">
        <div className="rounded-2xl bg-surface border border-border shadow-sheet px-6 pt-6 pb-8">

          {/* Heading */}
          <p className="font-mono text-[10px] tracking-[0.3em] uppercase text-text-muted mb-1">
            Required
          </p>
          <h2
            ref={headingRef}
            tabIndex={-1}
            className="text-xl font-semibold text-text-primary font-sans mb-1 focus:outline-none"
          >
            Install the app first
          </h2>
          <p className="text-sm text-text-secondary font-sans mb-6 leading-relaxed">
            Calcio needs to be added to your home screen before you can use it. Follow these three steps:
          </p>

          {/* Steps */}
          <ol className="space-y-5">
            <li className="flex items-start gap-3">
              <span className="shrink-0 w-7 h-7 rounded-full bg-primary/15 text-primary text-xs font-semibold font-mono flex items-center justify-center mt-0.5">
                1
              </span>
              <div className="flex-1">
                <p className="text-sm font-sans text-text-primary font-medium">
                  Tap{' '}
                  <span className="inline-flex items-center gap-1 font-semibold bg-surface-elevated border border-border rounded px-1.5 py-0.5">
                    <MoreHorizontal className="h-3.5 w-3.5" aria-hidden />
                  </span>{' '}
                  in the bottom-right corner
                </p>
                <p className="text-xs text-text-muted mt-0.5">
                  The three-dot menu in Safari's bottom toolbar.
                </p>
              </div>
            </li>

            <li className="flex items-start gap-3">
              <span className="shrink-0 w-7 h-7 rounded-full bg-primary/15 text-primary text-xs font-semibold font-mono flex items-center justify-center mt-0.5">
                2
              </span>
              <div className="flex-1">
                <p className="text-sm font-sans text-text-primary font-medium">
                  Tap{' '}
                  <span className="inline-flex items-center gap-1 font-semibold bg-surface-elevated border border-border rounded px-1.5 py-0.5">
                    <Share className="h-3.5 w-3.5 text-[#007AFF]" aria-hidden />
                    Share
                  </span>
                </p>
                <p className="text-xs text-text-muted mt-0.5">
                  Opens the iOS share sheet.
                </p>
              </div>
            </li>

            <li className="flex items-start gap-3">
              <span className="shrink-0 w-7 h-7 rounded-full bg-primary/15 text-primary text-xs font-semibold font-mono flex items-center justify-center mt-0.5">
                3
              </span>
              <div className="flex-1">
                <p className="text-sm font-sans text-text-primary font-medium">
                  Tap{' '}
                  <span className="inline-flex items-center gap-1 font-semibold bg-surface-elevated border border-border rounded px-1.5 py-0.5">
                    <Plus className="h-3.5 w-3.5" aria-hidden />
                    Add to Home Screen
                  </span>
                </p>
                <p className="text-xs text-text-muted mt-0.5">
                  Scroll down in the share sheet to find it, then tap{' '}
                  <strong className="text-text-secondary">Add</strong> in the top-right.
                </p>
              </div>
            </li>
          </ol>

          {/* Arrow pointing down toward Safari toolbar */}
          <div className="mt-6 flex flex-col items-center gap-1.5" aria-hidden="true">
            <div
              className={cn(
                'w-px h-8 rounded-full',
                'bg-gradient-to-b from-primary/60 to-transparent',
              )}
            />
            <div className="w-2 h-2 border-b-2 border-r-2 border-primary/60 rotate-45 -mt-2" />
          </div>

          <p className="mt-5 text-xs text-center text-text-muted font-sans">
            After adding, close Safari and open from your home screen.
          </p>
        </div>
      </div>
    </div>
  );
}
