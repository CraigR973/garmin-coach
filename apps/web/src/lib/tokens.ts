const KEYS = {
  access: 'wc2026_access',
  refresh: 'wc2026_refresh',
  player: 'wc2026_player',
} as const;

export interface StoredPlayer {
  id: string;
  displayName: string;
  email?: string | null;
  role: 'player' | 'admin';
  timezone: string;
  avatarUrl?: string | null;
}

export function storeTokens(access: string, refresh: string, player: StoredPlayer): void {
  localStorage.setItem(KEYS.access, access);
  localStorage.setItem(KEYS.refresh, refresh);
  localStorage.setItem(KEYS.player, JSON.stringify(player));
}

export function getAccessToken(): string | null {
  return localStorage.getItem(KEYS.access);
}

export function getRefreshToken(): string | null {
  return localStorage.getItem(KEYS.refresh);
}

export function getStoredPlayer(): StoredPlayer | null {
  const raw = localStorage.getItem(KEYS.player);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as StoredPlayer;
  } catch {
    return null;
  }
}

export async function clearApiCaches(): Promise<void> {
  if (typeof caches !== 'undefined') {
    await Promise.all([
      caches.delete('api-user-data'),
      caches.delete('api-matches'),
    ]);
  }
}

export async function clearTokens(): Promise<void> {
  Object.values(KEYS).forEach((k) => localStorage.removeItem(k));
  await clearApiCaches();
}

/** Decode JWT payload without verifying — used only to read exp for proactive refresh. */
export function jwtPayload(token: string): Record<string, unknown> | null {
  try {
    const [, b64] = token.split('.');
    return JSON.parse(atob(b64.replace(/-/g, '+').replace(/_/g, '/')));
  } catch {
    return null;
  }
}

/** Returns true if the access token is expired or within 60 s of expiry. */
export function isAccessTokenExpiringSoon(): boolean {
  const token = getAccessToken();
  if (!token) return true;
  const payload = jwtPayload(token);
  if (!payload || typeof payload.exp !== 'number') return true;
  return payload.exp - Date.now() / 1000 < 60;
}

/** Returns true only when the access token has actually passed its expiry. */
export function isAccessTokenExpired(): boolean {
  const token = getAccessToken();
  if (!token) return true;
  const payload = jwtPayload(token);
  if (!payload || typeof payload.exp !== 'number') return true;
  return payload.exp < Date.now() / 1000;
}
