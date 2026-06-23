import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { LoginPage } from './LoginPage';

const loginMock = vi.fn();

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({ login: loginMock }),
}));

function renderLogin() {
  return render(
    <MemoryRouter>
      <LoginPage />
    </MemoryRouter>,
  );
}

describe('LoginPage', () => {
  it('leads with the invite screen and hides the PIN form by default', () => {
    renderLogin();
    expect(screen.getByText(/ask Craig for an activation link/i)).toBeTruthy();
    // The PIN fallback form is not rendered until requested.
    expect(screen.queryByLabelText('Name')).toBeNull();
  });

  it('reveals the PIN fallback form on demand', async () => {
    const user = userEvent.setup();
    renderLogin();
    await user.click(screen.getByRole('button', { name: /use a pin instead/i }));
    expect(screen.getByLabelText('Name')).toBeTruthy();
    expect(screen.getByRole('button', { name: /sign in/i })).toBeTruthy();
  });
});
