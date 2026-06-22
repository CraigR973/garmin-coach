import React, { createContext, useCallback, useContext, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import {
  clearApiCaches,
  clearTokens,
  getAccessToken,
  getDeviceToken,
  getRefreshToken,
  getStoredPlayer,
  isAccessTokenExpired,
  storeDeviceToken,
  storeTokens,
  type StoredPlayer,
} from '../lib/tokens';

if (import.meta.env.PROD && import.meta.env.VITE_API_URL === undefined) {
  throw new Error('VITE_API_URL is required in production builds');
}
// Empty string = same-origin (requests go through Vercel proxy rewrite).
const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';

interface AuthState {
  player: StoredPlayer | null;
  isLoading: boolean;
  sessionUnlockRequired: boolean;
  sessionUnlockError: string | null;
}

interface AuthContextValue extends AuthState {
  login: (displayName: string, pin: string) => Promise<void>;
  activateDevice: (code: string) => Promise<void>;
  logout: () => Promise<void>;
  updatePlayer: (patch: Partial<StoredPlayer>) => void;
  unlockStoredSession: (pin: string) => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function playerFromApiResponse(data: {
  player: { id: string; display_name: string; role: string; timezone: string };
}): StoredPlayer {
  return {
    id: data.player.id,
    displayName: data.player.display_name,
    role: data.player.role as 'player' | 'admin',
    timezone: data.player.timezone,
  };
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient();
  const initialPlayer = getStoredPlayer();
  const initialRequiresUnlock =
    !!initialPlayer && !!getRefreshToken() && !getDeviceToken() && isAccessTokenExpired();
  const [lockedPlayer, setLockedPlayer] = useState<StoredPlayer | null>(
    initialRequiresUnlock ? initialPlayer : null,
  );
  const [state, setState] = useState<AuthState>({
    player: initialPlayer,
    isLoading: false,
    sessionUnlockRequired: initialRequiresUnlock,
    sessionUnlockError: null,
  });

  const login = useCallback(
    async (displayName: string, pin: string) => {
      setState((s) => ({ ...s, isLoading: true }));
      try {
        const resp = await fetch(`${BASE}/api/v1/auth/login`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ display_name: displayName, pin }),
        });
        if (!resp.ok) {
          const err = await resp.json().catch(() => ({}));
          throw new Error((err as { detail?: string }).detail ?? 'Login failed');
        }
        const data = await resp.json();
        const player = playerFromApiResponse(data);
        await clearApiCaches();
        queryClient.clear();
        storeTokens(data.access_token, data.refresh_token, player);
        setLockedPlayer(null);
        setState({ player, isLoading: false, sessionUnlockRequired: false, sessionUnlockError: null });
      } catch (err) {
        setState((s) => ({ ...s, isLoading: false }));
        throw err;
      }
    },
    [queryClient],
  );

  const activateDevice = useCallback(
    async (code: string) => {
      setState((s) => ({ ...s, isLoading: true }));
      try {
        const resp = await fetch(`${BASE}/api/v1/auth/activate`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ code }),
        });
        if (!resp.ok) {
          const err = await resp.json().catch(() => ({}));
          throw new Error((err as { detail?: string }).detail ?? 'Activation failed');
        }
        const data = await resp.json();
        const player = playerFromApiResponse(data);
        await clearApiCaches();
        queryClient.clear();
        storeDeviceToken(data.device_token, player);
        setLockedPlayer(null);
        setState({
          player,
          isLoading: false,
          sessionUnlockRequired: false,
          sessionUnlockError: null,
        });
      } catch (err) {
        setState((s) => ({ ...s, isLoading: false }));
        throw err;
      }
    },
    [queryClient],
  );

  const logout = useCallback(async () => {
    const refreshToken = getRefreshToken();
    if (refreshToken) {
      fetch(`${BASE}/api/v1/auth/logout`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
      }).catch(() => {});
    }
    await clearTokens();
    queryClient.clear();
    setLockedPlayer(null);
    setState({ player: null, isLoading: false, sessionUnlockRequired: false, sessionUnlockError: null });
  }, [queryClient]);

  const updatePlayer = useCallback((patch: Partial<StoredPlayer>) => {
    setState((s) => {
      if (!s.player) return s;
      const updated = { ...s.player, ...patch };
      const access = getAccessToken();
      const refresh = getRefreshToken();
      const deviceToken = getDeviceToken();
      if (deviceToken) storeDeviceToken(deviceToken, updated);
      else if (access && refresh) storeTokens(access, refresh, updated);
      return { ...s, player: updated };
    });
  }, []);

  const unlockStoredSession = useCallback(
    async (pin: string) => {
      if (!lockedPlayer) return;
      setState((s) => ({ ...s, isLoading: true, sessionUnlockError: null }));
      try {
        const resp = await fetch(`${BASE}/api/v1/auth/login`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ display_name: lockedPlayer.displayName, pin }),
        });
        if (!resp.ok) {
          const err = await resp.json().catch(() => ({}));
          throw new Error((err as { detail?: string }).detail ?? 'Invalid PIN');
        }
        const data = await resp.json();
        const player = playerFromApiResponse(data);
        await clearApiCaches();
        queryClient.clear();
        storeTokens(data.access_token, data.refresh_token, player);
        setState({ player, isLoading: false, sessionUnlockRequired: false, sessionUnlockError: null });
        setLockedPlayer(null);
      } catch (err) {
        setState((s) => ({
          ...s,
          isLoading: false,
          sessionUnlockRequired: true,
          sessionUnlockError: 'Invalid PIN. Try again or log out if this is not your account.',
        }));
        throw err;
      }
    },
    [lockedPlayer, queryClient],
  );

  return (
    <AuthContext.Provider
      value={{ ...state, login, activateDevice, logout, updatePlayer, unlockStoredSession }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
