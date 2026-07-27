import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AccessPage } from './AccessPage';

const activateDeviceMock = vi.fn(() => Promise.resolve());
const navigateMock = vi.fn();

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({ activateDevice: activateDeviceMock, isLoading: false }),
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => navigateMock,
  };
});

describe('AccessPage', () => {
  beforeEach(() => {
    activateDeviceMock.mockClear();
    activateDeviceMock.mockResolvedValue(undefined);
    navigateMock.mockClear();
  });

  it('offers in-app device activation without a PIN fallback', () => {
    render(<AccessPage />);

    expect(screen.getByTestId('logomark')).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Set up this device' })).toBeTruthy();
    expect(screen.getByText(/one-time activation link/i)).toBeTruthy();
    expect(screen.getByLabelText(/activation link or code/i)).toBeTruthy();
    expect(screen.queryByLabelText('PIN')).toBeNull();
    expect(screen.queryByRole('button', { name: /sign in/i })).toBeNull();
  });

  it('activates from a pasted full link and routes to the dashboard', async () => {
    render(<AccessPage />);

    fireEvent.change(screen.getByLabelText(/activation link or code/i), {
      target: { value: 'https://garmin-coach-one.vercel.app/activate?code=link-code' },
    });
    fireEvent.click(screen.getByRole('button', { name: /activate this device/i }));

    await waitFor(() => expect(activateDeviceMock).toHaveBeenCalledWith('link-code'));
    await waitFor(() => expect(navigateMock).toHaveBeenCalledWith('/', { replace: true }));
  });

  it('activates from a bare pasted code', async () => {
    render(<AccessPage />);

    fireEvent.change(screen.getByLabelText(/activation link or code/i), {
      target: { value: 'bare-code-123' },
    });
    fireEvent.click(screen.getByRole('button', { name: /activate this device/i }));

    await waitFor(() => expect(activateDeviceMock).toHaveBeenCalledWith('bare-code-123'));
  });

  it('surfaces a retryable error and stays on setup when activation fails', async () => {
    activateDeviceMock.mockRejectedValueOnce(new Error('This activation link has expired.'));
    render(<AccessPage />);

    fireEvent.change(screen.getByLabelText(/activation link or code/i), {
      target: { value: 'expired-code' },
    });
    fireEvent.click(screen.getByRole('button', { name: /activate this device/i }));

    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('expired'));
    expect(navigateMock).not.toHaveBeenCalled();
  });
});
