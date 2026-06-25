import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { ActivatePage } from './ActivatePage';

const activateDeviceMock = vi.fn(() => Promise.resolve());

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({ activateDevice: activateDeviceMock }),
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => vi.fn(),
  };
});

describe('ActivatePage', () => {
  beforeEach(() => {
    activateDeviceMock.mockClear();
  });

  it('activates from query parameter code', async () => {
    window.history.pushState({}, '', '/activate?code=abc123');
    render(
      <MemoryRouter initialEntries={['/activate?code=abc123']}>
        <ActivatePage />
      </MemoryRouter>,
    );

    await waitFor(() => expect(activateDeviceMock).toHaveBeenCalledWith('abc123'));
    expect(screen.queryByText(/Activation failed/i)).toBeNull();
  });

  it('activates from hash fragment code', async () => {
    window.history.pushState({}, '', '/activate#code=xyz789');
    render(
      <MemoryRouter initialEntries={['/activate#code=xyz789']}>
        <ActivatePage />
      </MemoryRouter>,
    );

    await waitFor(() => expect(activateDeviceMock).toHaveBeenCalledWith('xyz789'));
    expect(screen.queryByText(/Activation failed/i)).toBeNull();
  });

  it('uses stored pending activation code when launched from installed app', async () => {
    window.localStorage.setItem('coach_pending_activation_code', 'stored-abc');
    window.history.pushState({}, '', '/activate');

    render(
      <MemoryRouter initialEntries={['/activate']}>
        <ActivatePage />
      </MemoryRouter>,
    );

    await waitFor(() => expect(activateDeviceMock).toHaveBeenCalledWith('stored-abc'));
    expect(screen.queryByText(/Activation failed/i)).toBeNull();
  });
});
