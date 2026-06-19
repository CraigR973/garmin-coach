import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from '@/contexts/AuthContext';
import { ProtectedRoute } from '@/components/ProtectedRoute';

// Expired JWT (exp=1, i.e. 1970) so isAccessTokenExpiringSoon() = true and the PIN gate fires.
const FAKE_JWT = 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJwMSIsImV4cCI6MX0.fake';
const STORED_PLAYER = JSON.stringify({
  id: 'p1',
  displayName: 'Alice',
  email: 'alice@example.com',
  role: 'player',
  timezone: 'UTC',
});

function makeStorage() {
  const values = new Map([
    ['wc2026_player', STORED_PLAYER],
    ['wc2026_access', FAKE_JWT],
    ['wc2026_refresh', 'refresh-token'],
  ]);

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

function fillPin(digits: string) {
  for (let i = 0; i < digits.length; i++) {
    fireEvent.change(screen.getByLabelText(`PIN digit ${i + 1}`), {
      target: { value: digits[i] },
    });
  }
}

function renderProtectedApp(fetchMock: ReturnType<typeof vi.fn>) {
  vi.stubGlobal('fetch', fetchMock);
  vi.stubGlobal('caches', { delete: vi.fn().mockResolvedValue(true) });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/']}>
        <AuthProvider>
          <Routes>
            <Route element={<ProtectedRoute />}>
              <Route path="/" element={<div>Authed content</div>} />
            </Route>
            <Route path="/login" element={<div>PIN login</div>} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
  vi.stubGlobal('localStorage', makeStorage());
});

describe('PIN re-lock gate', () => {
  it('keeps authed content hidden until the stored account PIN succeeds', async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            access_token: 'new-access',
            refresh_token: 'new-refresh',
            player: {
              id: 'p1',
              display_name: 'Alice',
              email: 'alice@example.com',
              role: 'player',
              timezone: 'UTC',
              avatar_url: 'https://example.supabase.co/avatars/p1/face.jpg',
            },
          }),
      }),
    );

    renderProtectedApp(fetchMock);

    expect(screen.queryByText('Authed content')).not.toBeInTheDocument();
    expect(screen.getByText(/signed in as/i)).toHaveTextContent(/Alice/);
    expect(screen.getByRole('button', { name: /log out/i })).toBeInTheDocument();

    fillPin('1234');
    fireEvent.click(screen.getByRole('button', { name: /unlock with pin/i }));

    await waitFor(() => {
      expect(screen.getByText('Authed content')).toBeInTheDocument();
    });
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/v1/auth/login'),
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ email: 'alice@example.com', pin: '1234' }),
      }),
    );
  });

  it('rejects a wrong PIN and keeps protected content hidden', async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve({
        ok: false,
        json: () => Promise.resolve({ detail: 'Invalid credentials' }),
      }),
    );

    renderProtectedApp(fetchMock);

    fillPin('9999');
    fireEvent.click(screen.getByRole('button', { name: /unlock with pin/i }));

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(/invalid pin/i);
      expect(screen.queryByText('Authed content')).not.toBeInTheDocument();
    });
  });
});
