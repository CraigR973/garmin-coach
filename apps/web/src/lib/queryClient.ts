import { QueryClient, type Query } from '@tanstack/react-query';
import { createSyncStoragePersister } from '@tanstack/query-sync-storage-persister';
import type { PersistQueryClientOptions } from '@tanstack/react-query-persist-client';

// Batch 62.1: persist the daily-loop brief so a cold open (PWA relaunch / hard
// reload) paints the last brief instantly instead of blocking the whole Home
// screen on one fat network round-trip behind an empty cache.

/** localStorage key holding the dehydrated React Query cache. */
export const PERSIST_KEY = 'gc-rq-cache';

/** Only these query keys are written to disk — keeps health data at rest bounded. */
const PERSISTED_QUERY_KEYS = new Set(['daily-loop']);

/** Build-time buster: a new deploy invalidates any cache with an older shape. */
const BUSTER = typeof __APP_BUSTER__ === 'string' ? __APP_BUSTER__ : 'dev';

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: true,
    },
  },
});

export const persister = createSyncStoragePersister({
  storage: typeof window !== 'undefined' ? window.localStorage : undefined,
  key: PERSIST_KEY,
});

/** True only for a successful query whose key we deliberately persist. */
export function shouldPersistQuery(query: Query): boolean {
  return query.state.status === 'success' && PERSISTED_QUERY_KEYS.has(String(query.queryKey[0]));
}

export const persistOptions: Omit<PersistQueryClientOptions, 'queryClient'> = {
  persister,
  // A returning open should still hydrate within a day; older briefs expire.
  maxAge: 24 * 60 * 60 * 1000,
  buster: BUSTER,
  dehydrateOptions: {
    shouldDehydrateQuery: shouldPersistQuery,
  },
};

/**
 * Drop the persisted cache from disk. Called alongside `queryClient.clear()` on
 * login / activate / unlock / logout so one user's health data can never
 * rehydrate into another session.
 */
export function clearPersistedCache(): void {
  if (typeof window === 'undefined') return;
  window.localStorage.removeItem(PERSIST_KEY);
}
