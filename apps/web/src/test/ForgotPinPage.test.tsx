import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { ForgotPinPage } from '@/pages/ForgotPinPage';

function renderPage() {
  return render(
    <MemoryRouter>
      <ForgotPinPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe('ForgotPinPage', () => {
  it('renders an email input and submit button', () => {
    renderPage();
    expect(screen.getByLabelText(/email/i)).toBeTruthy();
    expect(screen.getByRole('button', { name: /send reset link/i })).toBeTruthy();
  });

  it('shows confirmation message after successful request', async () => {
    vi.stubGlobal('fetch', () =>
      Promise.resolve({ ok: true, json: () => Promise.resolve({ message: 'ok' }) }),
    );
    renderPage();
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'user@example.com' } });
    fireEvent.click(screen.getByRole('button', { name: /send reset link/i }));
    await waitFor(() =>
      expect(screen.getByText(/check your inbox/i)).toBeTruthy(),
    );
  });

  it('shows error message on failed request', async () => {
    vi.stubGlobal('fetch', () =>
      Promise.resolve({
        ok: false,
        json: () => Promise.resolve({ detail: 'Rate limited' }),
      }),
    );
    renderPage();
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'user@example.com' } });
    fireEvent.click(screen.getByRole('button', { name: /send reset link/i }));
    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy());
    expect(screen.getByRole('alert').textContent).toMatch(/rate limited/i);
  });

  it('has a back to sign in link', () => {
    renderPage();
    expect(screen.getByRole('link', { name: /back to sign in/i })).toBeTruthy();
  });
});
