import { useOnlineStatus } from '@/hooks/useOnlineStatus';
import { useOfflineQueue } from '@/hooks/useOfflineQueue';

export function OfflineBanner() {
  const isOnline = useOnlineStatus();
  const pendingCount = useOfflineQueue();

  if (isOnline && pendingCount === 0) return null;

  // Offline: warn the user. Online with queued items: indicate sync in progress.
  const message = isOnline
    ? `Syncing ${pendingCount} pending prediction${pendingCount === 1 ? '' : 's'}…`
    : pendingCount > 0
      ? `You're offline — ${pendingCount} prediction${pendingCount === 1 ? '' : 's'} queued to sync`
      : "You're offline — some content may be outdated";

  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="offline-banner"
      className={`border-b text-sm font-sans text-center py-2 px-4 ${
        isOnline
          ? 'bg-primary/15 border-primary/30 text-primary'
          : 'bg-amber-900/80 border-amber-700 text-amber-100'
      }`}
    >
      {message}
    </div>
  );
}
