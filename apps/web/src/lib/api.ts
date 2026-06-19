import {
  clearTokens,
  getAccessToken,
  getRefreshToken,
  isAccessTokenExpiringSoon,
  storeTokens,
  getStoredPlayer,
} from './tokens';

if (import.meta.env.PROD && import.meta.env.VITE_API_URL === undefined) {
  throw new Error('VITE_API_URL is required in production builds');
}
// Empty string = same-origin (requests go through Vercel proxy rewrite).
const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';

/**
 * Default league slug for screens not yet migrated to the per-league
 * LeagueContext (arrives in M6/M7). Mirrors the backend's M2 default so the
 * existing single-league UI keeps resolving to the Calcio league after
 * the M5 endpoint move under /api/v1/leagues/{slug}/.
 * NOTE: slug value is a structural DB identifier — do NOT rename without a migration + redirect.
 */
export const DEFAULT_LEAGUE_SLUG = 'steele-spreadsheet';

let refreshPromise: Promise<void> | null = null;

async function silentRefresh(): Promise<void> {
  const refreshToken = getRefreshToken();
  if (!refreshToken) {
    await clearTokens();
    throw new Error('No refresh token');
  }
  const resp = await fetch(`${BASE}/api/v1/auth/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
  if (!resp.ok) {
    clearTokens();
    throw new Error('Refresh failed');
  }
  const data = await resp.json();
  const player = getStoredPlayer()!;
  storeTokens(data.access_token, data.refresh_token, player);
}

async function ensureFreshToken(): Promise<void> {
  if (!isAccessTokenExpiringSoon()) return;
  if (!refreshPromise) {
    refreshPromise = silentRefresh().finally(() => {
      refreshPromise = null;
    });
  }
  await refreshPromise;
}

export async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  await ensureFreshToken();

  const accessToken = getAccessToken();
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string>),
  };
  if (accessToken) headers['Authorization'] = `Bearer ${accessToken}`;

  const resp = await fetch(`${BASE}${path}`, { ...options, headers });

  if (resp.status === 401) {
    // Access token was rejected — attempt one refresh then retry
    try {
      await silentRefresh();
      const retryToken = getAccessToken();
      if (retryToken) headers['Authorization'] = `Bearer ${retryToken}`;
      const retry = await fetch(`${BASE}${path}`, { ...options, headers });
      if (!retry.ok) throw new Error(`${retry.status}`);
      return retry.json() as Promise<T>;
    } catch {
      await clearTokens();
      window.location.href = '/login';
      throw new Error('Session expired');
    }
  }

  if (!resp.ok) {
    // Try to surface the FastAPI `detail` field for a more useful error message.
    try {
      const body = await resp.json();
      const detail = typeof body?.detail === 'string' ? body.detail : undefined;
      throw new Error(detail ?? `API error ${resp.status}`);
    } catch (e) {
      if (e instanceof Error && e.message !== `API error ${resp.status}`) throw e;
      throw new Error(`API error ${resp.status}`);
    }
  }
  if (resp.status === 204) return undefined as T;
  return resp.json() as Promise<T>;
}
