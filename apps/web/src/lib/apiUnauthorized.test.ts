import { beforeEach, describe, expect, it, vi } from 'vitest';

const clearTokens = vi.fn(async () => {});
const clearPersistedCache = vi.fn();

vi.mock('./tokens', () => ({
  clearTokens: (...args: unknown[]) => clearTokens(...(args as [])),
  getAuthToken: () => 'token',
}));

vi.mock('./queryClient', () => ({
  clearPersistedCache: () => clearPersistedCache(),
}));

/**
 * Batch 253 (DS237-16). A 401 cleared the token and redirected, but not the
 * persisted cache — so the involuntary-expiry path left the dehydrated
 * `daily-loop` query (the morning brief) readable in `localStorage` on a device
 * whose token had been revoked, until the 24h `maxAge` or the next build's
 * `buster` invalidated it. The logout and activation paths already cleared both.
 */
describe('apiFetch on an expired session', () => {
  beforeEach(() => {
    clearTokens.mockClear();
    clearPersistedCache.mockClear();
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('', { status: 401 })),
    );
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { href: '/' },
    });
  });

  it('clears the persisted brief as well as the token', async () => {
    const { apiFetch } = await import('./api');
    await expect(apiFetch('/api/v1/daily-loop')).rejects.toThrow(/session expired/i);

    expect(clearTokens).toHaveBeenCalledTimes(1);
    expect(clearPersistedCache).toHaveBeenCalledTimes(1);
    expect(window.location.href).toBe('/access');
  });
});
