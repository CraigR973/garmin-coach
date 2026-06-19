import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from '@/contexts/AuthContext';
import { SettingsPage } from '@/pages/SettingsPage';

// ── Mock browser-specific hooks ───────────────────────────────────────────────

vi.mock('@/hooks/usePushSubscription', () => ({
  usePushSubscription: () => ({
    permission: 'granted',
    isSubscribed: true,
    isLoading: false,
    subscribe: vi.fn(),
    unsubscribe: vi.fn(),
  }),
}));

vi.mock('@/hooks/useInstallPrompt', () => ({
  useInstallPrompt: () => ({
    canInstall: true,
    isInstalled: false,
    isIosSafari: false,
    prompt: vi.fn(),
  }),
}));

// ── Mock Supabase (not used in unit tests; avoids env-var initialisation) ────

vi.mock('@/lib/supabase', () => ({
  supabase: {
    storage: {
      from: () => ({
        upload: vi.fn().mockResolvedValue({ error: null }),
        getPublicUrl: vi.fn().mockReturnValue({ data: { publicUrl: 'https://example.supabase.co/avatars/x.jpg' } }),
      }),
    },
  },
}));

// ── Fixtures ──────────────────────────────────────────────────────────────────

const DEFAULT_PREFS = {
  deadline_warning: true,
  predict_reminder: true,
  pick_confirmation: false,
  match_locked: true,
  result_detected: true,
  leaderboard_shift: true,
  round_complete: true,
  match_postponed: true,
  special_results: true,
  global_mute: false,
  quiet_hours_start: null,
  quiet_hours_end: null,
};

const MUTED_PREFS = { ...DEFAULT_PREFS, global_mute: true };

function makeFetch(prefs = DEFAULT_PREFS, patchResult = DEFAULT_PREFS) {
  return vi.fn((url: string, opts?: RequestInit) => {
    if (url.includes('/api/v1/notifications/preferences') && (!opts?.method || opts.method === 'GET')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(prefs) });
    }
    if (url.includes('/api/v1/notifications/preferences') && opts?.method === 'PATCH') {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(patchResult) });
    }
    if (url.includes('/api/v1/push/test')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ sent: 1 }) });
    }
    // token refresh — return 401 to skip
    return Promise.resolve({ ok: false, status: 401, json: () => Promise.resolve({}) });
  });
}

const FAKE_JWT = 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJwMSIsImV4cCI6OTk5OTk5OTk5OX0.fake';
const STORED_PLAYER = JSON.stringify({
  id: 'p1',
  displayName: 'Alice',
  role: 'player',
  timezone: 'UTC',
});

function makeStorage(initial: Record<string, string> = {}) {
  const values = new Map(Object.entries(initial));
  return {
    getItem: vi.fn((key: string) => values.get(key) ?? null),
    setItem: vi.fn((key: string, value: string) => {
      values.set(key, value);
    }),
    removeItem: vi.fn((key: string) => {
      values.delete(key);
    }),
    clear: vi.fn(() => {
      values.clear();
    }),
  };
}

function renderPage(fetchMock?: ReturnType<typeof makeFetch>) {
  const storage = makeStorage({
    wc2026_player: STORED_PLAYER,
    wc2026_access: FAKE_JWT,
  });
  vi.stubGlobal('localStorage', storage);

  vi.stubGlobal('fetch', fetchMock ?? makeFetch());

  const view = render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <AuthProvider>
          <SettingsPage />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { ...view, storage };
}

