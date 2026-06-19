import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { FirstRunController } from '@/components/FirstRunController';
import { useAuth } from '@/contexts/AuthContext';

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: vi.fn(),
}));

// Stub the launchpad with a button that mirrors the real close contract:
// it marks its own latch and then calls onClose (where the controller writes
// the per-user tour-seen key).
vi.mock('@/components/FirstRunLaunchpad', () => ({
  FirstRunLaunchpad: ({ onClose }: { onClose: () => void }) => (
    <button
      type="button"
      onClick={() => {
        localStorage.setItem('sss_firstrun_launchpad_seen', '1');
        onClose();
      }}
    >
      close-launchpad
    </button>
  ),
}));

const mockedUseAuth = vi.mocked(useAuth);
const player = {
  id: 'p1',
  displayName: 'Alice',
  role: 'player' as const,
  timezone: 'UTC',
  avatarUrl: null,
};

const baseAuth = {
  player,
  isLoading: false,
  sessionUnlockRequired: false,
  sessionUnlockError: null,
  login: vi.fn(),
  signup: vi.fn(),
  logout: vi.fn(),
  updatePlayer: vi.fn(),
  unlockStoredSession: vi.fn(),
};

/** Captures the current location so we can assert there is no forced redirect. */
function LocationDisplay() {
  const loc = useLocation();
  return <span data-testid="location">{loc.pathname}</span>;
}

function renderController(initialPath = '/') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <LocationDisplay />
      <Routes>
        <Route path="*" element={<FirstRunController />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  localStorage.clear();
  mockedUseAuth.mockReturnValue({ ...baseAuth });
});

describe('FirstRunController', () => {
  it('shows the launchpad to a brand-new user instead of redirecting to /about', async () => {
    renderController('/');
    await act(async () => {});

    expect(screen.getByRole('button', { name: 'close-launchpad' })).toBeTruthy();
    // No forced navigation — the user stays where they landed.
    expect(screen.getByTestId('location').textContent).toBe('/');
  });

  it('marks the tour seen on close so the launchpad never shows again', async () => {
    renderController('/');
    await act(async () => {});

    fireEvent.click(screen.getByRole('button', { name: 'close-launchpad' }));

    expect(localStorage.getItem('sss_tour_seen_p1')).toBe('1');
    expect(screen.queryByRole('button', { name: 'close-launchpad' })).toBeNull();
  });

  it('does not show the launchpad while a session unlock is required', async () => {
    mockedUseAuth.mockReturnValue({ ...baseAuth, sessionUnlockRequired: true });
    renderController('/');
    await act(async () => {});

    expect(screen.queryByRole('button', { name: 'close-launchpad' })).toBeNull();
  });

  it('renders nothing for a returning user who has already seen it (per-user key)', () => {
    localStorage.setItem('sss_tour_seen_p1', '1');
    renderController('/');

    expect(screen.queryByRole('button', { name: 'close-launchpad' })).toBeNull();
  });

  it('still respects the legacy global tour-seen key for pre-U49 users', () => {
    localStorage.setItem('sss_tour_seen', '1');
    renderController('/');

    expect(screen.queryByRole('button', { name: 'close-launchpad' })).toBeNull();
  });
});
