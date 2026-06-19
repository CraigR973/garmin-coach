import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { usePredictionEditor } from '@/hooks/usePredictionEditor';
import { getQueue, clearQueue } from '@/lib/offlineQueue';
import type { MatchResponse, PredictionResponse } from '@/lib/types';

// A fake JWT with exp in the year 2286 — keeps apiFetch from attempting a refresh.
const FAKE_JWT = 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJwMSIsImV4cCI6OTk5OTk5OTk5OX0.fake';
const STORED_PLAYER = JSON.stringify({ id: 'p1', displayName: 'Alice', role: 'player', timezone: 'UTC' });

// IMPORTANT: these fixtures are module-level constants so the hook receives the
// *same* array references on every internal re-render. Passing fresh literals
// (e.g. `{ predictions: [PRED_M1] }` inline) would make the `[predictions]`
// effect dependency change each render → setLocal → re-render → infinite loop.
const PRED_M1 = {
  match_id: 'm1',
  predicted_home: 2,
  predicted_away: 1,
  points_awarded: null,
};
const M1_PRED = [PRED_M1] as unknown as PredictionResponse[];
const NO_MATCHES: MatchResponse[] = [];

function makeQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={makeQueryClient()}>{children}</QueryClientProvider>;
}

function renderEditor(predictions = M1_PRED, matches = NO_MATCHES) {
  return renderHook(() => usePredictionEditor({ predictions, matches }), { wrapper });
}

function setOnline(value: boolean) {
  Object.defineProperty(navigator, 'onLine', { configurable: true, value });
}

beforeEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
  localStorage.setItem('wc2026_access', FAKE_JWT);
  localStorage.setItem('wc2026_player', STORED_PLAYER);
  clearQueue();
  setOnline(true);
});

afterEach(() => {
  clearQueue();
  setOnline(true);
});

describe('usePredictionEditor', () => {
  it('initialises local state from server predictions', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve({}) })));
    const { result } = renderEditor();

    await waitFor(() => expect(result.current.local['m1']).toBeTruthy());
    expect(result.current.local['m1']).toMatchObject({
      home: '2',
      away: '1',
      dirty: false,
      saving: false,
    });
  });

  it('marks a field dirty immediately and autosaves via debounced PUT (online)', async () => {
    const fetchMock = vi.fn((_url: string, _opts?: RequestInit) =>
      Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const { result } = renderEditor();
    await waitFor(() => expect(result.current.local['m1']).toBeTruthy());

    act(() => result.current.handleHomeChange('m1', '3'));

    // Optimistic + dirty right away
    expect(result.current.local['m1']).toMatchObject({ home: '3', dirty: true });

    // Debounced PUT lands within the 800 ms window
    await waitFor(
      () => {
        const puts = (fetchMock.mock.calls as unknown as [string, RequestInit][]).filter(
          ([url, opts]) => url.includes('/api/v1/predictions/m1') && opts?.method === 'PUT',
        );
        expect(puts.length).toBeGreaterThan(0);
      },
      { timeout: 2500 },
    );

    // Clears dirty/saving once the write resolves
    await waitFor(() => expect(result.current.local['m1']).toMatchObject({ dirty: false, saving: false }));
  });

  // U59: refetchOnWindowFocus is now enabled globally, so resuming a backgrounded
  // tab refetches `predictions` mid-edit. A dirty/saving field must survive that —
  // otherwise a focus refetch would silently wipe whatever the player just typed.
  it('preserves a dirty field across a predictions refetch (simulated focus refetch)', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve({}) })));

    const { result, rerender } = renderHook(
      ({ predictions, matches }) => usePredictionEditor({ predictions, matches }),
      { wrapper, initialProps: { predictions: M1_PRED, matches: NO_MATCHES } },
    );
    await waitFor(() => expect(result.current.local['m1']).toBeTruthy());

    act(() => result.current.handleHomeChange('m1', '5'));
    expect(result.current.local['m1']).toMatchObject({ home: '5', dirty: true });

    // Server data refetched on window focus, returned unchanged (still home: 2).
    rerender({ predictions: M1_PRED, matches: NO_MATCHES });

    // The in-progress edit must not be clobbered by the refetched server value.
    expect(result.current.local['m1']).toMatchObject({ home: '5', dirty: true });
  });

  it('enqueues the write to the offline queue instead of PUTting when offline', async () => {
    setOnline(false);
    const fetchMock = vi.fn(() => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) }));
    vi.stubGlobal('fetch', fetchMock);

    const { result } = renderEditor();
    await waitFor(() => expect(result.current.local['m1']).toBeTruthy());

    act(() => result.current.handleHomeChange('m1', '4'));

    await waitFor(() => expect(getQueue().some((q) => q.matchId === 'm1')).toBe(true), { timeout: 2500 });

    const queued = getQueue().find((q) => q.matchId === 'm1');
    expect(queued).toMatchObject({ matchId: 'm1', home: 4, away: 1 });
    // No network PUT should have been attempted while offline
    const puts = (fetchMock.mock.calls as unknown as [string, RequestInit][]).filter(
      ([url, opts]) => url.includes('/api/v1/predictions/') && opts?.method === 'PUT',
    );
    expect(puts.length).toBe(0);
  });
});
