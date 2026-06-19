import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { LoginPage } from '@/pages/LoginPage';
import { AuthProvider } from '@/contexts/AuthContext';

function renderLogin() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <AuthProvider>
          <LoginPage />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function fillPin(digits: string) {
  for (let i = 0; i < digits.length; i++) {
    fireEvent.change(screen.getByLabelText(`PIN digit ${i + 1}`), {
      target: { value: digits[i] },
    });
  }
}

beforeEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe('LoginPage', () => {
  it('shows an email input field', () => {
    renderLogin();
    expect(screen.getByLabelText(/email/i)).toBeTruthy();
  });

  it('shows a PIN input', () => {
    renderLogin();
    expect(screen.getByLabelText(/pin digit 1/i)).toBeTruthy();
  });

  it('shows a sign up link', () => {
    renderLogin();
    expect(screen.getByRole('link', { name: /create account/i })).toBeTruthy();
  });

  it('shows the value-proposition tagline', () => {
    renderLogin();
    expect(screen.getByText(/predict once, compete everywhere/i)).toBeTruthy();
  });

  it('shows generic error even on locked account response (lockout removed)', async () => {
    vi.stubGlobal('fetch', () =>
      Promise.resolve({
        ok: false,
        json: () =>
          Promise.resolve({ detail: 'Account temporarily locked — try again later' }),
      }),
    );

    renderLogin();
    const emailInput = screen.getByLabelText(/email/i);
    fireEvent.change(emailInput, { target: { value: 'alice@example.com' } });
    fireEvent.change(screen.getByLabelText('PIN digit 1'), { target: { value: '1' } });
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }));

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeTruthy();
    });
    expect(screen.getByRole('alert').textContent).toMatch(/invalid email or pin/i);
  });

  it('shows generic error on invalid credentials', async () => {
    vi.stubGlobal('fetch', () =>
      Promise.resolve({
        ok: false,
        json: () => Promise.resolve({ detail: 'INVALID_CREDENTIALS' }),
      }),
    );

    renderLogin();
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'alice@example.com' } });
    fireEvent.change(screen.getByLabelText('PIN digit 1'), { target: { value: '1' } });
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }));

    await waitFor(() => {
      expect(screen.getByRole('alert').textContent).toMatch(/invalid email or pin/i);
    });
  });

  it('clears API caches on successful login before the new identity is used', async () => {
    const cachesDelete = vi.fn().mockResolvedValue(true);
    vi.stubGlobal('caches', { delete: cachesDelete });
    vi.stubGlobal('fetch', () =>
      Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            access_token: 'access-token',
            refresh_token: 'refresh-token',
            player: {
              id: 'p1',
              display_name: 'Alice',
              email: 'alice@example.com',
              role: 'player',
              timezone: 'Europe/London',
              avatar_url: null,
            },
          }),
      }),
    );

    renderLogin();
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'alice@example.com' } });
    fillPin('1234');
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }));

    await waitFor(() => {
      expect(cachesDelete).toHaveBeenCalledWith('api-user-data');
      expect(cachesDelete).toHaveBeenCalledWith('api-matches');
    });
    expect(localStorage.getItem('wc2026_player')).toContain('alice@example.com');
  });
});
