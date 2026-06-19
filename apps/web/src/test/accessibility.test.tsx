import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { axe } from 'jest-axe';
import { AuthProvider } from '@/contexts/AuthContext';
import { LoginPage } from '@/pages/LoginPage';
import { TopBar } from '@/components/TopBar';
import { SettingsPage } from '@/pages/SettingsPage';

// Disable color-contrast: jsdom cannot evaluate CSS custom properties.
// All other axe rules run at full severity.
const AXE_CONFIG = {
  rules: { 'color-contrast': { enabled: false } },
};

// ---------------------------------------------------------------------------
// Shared auth fixtures
// ---------------------------------------------------------------------------

const FAKE_JWT = 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJwMSIsImV4cCI6OTk5OTk5OTk5OX0.fake';
const STORED_PLAYER = JSON.stringify({
  id: 'p1',
  displayName: 'Alice',
  role: 'player',
  timezone: 'UTC',
});

function stubAuth() {
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => {
      if (k === 'wc2026_player') return STORED_PLAYER;
      if (k === 'wc2026_access') return FAKE_JWT;
      return null;
    },
    setItem: vi.fn(),
    removeItem: vi.fn(),
    clear: vi.fn(),
  });
}

function makeQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

// ---------------------------------------------------------------------------
// LoginPage
// ---------------------------------------------------------------------------

vi.mock('@/hooks/usePushSubscription', () => ({
  usePushSubscription: () => ({
    permission: 'default',
    isSubscribed: false,
    isLoading: false,
    subscribe: vi.fn(),
    unsubscribe: vi.fn(),
  }),
}));

vi.mock('@/hooks/useInstallPrompt', () => ({
  useInstallPrompt: () => ({
    canInstall: false,
    isInstalled: false,
    isIosSafari: false,
    prompt: vi.fn(),
  }),
}));

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

beforeEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe('Accessibility — LoginPage', () => {
  it('has no axe violations on initial render (text input fallback)', async () => {
    vi.stubGlobal('fetch', () => Promise.resolve({ ok: false }));
    const { container } = render(
      <QueryClientProvider client={makeQueryClient()}>
        <MemoryRouter>
          <AuthProvider>
            <LoginPage />
          </AuthProvider>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await new Promise((r) => setTimeout(r, 50));
    const results = await axe(container, AXE_CONFIG);
    expect(results).toHaveNoViolations();
  });

  it('has no axe violations on the email+PIN form', async () => {
    const { container } = render(
      <QueryClientProvider client={makeQueryClient()}>
        <MemoryRouter>
          <AuthProvider>
            <LoginPage />
          </AuthProvider>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await new Promise((r) => setTimeout(r, 50));
    const results = await axe(container, AXE_CONFIG);
    expect(results).toHaveNoViolations();
  });
});

// ---------------------------------------------------------------------------
// NavBar
// ---------------------------------------------------------------------------

describe('Accessibility — TopBar', () => {
  it('has no axe violations', async () => {
    stubAuth();
    vi.stubGlobal('fetch', () => Promise.resolve({ ok: false, status: 401, json: () => Promise.resolve({}) }));
    const { container } = render(
      <QueryClientProvider client={makeQueryClient()}>
        <MemoryRouter>
          <AuthProvider>
            <TopBar />
          </AuthProvider>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    const results = await axe(container, AXE_CONFIG);
    expect(results).toHaveNoViolations();
  });

  it('nav has an accessible label', () => {
    stubAuth();
    vi.stubGlobal('fetch', () => Promise.resolve({ ok: false, status: 401, json: () => Promise.resolve({}) }));
    const { container } = render(
      <QueryClientProvider client={makeQueryClient()}>
        <MemoryRouter>
          <AuthProvider>
            <TopBar />
          </AuthProvider>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    const nav = container.querySelector('nav');
    expect(nav?.getAttribute('aria-label')).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// SettingsPage
// ---------------------------------------------------------------------------

describe('Accessibility — SettingsPage', () => {
  function renderSettings() {
    stubAuth();
    vi.stubGlobal('fetch', (url: string, opts?: RequestInit) => {
      if (url.includes('/api/v1/notifications/preferences') && (!opts?.method || opts.method === 'GET')) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
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
            }),
        });
      }
      return Promise.resolve({ ok: false, status: 401, json: () => Promise.resolve({}) });
    });
    Object.defineProperty(window, 'PushManager', { value: {}, writable: true, configurable: true });
    Object.defineProperty(navigator, 'serviceWorker', { value: {}, writable: true, configurable: true });
    return render(
      <QueryClientProvider client={makeQueryClient()}>
        <MemoryRouter>
          <AuthProvider>
            <SettingsPage />
          </AuthProvider>
        </MemoryRouter>
      </QueryClientProvider>,
    );
  }

  it('has no axe violations', async () => {
    const { container } = renderSettings();
    await waitFor(() => expect(container.querySelector('[role="switch"]')).toBeTruthy());
    const results = await axe(container, AXE_CONFIG);
    expect(results).toHaveNoViolations();
  });

  it('toggle switches have aria-checked and aria-label', async () => {
    const { container } = renderSettings();
    await waitFor(() => expect(container.querySelector('[role="switch"]')).toBeTruthy());
    const switches = container.querySelectorAll('[role="switch"]');
    expect(switches.length).toBeGreaterThan(0);
    switches.forEach((sw) => {
      expect(sw.getAttribute('aria-checked')).toMatch(/^(true|false)$/);
      expect(sw.getAttribute('aria-label')).toBeTruthy();
    });
  });
});
