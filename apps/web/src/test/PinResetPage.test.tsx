import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import { fireEvent } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { PinResetPage } from '@/pages/PinResetPage';

function renderWithToken(token = 'validtoken') {
  return render(
    <MemoryRouter initialEntries={[`/pin/reset/${token}`]}>
      <Routes>
        <Route path="/pin/reset/:token" element={<PinResetPage />} />
        <Route path="/login" element={<div>Login page</div>} />
        <Route path="/forgot-pin" element={<div>Forgot pin page</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

function fillPin(groupLabel: string, digits: string) {
  const group = screen.getByRole('group', { name: groupLabel });
  for (let i = 0; i < digits.length; i++) {
    fireEvent.change(within(group).getByLabelText(`PIN digit ${i + 1}`), {
      target: { value: digits[i] },
    });
  }
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe('PinResetPage', () => {
  it('renders two PIN inputs and a submit button', () => {
    renderWithToken();
    expect(screen.getByRole('group', { name: 'New PIN' })).toBeTruthy();
    expect(screen.getByRole('group', { name: 'Confirm PIN' })).toBeTruthy();
    expect(screen.getByRole('button', { name: /set new pin/i })).toBeTruthy();
  });

  it('shows error when PINs do not match', async () => {
    vi.stubGlobal('fetch', vi.fn());
    renderWithToken();
    fillPin('New PIN', '1234');
    fillPin('Confirm PIN', '9999');
    fireEvent.click(screen.getByRole('button', { name: /set new pin/i }));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toMatch(/do not match/i));
  });

  it('redirects to /login on success', async () => {
    vi.stubGlobal('fetch', () =>
      Promise.resolve({ ok: true, json: () => Promise.resolve(null) }),
    );
    renderWithToken();
    fillPin('New PIN', '1234');
    fillPin('Confirm PIN', '1234');
    fireEvent.click(screen.getByRole('button', { name: /set new pin/i }));
    await waitFor(() => expect(screen.getByText('Login page')).toBeTruthy());
  });

  it('shows expired state when backend returns expired error', async () => {
    vi.stubGlobal('fetch', () =>
      Promise.resolve({
        ok: false,
        json: () => Promise.resolve({ detail: 'Reset link expired' }),
      }),
    );
    renderWithToken();
    fillPin('New PIN', '1234');
    fillPin('Confirm PIN', '1234');
    fireEvent.click(screen.getByRole('button', { name: /set new pin/i }));
    await waitFor(() => expect(screen.getByText(/link expired/i)).toBeTruthy());
    expect(screen.getByRole('link', { name: /request a new reset link/i })).toBeTruthy();
  });

  it('shows invalid state when backend returns invalid token error', async () => {
    vi.stubGlobal('fetch', () =>
      Promise.resolve({
        ok: false,
        json: () => Promise.resolve({ detail: 'Invalid token' }),
      }),
    );
    renderWithToken();
    fillPin('New PIN', '5678');
    fillPin('Confirm PIN', '5678');
    fireEvent.click(screen.getByRole('button', { name: /set new pin/i }));
    await waitFor(() => expect(screen.getByText(/link invalid/i)).toBeTruthy());
  });
});
