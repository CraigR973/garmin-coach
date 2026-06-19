import React, { createContext, useCallback, useContext, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { clearApiCaches, clearTokens, getAccessToken, getRefreshToken, getStoredPlayer, isAccessTokenExpired, storeTokens, StoredPlayer } from '../lib/tokens';

if (import.meta.env.PROD && !import.meta.env.VITE_API_URL) {
  throw new Error('VITE_API_URL is required in production builds');
}
const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';

interface AuthState {
  player: StoredPlayer | null;
  isLoading: boolean;
  sessionUnlockRequired: boolean;
  sessionUnlockError: string | null;
}

interface AuthContextValue extends AuthState {
  login: (email: string, pin: string) => Promise<void>;
  signup: (params: {
    email: string;
    first_name: string;
    last_name: string;
    pin: string;
    timezone: string;
  }) => Promise<void>;
  logout: () => Promise<void>;
  /** Update a subset of the stored player (e.g. after avatar upload). */
  updatePlayer: (patch: Partial<StoredPlayer>) => void;
  unlockStoredSession: (pin: string) => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function playerFromApiResponse(data: {
  player: { id: string; display_name: string; email?: string | null; role: string; timezone: string; avatar_url?: string | null };
}): StoredPlayer {
  return {
    id: data.player.id,
    displayName: data.player.display_name,
    email: data.player.email ?? null,
    role: data.player.role as 'player' | 'admin',
    timezone: data.player.timezone,
    avatarUrl: data.player.avatar_url ?? null,
  };
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient();
  const initialPlayer = getStoredPlayer();
  const initialRequiresUnlock = !!initialPlayer && !!getRefreshToken() && isAccessTokenExpired();
  const [lockedPlayer, setLockedPlayer] = useState<StoredPlayer | null>(
    initialRequiresUnlock ? initialPlayer : null,
  );
  const [state, setState] = useState<AuthState>({
    player: initialPlayer,
    isLoading: false,
    sessionUnlockRequired: initialRequiresUnlock,
    sessionUnlockError: null,
  });

  const login = useCallback(async (email: string, pin: string) => {
    setState((s) => ({ ...s, isLoading: true }));
    try {
      const resp = await fetch(`${BASE}/api/v1/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, pin }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail ?? 'Login failed');
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
  }, [queryClient]);

  const signup = useCallback(async (params: {
    email: string;
    first_name: string;
    last_name: string;
    pin: string;
    timezone: string;
  }) => {
    setState((s) => ({ ...s, isLoading: true }));
    try {
      const resp = await fetch(`${BASE}/api/v1/auth/signup`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(params),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail ?? 'Signup failed');
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
  }, [queryClient]);

  const logout = useCallback(async () => {
    const { getRefreshToken } = await import('../lib/tokens');
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
      if (access && refresh) storeTokens(access, refresh, updated);
      return { ...s, player: updated };
    });
  }, []);

  const unlockStoredSession = useCallback(async (pin: string) => {
    if (!lockedPlayer) return;
    if (!lockedPlayer.email) {
      const message = 'Please sign in again to refresh this saved session.';
      setState((s) => ({ ...s, isLoading: false, sessionUnlockRequired: true, sessionUnlockError: message }));
      throw new Error(message);
    }

    setState((s) => ({ ...s, isLoading: true, sessionUnlockError: null }));
    try {
      const resp = await fetch(`${BASE}/api/v1/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: lockedPlayer.email, pin }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail ?? 'Invalid PIN');
      }
      const data = await resp.json();
      const player = playerFromApiResponse(data);
      await clearApiCaches();
      queryClient.clear();
      storeTokens(data.access_token, data.refresh_token, player);
      setState({
        player,
        isLoading: false,
        sessionUnlockRequired: false,
        sessionUnlockError: null,
      });
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
  }, [lockedPlayer, queryClient]);

  return (
    <AuthContext.Provider value={{ ...state, login, signup, logout, updatePlayer, unlockStoredSession }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
