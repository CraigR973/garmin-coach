/**
 * UpdateBanner — notifies user when a new SW version is available.
 * Phase 0: simple "reload now" button, no dirty-state awareness.
 * Phase 1: add dirty-state guard when the coaching brief editor ships.
 */

import { useEffect, useRef, useState } from 'react';
import { registerSW } from 'virtual:pwa-register';
import { RefreshCw } from 'lucide-react';
import { cn } from '@/lib/utils';

const POLL_INTERVAL_MS = 45 * 60 * 1000; // 45 min

export function UpdateBanner() {
  const [needsRefresh, setNeedsRefresh] = useState(false);
  const updateSWRef = useRef<((reloadPage?: boolean) => Promise<void>) | null>(null);

  useEffect(() => {
    const sw = registerSW({
      onNeedRefresh() {
        setNeedsRefresh(true);
      },
      onOfflineReady() {
        // SW cached — no UI needed
      },
    });
    updateSWRef.current = sw;

    const pollTimer = setInterval(() => {
      void sw().catch(() => void 0);
    }, POLL_INTERVAL_MS);

    return () => clearInterval(pollTimer);
  }, []);

  function reload() {
    void updateSWRef.current?.(true);
  }

  if (!needsRefresh) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      className={cn(
        'fixed top-0 left-0 right-0 z-[80]',
        'pt-safe bg-primary text-white shadow-md',
      )}
    >
      <div className="flex items-center justify-between gap-3 px-4 py-2.5">
        <div className="flex items-center gap-2 min-w-0">
          <RefreshCw className="h-4 w-4 shrink-0" aria-hidden />
          <span className="text-sm font-sans font-medium">New version available</span>
        </div>
        <button
          onClick={reload}
          className="tap-target shrink-0 px-3 py-1 rounded-sm text-sm font-sans font-semibold bg-white/20 hover:bg-white/30 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/50"
        >
          Update now
        </button>
      </div>
    </div>
  );
}
