import { useEffect, useSyncExternalStore } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import {
  flushQueue,
  getQueueCount,
  subscribeQueue,
} from '../lib/offlineQueue';

const RETRY_DELAYS = [30_000, 60_000, 120_000] as const;

/**
 * Subscribes the calling component to the offline-queue count and registers a
 * single global `online` listener that auto-flushes the queue when the network
 * returns. On a successful flush we invalidate `predictions` queries so the
 * UI re-fetches authoritative server state and clears any stale local values.
 *
 * If items remain after a flush (partial failure), schedules a backoff retry:
 * 30 s → 60 s → 120 s (capped). The timer is cancelled on unmount or when
 * the queue empties.
 */
export function useOfflineQueue(): number {
  const count = useSyncExternalStore(subscribeQueue, getQueueCount, getQueueCount);
  const queryClient = useQueryClient();

  useEffect(() => {
    let cancelled = false;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let retryCount = 0;

    function scheduleRetry(): void {
      const delay = RETRY_DELAYS[Math.min(retryCount, RETRY_DELAYS.length - 1)];
      retryCount++;
      retryTimer = setTimeout(() => {
        retryTimer = null;
        if (!cancelled) void runFlush();
      }, delay);
    }

    async function runFlush(): Promise<void> {
      const result = await flushQueue();
      if (cancelled) return;
      if (result.succeeded.length > 0) {
        toast.success(
          `Synced ${result.succeeded.length} pending prediction${result.succeeded.length === 1 ? '' : 's'}`,
        );
        await queryClient.invalidateQueries({ queryKey: ['predictions', 'me'] });
      }
      if (result.failed.length > 0) {
        toast.error(
          `${result.failed.length} prediction${result.failed.length === 1 ? '' : 's'} still pending — will retry`,
        );
      }
      if (getQueueCount() > 0 && navigator.onLine) {
        scheduleRetry();
      }
    }

    function handleOnline(): void {
      if (retryTimer) {
        clearTimeout(retryTimer);
        retryTimer = null;
        retryCount = 0;
      }
      void runFlush();
    }
    window.addEventListener('online', handleOnline);

    if (navigator.onLine && getQueueCount() > 0) {
      void runFlush();
    }

    return () => {
      cancelled = true;
      if (retryTimer) {
        clearTimeout(retryTimer);
        retryTimer = null;
      }
      window.removeEventListener('online', handleOnline);
    };
  }, [queryClient]);

  return count;
}
