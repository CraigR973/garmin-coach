import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { createElement, type PropsWithChildren } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useOnlineStatus } from '@/hooks/useOnlineStatus';
import { useInstallPrompt } from '@/hooks/useInstallPrompt';
import { useOfflineQueue } from '@/hooks/useOfflineQueue';
import { clearQueue, enqueuePrediction, getQueueCount } from '@/lib/offlineQueue';

vi.mock('@/lib/api', () => ({
  apiFetch: vi.fn(),
}));
vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { apiFetch } from '@/lib/api';
const mockApiFetch = vi.mocked(apiFetch);

// ─── useOnlineStatus ─────────────────────────────────────────────────────────

describe('useOnlineStatus', () => {
  beforeEach(() => {
    vi.stubGlobal('navigator', { ...navigator, onLine: true });
  });
  afterEach(() => vi.unstubAllGlobals());

  it('returns true when navigator.onLine is true', () => {
    const { result } = renderHook(() => useOnlineStatus());
    expect(result.current).toBe(true);
  });

  it('updates to false when offline event fires', () => {
    const { result } = renderHook(() => useOnlineStatus());
    act(() => {
      window.dispatchEvent(new Event('offline'));
    });
    expect(result.current).toBe(false);
  });

  it('updates to true when online event fires after going offline', () => {
    vi.stubGlobal('navigator', { ...navigator, onLine: false });
    const { result } = renderHook(() => useOnlineStatus());
    expect(result.current).toBe(false);
    act(() => {
      window.dispatchEvent(new Event('online'));
    });
    expect(result.current).toBe(true);
  });

  it('removes event listeners on unmount', () => {
    const removeSpy = vi.spyOn(window, 'removeEventListener');
    const { unmount } = renderHook(() => useOnlineStatus());
    unmount();
    expect(removeSpy).toHaveBeenCalledWith('online', expect.any(Function));
    expect(removeSpy).toHaveBeenCalledWith('offline', expect.any(Function));
  });
});

// ─── useInstallPrompt ─────────────────────────────────────────────────────────

describe('useInstallPrompt', () => {
  beforeEach(() => {
    // Not standalone, not iOS, no deferred prompt
    vi.stubGlobal('navigator', {
      ...navigator,
      userAgent:
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36',
    });
    vi.spyOn(window, 'matchMedia').mockReturnValue({
      matches: false,
    } as MediaQueryList);
  });
  afterEach(() => vi.unstubAllGlobals());

  it('canInstall is false initially with no deferred prompt', () => {
    const { result } = renderHook(() => useInstallPrompt());
    expect(result.current.canInstall).toBe(false);
    expect(result.current.isInstalled).toBe(false);
  });

  it('canInstall becomes true when beforeinstallprompt fires', () => {
    const { result } = renderHook(() => useInstallPrompt());
    const fakePromptEvent = Object.assign(new Event('beforeinstallprompt'), {
      prompt: vi.fn().mockResolvedValue(undefined),
      userChoice: Promise.resolve({ outcome: 'accepted' }),
    });
    act(() => {
      window.dispatchEvent(fakePromptEvent);
    });
    expect(result.current.canInstall).toBe(true);
  });

  it('isInstalled becomes true when appinstalled fires', () => {
    const { result } = renderHook(() => useInstallPrompt());
    act(() => {
      window.dispatchEvent(new Event('appinstalled'));
    });
    expect(result.current.isInstalled).toBe(true);
    expect(result.current.canInstall).toBe(false);
  });

  it('prompt() calls deferredPrompt.prompt() and clears it', async () => {
    const { result } = renderHook(() => useInstallPrompt());
    const mockPrompt = vi.fn().mockResolvedValue(undefined);
    const fakePromptEvent = Object.assign(new Event('beforeinstallprompt'), {
      prompt: mockPrompt,
      userChoice: Promise.resolve({ outcome: 'accepted' }),
    });
    act(() => {
      window.dispatchEvent(fakePromptEvent);
    });
    await act(async () => {
      await result.current.prompt();
    });
    expect(mockPrompt).toHaveBeenCalledOnce();
    expect(result.current.canInstall).toBe(false);
  });
});

