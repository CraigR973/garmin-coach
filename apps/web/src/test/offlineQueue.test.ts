import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  clearQueue,
  enqueuePrediction,
  flushQueue,
  getQueue,
  getQueueCount,
  subscribeQueue,
} from '@/lib/offlineQueue';

// `apiFetch` is the only outbound dep; mock it so we never touch the network.
vi.mock('@/lib/api', () => ({
  apiFetch: vi.fn(),
}));

import { apiFetch } from '@/lib/api';

const mockApiFetch = vi.mocked(apiFetch);

describe('offlineQueue', () => {
  beforeEach(() => {
    localStorage.clear();
    mockApiFetch.mockReset();
  });
  afterEach(() => {
    clearQueue();
  });

  it('starts empty', () => {
    expect(getQueue()).toEqual([]);
    expect(getQueueCount()).toBe(0);
  });

  it('enqueues a prediction with a timestamp', () => {
    enqueuePrediction({ matchId: 'm1', home: 2, away: 1 });
    const queue = getQueue();
    expect(queue).toHaveLength(1);
    expect(queue[0]).toMatchObject({ matchId: 'm1', home: 2, away: 1 });
    expect(typeof queue[0].ts).toBe('number');
  });

  it('replaces an earlier entry for the same matchId (last write wins)', () => {
    enqueuePrediction({ matchId: 'm1', home: 1, away: 0 });
    enqueuePrediction({ matchId: 'm1', home: 3, away: 2 });
    const queue = getQueue();
    expect(queue).toHaveLength(1);
    expect(queue[0]).toMatchObject({ home: 3, away: 2 });
  });

  it('preserves entries for different matchIds', () => {
    enqueuePrediction({ matchId: 'm1', home: 1, away: 0 });
    enqueuePrediction({ matchId: 'm2', home: 0, away: 2 });
    expect(getQueueCount()).toBe(2);
  });

  it('notifies subscribers when the queue changes', () => {
    const listener = vi.fn();
    const unsub = subscribeQueue(listener);
    enqueuePrediction({ matchId: 'm1', home: 1, away: 1 });
    expect(listener).toHaveBeenCalledTimes(1);
    enqueuePrediction({ matchId: 'm2', home: 2, away: 2 });
    expect(listener).toHaveBeenCalledTimes(2);
    unsub();
    enqueuePrediction({ matchId: 'm3', home: 3, away: 3 });
    expect(listener).toHaveBeenCalledTimes(2);
  });

  it('survives corrupted localStorage by returning an empty queue', () => {
    localStorage.setItem('wc2026.offlineQueue.v1', '{not json');
    expect(getQueue()).toEqual([]);
  });

  it('flushQueue is a no-op when the queue is empty', async () => {
    const result = await flushQueue();
    expect(result).toEqual({ succeeded: [], failed: [] });
    expect(mockApiFetch).not.toHaveBeenCalled();
  });

  it('flushQueue PUTs each entry and removes those that succeed', async () => {
    mockApiFetch.mockResolvedValue(undefined);
    enqueuePrediction({ matchId: 'm1', home: 2, away: 1 });
    enqueuePrediction({ matchId: 'm2', home: 0, away: 0 });

    const result = await flushQueue();

    expect(result.succeeded.sort()).toEqual(['m1', 'm2']);
    expect(result.failed).toEqual([]);
    expect(mockApiFetch).toHaveBeenCalledTimes(2);
    expect(mockApiFetch).toHaveBeenCalledWith('/api/v1/predictions/m1', {
      method: 'PUT',
      body: JSON.stringify({ predicted_home: 2, predicted_away: 1 }),
    });
    expect(getQueue()).toEqual([]);
  });

  it('flushQueue keeps entries whose PUT fails so the next attempt can retry', async () => {
    mockApiFetch
      .mockResolvedValueOnce(undefined) // m1 ok
      .mockRejectedValueOnce(new Error('500')); // m2 fails
    enqueuePrediction({ matchId: 'm1', home: 1, away: 1 });
    enqueuePrediction({ matchId: 'm2', home: 2, away: 2 });

    const result = await flushQueue();

    expect(result.succeeded).toEqual(['m1']);
    expect(result.failed).toEqual(['m2']);
    const remaining = getQueue();
    expect(remaining).toHaveLength(1);
    expect(remaining[0].matchId).toBe('m2');
  });

  it('flushQueue coalesces concurrent calls into a single pass', async () => {
    mockApiFetch.mockResolvedValue(undefined);
    enqueuePrediction({ matchId: 'm1', home: 1, away: 1 });

    const [a, b] = await Promise.all([flushQueue(), flushQueue()]);

    expect(a).toBe(b);
    expect(mockApiFetch).toHaveBeenCalledTimes(1);
  });
});
