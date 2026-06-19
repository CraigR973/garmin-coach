import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import { fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { SignupPage } from '@/pages/SignupPage';
import { AuthProvider } from '@/contexts/AuthContext';

function renderSignup() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <AuthProvider>
          <SignupPage />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function fillPin(group: HTMLElement, digits: string) {
  for (let i = 0; i < digits.length; i++) {
    fireEvent.change(within(group).getByLabelText(`PIN digit ${i + 1}`), {
      target: { value: digits[i] },
    });
  }
}

beforeEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe('SignupPage', () => {
  it('renders email, first name, last name, timezone, PIN, confirm PIN fields', () => {
    renderSignup();
    expect(screen.getByLabelText(/email/i)).toBeTruthy();
    expect(screen.getByLabelText(/first name/i)).toBeTruthy();
    expect(screen.getByLabelText(/last name/i)).toBeTruthy();
    expect(screen.getByLabelText(/timezone/i)).toBeTruthy();
    expect(screen.getByRole('group', { name: 'PIN' })).toBeTruthy();
    expect(screen.getByRole('group', { name: 'Confirm PIN' })).toBeTruthy();
  });

  it('shows pin mismatch error when PINs differ', async () => {
    vi.stubGlobal('fetch', vi.fn());
    renderSignup();
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'alice@example.com' } });
    fireEvent.change(screen.getByLabelText(/first name/i), { target: { value: 'Alice' } });
    fireEvent.change(screen.getByLabelText(/last name/i), { target: { value: 'Smith' } });
    const entryGroup = screen.getByRole('group', { name: 'PIN' });
    const confirmGroup = screen.getByRole('group', { name: 'Confirm PIN' });
    fillPin(entryGroup, '1234');
    fillPin(confirmGroup, '9999');
    fireEvent.click(screen.getByRole('button', { name: /create account/i }));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toMatch(/do not match/i));
  });

  it('shows error when email already exists', async () => {
    vi.stubGlobal('fetch', () =>
      Promise.resolve({
        ok: false,
        json: () => Promise.resolve({ detail: 'Email already registered' }),
      }),
    );
    renderSignup();
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'alice@example.com' } });
    fireEvent.change(screen.getByLabelText(/first name/i), { target: { value: 'Alice' } });
    fireEvent.change(screen.getByLabelText(/last name/i), { target: { value: 'Smith' } });
    const entryGroup = screen.getByRole('group', { name: 'PIN' });
    const confirmGroup = screen.getByRole('group', { name: 'Confirm PIN' });
    fillPin(entryGroup, '1234');
    fillPin(confirmGroup, '1234');
    fireEvent.click(screen.getByRole('button', { name: /create account/i }));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toMatch(/already exists/i));
  });

  it('has a link back to login', () => {
    renderSignup();
    expect(screen.getByRole('link', { name: /sign in/i })).toBeTruthy();
  });
});
