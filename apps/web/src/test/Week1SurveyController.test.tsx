import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Week1SurveyController } from '@/components/Week1SurveyController';
import { useAuth } from '@/contexts/AuthContext';
import * as surveyLib from '@/lib/survey';

vi.mock('@/contexts/AuthContext', () => ({ useAuth: vi.fn() }));
vi.mock('@/lib/survey', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/survey')>();
  return { ...actual, fetchSurveyStatus: vi.fn(), submitSurvey: vi.fn() };
});

const mockedUseAuth = vi.mocked(useAuth);
const mockedFetchStatus = vi.mocked(surveyLib.fetchSurveyStatus);

const player = {
  id: 'p1',
  displayName: 'Alice',
  email: null,
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

function renderController() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <Week1SurveyController />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  vi.clearAllMocks();
  mockedUseAuth.mockReturnValue({ ...baseAuth });
  // Past first-run so the survey isn't gated behind the launchpad.
  localStorage.setItem('sss_tour_seen_p1', '1');
});

describe('Week1SurveyController', () => {
  it('shows the survey to a logged-in player who has not completed it', async () => {
    mockedFetchStatus.mockResolvedValue({ completed: false });
    renderController();
    expect(await screen.findByText(/one week in/i)).toBeTruthy();
  });

  it('does not show when the player has already completed it', async () => {
    mockedFetchStatus.mockResolvedValue({ completed: true });
    renderController();
    await waitFor(() => expect(mockedFetchStatus).toHaveBeenCalled());
    expect(screen.queryByText(/one week in/i)).toBeNull();
  });

  it('stays hidden when the status response is unexpected (defensive)', async () => {
    // Mirrors the e2e catch-all, which fulfils unmocked /api routes with [].
    mockedFetchStatus.mockResolvedValue([] as unknown as { completed: boolean });
    renderController();
    await waitFor(() => expect(mockedFetchStatus).toHaveBeenCalled());
    expect(screen.queryByText(/one week in/i)).toBeNull();
  });

  it('renders nothing and skips the request when no player is logged in', () => {
    mockedUseAuth.mockReturnValue({ ...baseAuth, player: null });
    renderController();
    expect(screen.queryByText(/one week in/i)).toBeNull();
    expect(mockedFetchStatus).not.toHaveBeenCalled();
  });

  it('does not show (or fetch) when snoozed this session', async () => {
    sessionStorage.setItem('sss_survey_week1_snoozed', '1');
    mockedFetchStatus.mockResolvedValue({ completed: false });
    renderController();
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByText(/one week in/i)).toBeNull();
    expect(mockedFetchStatus).not.toHaveBeenCalled();
  });

  it('snoozes when "Later" is clicked and hides the survey', async () => {
    mockedFetchStatus.mockResolvedValue({ completed: false });
    renderController();
    const later = await screen.findByRole('button', { name: /later/i });
    fireEvent.click(later);
    expect(sessionStorage.getItem('sss_survey_week1_snoozed')).toBe('1');
    await waitFor(() => expect(screen.queryByText(/one week in/i)).toBeNull());
  });
});
