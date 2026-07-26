import React, { createContext, useCallback, useContext, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { clearPersistedCache } from '../lib/queryClient';
import {
  clearApiCaches,
  clearTokens,
  getDeviceToken,
  getStoredPlayer,
  storeDeviceToken,
  type StoredPlayer,
} from '../lib/tokens';

// Empty/unset in production = same-origin (requests go through Vercel proxy rewrite).
const BASE = import.meta.env.VITE_API_URL ?? (import.meta.env.PROD ? '' : 'http://localhost:8000');

interface AuthState {
  player: StoredPlayer | null;
  isLoading: boolean;
}

interface AuthContextValue extends AuthState {
  activateDevice: (code: string) => Promise<void>;
  logout: () => Promise<void>;
  updatePlayer: (patch: Partial<StoredPlayer>) => void;
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
  const deviceToken = getDeviceToken();
  const initialPlayer = deviceToken ? getStoredPlayer() : null;
  const [state, setState] = useState<AuthState>({
    player: initialPlayer,
    isLoading: false,
  });

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
        clearPersistedCache();
        storeDeviceToken(data.device_token, player);
        setState({ player, isLoading: false });
      } catch (err) {
        setState((s) => ({ ...s, isLoading: false }));
        throw err;
      }
    },
    [queryClient],
  );

  const logout = useCallback(async () => {
    const token = getDeviceToken();
    if (token) {
      await fetch(`${BASE}/api/v1/auth/revoke`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      }).catch(() => {});
    }
    await clearTokens();
    queryClient.clear();
    clearPersistedCache();
    setState({ player: null, isLoading: false });
  }, [queryClient]);

  const updatePlayer = useCallback((patch: Partial<StoredPlayer>) => {
    setState((s) => {
      if (!s.player) return s;
      const updated = { ...s.player, ...patch };
      const token = getDeviceToken();
      if (token) storeDeviceToken(token, updated);
      return { ...s, player: updated };
    });
  }, []);

  return (
    <AuthContext.Provider value={{ ...state, activateDevice, logout, updatePlayer }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
