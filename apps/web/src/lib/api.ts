import {
  clearTokens,
  getAuthToken,
  getDeviceToken,
  getRefreshToken,
  isAccessTokenExpiringSoon,
  storeTokens,
  getStoredPlayer,
} from './tokens';

// Empty/unset in production = same-origin (requests go through Vercel proxy rewrite).
const BASE = import.meta.env.VITE_API_URL ?? (import.meta.env.PROD ? '' : 'http://localhost:8000');

let refreshPromise: Promise<void> | null = null;

function detailToMessage(detail: unknown): string | null {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => {
        if (typeof item === 'string') return item;
        if (item && typeof item === 'object') {
          const message = 'msg' in item && typeof item.msg === 'string' ? item.msg : null;
          const loc =
            'loc' in item && Array.isArray(item.loc)
              ? item.loc
                  .map((part: unknown) => String(part))
                  .filter((part: string) => part !== 'body')
                  .join(' -> ')
              : null;
          if (message && loc) return `${loc}: ${message}`;
          return message;
        }
        return null;
      })
      .filter((item): item is string => Boolean(item));
    return parts.length > 0 ? parts.join('; ') : null;
  }
  return null;
}

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
  if (getDeviceToken()) return;
  if (!isAccessTokenExpiringSoon()) return;
  if (!refreshPromise) {
    refreshPromise = silentRefresh().finally(() => {
      refreshPromise = null;
    });
  }
  await refreshPromise;
}

/** Like `apiFetch`, but for endpoints that return a binary body (e.g. hosted
 * TTS audio) rather than JSON. No 401-refresh-retry — callers of a
 * best-effort, opportunistically-degraded feature should just fall back. */
export async function apiFetchBlob(path: string, options: RequestInit = {}): Promise<Blob> {
  await ensureFreshToken();

  const accessToken = getAuthToken();
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string>),
  };
  if (accessToken) headers['Authorization'] = `Bearer ${accessToken}`;

  const resp = await fetch(`${BASE}${path}`, { ...options, headers });
  if (!resp.ok) {
    throw new Error(`API error ${resp.status}`);
  }
  return resp.blob();
}

export async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  await ensureFreshToken();

  const accessToken = getAuthToken();
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string>),
  };
  if (accessToken) headers['Authorization'] = `Bearer ${accessToken}`;

  const resp = await fetch(`${BASE}${path}`, { ...options, headers });

  if (resp.status === 401 && getDeviceToken()) {
    await clearTokens();
    window.location.href = '/login';
    throw new Error('Session expired');
  }

  if (resp.status === 401 && !getDeviceToken()) {
    // Access token was rejected — attempt one refresh then retry
    try {
      await silentRefresh();
      const retryToken = getAuthToken();
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
    // Surface the FastAPI `detail` when the error body is JSON; fall back to a
    // clean `API error {status}` when it isn't. A day-time Anthropic outage used
    // to reach the client as a bare 500 with a plain-text "Internal Server Error"
    // body (Batch 143) — parsing that threw a `SyntaxError` we then re-threw
    // verbatim ("Unexpected token 'I'…"). Never surface that parse error again.
    let detail: string | null = null;
    try {
      const body = await resp.json();
      detail = detailToMessage(body?.detail);
    } catch {
      detail = null;
    }
    throw new Error(detail ?? `API error ${resp.status}`);
  }
  if (resp.status === 204) return undefined as T;
  return resp.json() as Promise<T>;
}