// ─── useOfflineQueue ──────────────────────────────────────────────────────────

describe('useOfflineQueue', () => {
  function wrapper({ children }: PropsWithChildren) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return createElement(QueryClientProvider, { client }, children);
  }

  beforeEach(() => {
    localStorage.clear();
    clearQueue();
    mockApiFetch.mockReset();
    vi.stubGlobal('navigator', { ...navigator, onLine: true });
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    clearQueue();
  });

  it('returns the current queue count', () => {
    vi.stubGlobal('navigator', { ...navigator, onLine: false });
    enqueuePrediction({ matchId: 'm1', home: 1, away: 0 });
    const { result } = renderHook(() => useOfflineQueue(), { wrapper });
    expect(result.current).toBe(1);
  });

  it('reacts to new enqueues from another caller', () => {
    vi.stubGlobal('navigator', { ...navigator, onLine: false });
    const { result } = renderHook(() => useOfflineQueue(), { wrapper });
    expect(result.current).toBe(0);
    act(() => {
      enqueuePrediction({ matchId: 'm1', home: 2, away: 1 });
    });
    expect(result.current).toBe(1);
  });

  it('flushes the queue when the `online` event fires', async () => {
    vi.stubGlobal('navigator', { ...navigator, onLine: false });
    enqueuePrediction({ matchId: 'm1', home: 3, away: 2 });
    mockApiFetch.mockResolvedValue(undefined);

    const { result } = renderHook(() => useOfflineQueue(), { wrapper });
    expect(result.current).toBe(1);

    vi.stubGlobal('navigator', { ...navigator, onLine: true });
    act(() => {
      window.dispatchEvent(new Event('online'));
    });

    await waitFor(() => expect(mockApiFetch).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(getQueueCount()).toBe(0));
  });

  it('flushes on mount if items remain and we are already online', async () => {
    enqueuePrediction({ matchId: 'm1', home: 1, away: 1 });
    mockApiFetch.mockResolvedValue(undefined);

    renderHook(() => useOfflineQueue(), { wrapper });

    await waitFor(() => expect(mockApiFetch).toHaveBeenCalledTimes(1));
  });

  it('schedules a retry when items remain after a flush (item added during flush)', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      // m1 is in queue when flush starts; m2 is added mid-flush and stays
      enqueuePrediction({ matchId: 'm1', home: 1, away: 0 });

      let resolveM1!: () => void;
      mockApiFetch.mockReturnValueOnce(
        new Promise<void>((r) => {
          resolveM1 = r;
        }),
      );

      renderHook(() => useOfflineQueue(), { wrapper });

      // Add m2 while m1's PUT is still in-flight
      enqueuePrediction({ matchId: 'm2', home: 0, away: 1 });

      // Complete m1's PUT — first flush finishes, m2 remains
      await act(async () => {
        resolveM1();
      });
      expect(getQueueCount()).toBe(1);

      // Set up m2 to succeed on the retry flush
      mockApiFetch.mockResolvedValueOnce(undefined);

      // Advance 30 s — retry timer should fire and flush m2
      await act(async () => {
        vi.advanceTimersByTime(30_000);
      });

      await waitFor(() => expect(getQueueCount()).toBe(0));
      expect(mockApiFetch).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it('cancels the retry timer on unmount', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      enqueuePrediction({ matchId: 'm1', home: 1, away: 0 });
      // First call fails so m1 stays in queue → retry will be scheduled
      mockApiFetch.mockRejectedValueOnce(new Error('offline'));

      const { unmount } = renderHook(() => useOfflineQueue(), { wrapper });

      await waitFor(() => expect(mockApiFetch).toHaveBeenCalledTimes(1));
      expect(getQueueCount()).toBe(1);

      // Unmount before the 30 s retry fires
      unmount();
      mockApiFetch.mockResolvedValue(undefined);

      // Advance well past the retry delay — no second flush should happen
      await act(async () => {
        vi.advanceTimersByTime(60_000);
      });

      expect(mockApiFetch).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });
});
