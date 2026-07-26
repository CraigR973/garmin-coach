const DEVICE_TOKEN_KEY = 'coach_device_token';
const PLAYER_KEY = 'coach_player';
const LEGACY_AUTH_KEYS = ['coach_access', 'coach_refresh'] as const;

export interface StoredPlayer {
  id: string;
  displayName: string;
  role: 'player' | 'admin';
  timezone: string;
}

export function storeDeviceToken(token: string, player: StoredPlayer): void {
  LEGACY_AUTH_KEYS.forEach((key) => localStorage.removeItem(key));
  localStorage.setItem(DEVICE_TOKEN_KEY, token);
  localStorage.setItem(PLAYER_KEY, JSON.stringify(player));
}

export function getDeviceToken(): string | null {
  return localStorage.getItem(DEVICE_TOKEN_KEY);
}

export function getAuthToken(): string | null {
  return getDeviceToken();
}

export function getStoredPlayer(): StoredPlayer | null {
  const raw = localStorage.getItem(PLAYER_KEY);
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
      caches.delete('api-daily-loop'),
    ]);
  }
}

export async function clearTokens(): Promise<void> {
  localStorage.removeItem(DEVICE_TOKEN_KEY);
  localStorage.removeItem(PLAYER_KEY);
  LEGACY_AUTH_KEYS.forEach((key) => localStorage.removeItem(key));
  await clearApiCaches();
}
