import { clearTokens, getAuthToken } from './tokens';

// Empty/unset in production = same-origin (requests go through Vercel proxy rewrite).
const BASE = import.meta.env.VITE_API_URL ?? (import.meta.env.PROD ? '' : 'http://localhost:8000');

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

/** Like `apiFetch`, but for endpoints that return a binary body (e.g. hosted
 * TTS audio) rather than JSON. Callers of this best-effort feature degrade to
 * on-device speech on any error. */
export async function apiFetchBlob(path: string, options: RequestInit = {}): Promise<Blob> {
  const token = getAuthToken();
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string>),
  };
  if (token) headers.Authorization = `Bearer ${token}`;

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
  const token = getAuthToken();
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string>),
  };
  if (token) headers.Authorization = `Bearer ${token}`;

  const resp = await fetch(`${BASE}${path}`, { ...options, headers });

  if (resp.status === 401) {
    await clearTokens();
    window.location.href = '/access';
    throw new Error('Session expired');
  }

  if (!resp.ok) {
    // Surface FastAPI's detail when the error body is JSON; never leak a JSON
    // parser exception for a plain-text upstream 500 (Batch 143).
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