beforeEach(() => {
  vi.restoreAllMocks();
  // Stub browser push APIs so PushSection doesn't bail out with "not supported"
  Object.defineProperty(window, 'PushManager', { value: {}, writable: true, configurable: true });
  Object.defineProperty(navigator, 'serviceWorker', { value: {}, writable: true, configurable: true });
});

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('SettingsPage', () => {
  it('renders section headings', async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText('Push Notifications')).toBeInTheDocument();
      expect(screen.getByText('Notification Preferences')).toBeInTheDocument();
      expect(screen.getByText('Install App')).toBeInTheDocument();
    });
  });

  it('shows test push button when subscribed', async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId('test-push-btn')).toBeInTheDocument();
    });
  });

  it('test push button calls POST /api/v1/push/test', async () => {
    const fetch = makeFetch();
    renderPage(fetch);
    await waitFor(() => screen.getByTestId('test-push-btn'));
    fireEvent.click(screen.getByTestId('test-push-btn'));
    await waitFor(() => {
      const testCall = (fetch.mock.calls as [string, RequestInit?][]).find(
        ([url]) => url.includes('/api/v1/push/test'),
      );
      expect(testCall).toBeDefined();
      expect(testCall![1]?.method).toBe('POST');
    });
  });

  it('renders all 9 category toggles', async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByRole('switch', { name: /deadline warning/i })).toBeInTheDocument();
      expect(screen.getByRole('switch', { name: /daily prediction reminder/i })).toBeInTheDocument();
      expect(screen.getByRole('switch', { name: /pick confirmation/i })).toBeInTheDocument();
      expect(screen.getByRole('switch', { name: /predictions locked/i })).toBeInTheDocument();
      expect(screen.getByRole('switch', { name: /match result posted/i })).toBeInTheDocument();
      expect(screen.getByRole('switch', { name: /leaderboard rank/i })).toBeInTheDocument();
      expect(screen.getByRole('switch', { name: /round complete/i })).toBeInTheDocument();
      expect(screen.getByRole('switch', { name: /match postponed/i })).toBeInTheDocument();
      expect(screen.getByRole('switch', { name: /special prediction/i })).toBeInTheDocument();
    });
  });

  it('toggling a category sends PATCH request', async () => {
    const fetch = makeFetch();
    renderPage(fetch);
    await waitFor(() => screen.getByRole('switch', { name: /deadline warning/i }));
    fireEvent.click(screen.getByRole('switch', { name: /deadline warning/i }));
    await waitFor(() => {
      const patchCall = (fetch.mock.calls as [string, RequestInit?][]).find(
        ([url, opts]) => url.includes('/api/v1/notifications/preferences') && opts?.method === 'PATCH',
      );
      expect(patchCall).toBeDefined();
      const body = JSON.parse(patchCall![1]!.body as string);
      expect(body).toHaveProperty('deadline_warning');
    });
  });

  it('renders pick confirmation off by default', async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByRole('switch', { name: /pick confirmation/i })).toHaveAttribute('aria-checked', 'false');
    });
  });

  it('global mute toggle disables category switches', async () => {
    renderPage(makeFetch(MUTED_PREFS));
    await waitFor(() => {
      const deadlineToggle = screen.getByRole('switch', { name: /deadline warning/i });
      expect(deadlineToggle).toBeDisabled();
    });
  });

  it('shows install button when canInstall is true', async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText('Install app')).toBeInTheDocument();
    });
  });

  it('renders the Profile Photo section', async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText('Profile Photo')).toBeInTheDocument();
    });
  });

  it('does not render a passkey unlock setting', async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.queryByRole('switch', { name: /unlock with face id/i })).not.toBeInTheDocument();
    });
  });

  it('shows "Upload photo" button when player has no avatar', async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /upload avatar photo/i })).toBeInTheDocument();
    });
  });

  it('renders "Remove photo" button when player has an avatar', async () => {
    const storedPlayerWithAvatar = JSON.stringify({
      id: 'p1',
      displayName: 'Alice',
      role: 'player',
      timezone: 'UTC',
      avatarUrl: 'https://example.supabase.co/avatars/p1/face.jpg',
    });

    vi.stubGlobal('localStorage', {
      getItem: (k: string) => {
        if (k === 'wc2026_player') return storedPlayerWithAvatar;
        if (k === 'wc2026_access') return FAKE_JWT;
        return null;
      },
      setItem: vi.fn(),
      removeItem: vi.fn(),
      clear: vi.fn(),
    });
    vi.stubGlobal('fetch', makeFetch());

    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter>
          <AuthProvider>
            <SettingsPage />
          </AuthProvider>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /remove avatar photo/i })).toBeInTheDocument();
    });
  });
});
