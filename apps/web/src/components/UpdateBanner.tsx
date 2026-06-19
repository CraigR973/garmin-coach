/**
 * UpdateBanner — smart auto-reload for new SW versions (U26.1).
 *
 * Strategy:
 * 1. A periodic update() poll runs every 45 min (post-mount) so the SW
 *    checks for a new version even if the tab has been open for hours.
 * 2. When a new version is detected (onNeedRefresh), we schedule a reload at
 *    the next "safe" moment:
 *      a. If the tab becomes visible (visibilitychange → visible), reload.
 *      b. If the tab is already visible and the predictions editor has no
 *         unsaved edits, reload after a short grace countdown (5 s).
 *    The reload is always deferred while predictions are dirty (unsaved edits).
 * 3. There is NO permanent-dismiss path. The banner shows a countdown when it
 *    can act; otherwise it shows "Updating when safe…".
 * 4. z-index raised to z-[80] — above the iOS Safari install overlay (z-70).
 */

import { useEffect, useRef, useState } from 'react';
import { registerSW } from 'virtual:pwa-register';
import { RefreshCw } from 'lucide-react';
import { cn } from '@/lib/utils';
import { getPredictionsDirty, subscribePredictionsDirty } from '@/lib/dirtyState';

/** How often to poll the SW for a new version (ms). */
const POLL_INTERVAL_MS = 45 * 60 * 1000; // 45 min

/** Grace countdown (seconds) shown before auto-reloading. */
const COUNTDOWN_S = 5;

export function UpdateBanner() {
  const [needsRefresh, setNeedsRefresh] = useState(false);
  const [countdown, setCountdown] = useState<number | null>(null);
  const [isDirty, setIsDirty] = useState(getPredictionsDirty);
  const updateSWRef = useRef<((reloadPage?: boolean) => Promise<void>) | null>(null);
  const countdownTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── Register SW and set up the periodic update poll ──────────────────────

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

    // Periodic poll so long-lived sessions pick up new versions.
    const pollTimer = setInterval(() => {
      void sw()
        .then(() => void 0)
        .catch(() => void 0);
    }, POLL_INTERVAL_MS);

    return () => clearInterval(pollTimer);
  }, []);

  // ── Subscribe to the dirty-state signal ──────────────────────────────────

  useEffect(() => {
    return subscribePredictionsDirty(setIsDirty);
  }, []);

  // ── Schedule the reload when needsRefresh becomes true ───────────────────

  function reload() {
    void updateSWRef.current?.(true);
  }

  function startCountdown() {
    if (countdownTimerRef.current) return; // already running
    setCountdown(COUNTDOWN_S);
    let remaining = COUNTDOWN_S;
    countdownTimerRef.current = setInterval(() => {
      remaining -= 1;
      if (remaining <= 0) {
        clearInterval(countdownTimerRef.current!);
        countdownTimerRef.current = null;
        setCountdown(null);
        reload();
      } else {
        setCountdown(remaining);
      }
    }, 1000);
  }

  function clearCountdown() {
    if (countdownTimerRef.current) {
      clearInterval(countdownTimerRef.current);
      countdownTimerRef.current = null;
    }
    setCountdown(null);
  }

  // Main scheduling effect: runs whenever needsRefresh, isDirty, or countdown changes.
  useEffect(() => {
    if (!needsRefresh) return;

    // If the user has unsaved edits, cancel any running countdown and wait.
    if (isDirty) {
      clearCountdown();
      return;
    }

    // Tab is currently hidden — listen for it to come back to the foreground.
    if (document.visibilityState === 'hidden') {
      const onVisible = () => {
        if (document.visibilityState === 'visible' && !getPredictionsDirty()) {
          startCountdown();
        }
      };
      document.addEventListener('visibilitychange', onVisible);
      return () => document.removeEventListener('visibilitychange', onVisible);
    }

    // Tab is visible and not dirty — start the grace countdown.
    startCountdown();

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [needsRefresh, isDirty]);

  // Clean up the countdown timer on unmount.
  useEffect(() => () => clearCountdown(), []);

  if (!needsRefresh) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      className={cn(
        // z-[80] places the banner above the iOS Safari install overlay (z-[70]).
        'fixed top-0 left-0 right-0 z-[80]',
        'pt-safe bg-primary text-white shadow-md',
      )}
    >
      <div className="flex items-center justify-between gap-3 px-4 py-2.5">
        <div className="flex items-center gap-2 min-w-0">
          <RefreshCw className="h-4 w-4 shrink-0 animate-spin" aria-hidden />
          <span className="text-sm font-sans font-medium truncate">
            {isDirty
              ? 'New version ready — updating after save'
              : countdown !== null
                ? `Updating in ${countdown}…`
                : 'New version ready — updating shortly'}
          </span>
        </div>
        {/* Manual trigger — always available so users aren't stuck waiting. */}
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
