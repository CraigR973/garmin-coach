// Offline write queue for prediction saves.
// When a PUT fails because the browser is offline, the prediction is persisted to
// localStorage and replayed when the `online` event fires (or `flushQueue` is
// called manually). Only group-stage score predictions go through this queue —
// knockout/specials writes happen rarely and surface the standard error toast.

import { apiFetch } from './api';

export interface QueuedPrediction {
  matchId: string;
  home: number;
  away: number;
  /** Epoch millis when the user submitted; used to dedupe — last write wins. */
  ts: number;
}

const STORAGE_KEY = 'wc2026.offlineQueue.v1';

function read(): QueuedPrediction[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    return Array.isArray(parsed) ? (parsed as QueuedPrediction[]) : [];
  } catch {
    return [];
  }
}

function write(queue: QueuedPrediction[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(queue));
  } catch {
    // Quota / private-mode failures — silently drop; the user will see the
    // banner remain in its "outdated" state and can retry while online.
  }
  notifyListeners();
}

const listeners = new Set<() => void>();
function notifyListeners(): void {
  for (const l of listeners) l();
}

export function subscribeQueue(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function getQueue(): QueuedPrediction[] {
  return read();
}

export function getQueueCount(): number {
  return read().length;
}

/** Enqueue or replace any earlier write for the same matchId (last write wins). */
export function enqueuePrediction(entry: Omit<QueuedPrediction, 'ts'>): void {
  const queue = read().filter((q) => q.matchId !== entry.matchId);
  queue.push({ ...entry, ts: Date.now() });
  write(queue);
}

export function clearQueue(): void {
  write([]);
}

interface FlushResult {
  succeeded: string[];
  failed: string[];
}

/**
 * Replay the queue. Each entry that succeeds is removed; failures stay queued
 * so the next online transition can retry. Returns the matchIds processed.
 *
 * Guarded by an in-flight promise so concurrent flush attempts (e.g. `online`
 * event firing twice, or a manual retry mid-flush) coalesce into one pass.
 */
let inFlight: Promise<FlushResult> | null = null;

export async function flushQueue(): Promise<FlushResult> {
  if (inFlight) return inFlight;
  const queue = read();
  if (queue.length === 0) return { succeeded: [], failed: [] };

  inFlight = (async () => {
    const succeeded: string[] = [];
    const failed: string[] = [];

    for (const entry of queue) {
      try {
        await apiFetch(`/api/v1/predictions/${entry.matchId}`, {
          method: 'PUT',
          body: JSON.stringify({
            predicted_home: entry.home,
            predicted_away: entry.away,
          }),
        });
        succeeded.push(entry.matchId);
      } catch {
        failed.push(entry.matchId);
      }
    }

    if (succeeded.length > 0) {
      const remaining = read().filter(
        (q) =>
          !succeeded.includes(q.matchId) ||
          // Re-keep if the user wrote a NEWER version after we started flushing.
          (q.ts > (queue.find((e) => e.matchId === q.matchId)?.ts ?? 0)),
      );
      write(remaining);
    }

    return { succeeded, failed };
  })().finally(() => {
    inFlight = null;
  });

  return inFlight;
}
