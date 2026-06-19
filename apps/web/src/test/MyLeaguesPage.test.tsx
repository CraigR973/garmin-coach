import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from '@/contexts/AuthContext';
import { LeagueProvider } from '@/contexts/LeagueContext';
import { MyLeaguesPage } from '@/pages/MyLeaguesPage';

const FAKE_JWT = 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJwMSIsImV4cCI6OTk5OTk5OTk5OX0.fake';
const STORED_PLAYER = JSON.stringify({ id: 'p1', displayName: 'Alice', role: 'player', timezone: 'UTC' });

const MOCK_LEAGUE = {
  slug: 'steele-spreadsheet',
  name: 'The Steele Spreadsheet',
  description: null,
  privacy: 'private',
  member_count: 5,
  max_members: null,
  created_at: '2026-01-01T00:00:00Z',
};

const MOCK_LEADERBOARD = [
  { rank: 2, player_id: 'p1', player_name: 'Alice', total_points: 85, match_points: 80, knockout_winner_points: 5, special_points: 0, is_active: true },
  { rank: 1, player_id: 'p2', player_name: 'Bob', total_points: 100, match_points: 95, knockout_winner_points: 5, special_points: 0, is_active: true },
];

function makeQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function stubFetch(extraLeagues: unknown[] = []) {
  vi.stubGlobal('fetch', (url: string) => {
    if (url.includes('/leagues/mine')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve([MOCK_LEAGUE, ...extraLeagues]),
      });
    }
    if (url.includes('/leaderboard')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(MOCK_LEADERBOARD) });
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
  });
}

function stubAuth() {
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => {
      if (k === 'wc2026_player') return STORED_PLAYER;
      if (k === 'wc2026_access') return FAKE_JWT;
      return null;
    },
    setItem: vi.fn(),
    removeItem: vi.fn(),
    clear: vi.fn(),
  });
}

function renderHub() {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <MemoryRouter initialEntries={['/leagues']}>
        <AuthProvider>
          <LeagueProvider>
            <MyLeaguesPage />
          </LeagueProvider>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
  stubAuth();
});

describe('MyLeaguesPage hub', () => {
  it('renders league name and member count', async () => {
    stubFetch();
    renderHub();
    await waitFor(() => expect(screen.getByText('The Steele Spreadsheet')).toBeTruthy());
    expect(screen.getByText(/5 members/)).toBeTruthy();
  });

  it('renders live rank and points for the current player', async () => {
    stubFetch();
    renderHub();
    await waitFor(() =>
      expect(screen.getByTestId('rank-steele-spreadsheet').textContent).toContain('#2'),
    );
    expect(screen.getByTestId('points-steele-spreadsheet').textContent).toContain('85');
  });

  it('shows My Leagues heading', async () => {
    stubFetch();
    renderHub();
    await waitFor(() => expect(screen.getByText('My Leagues')).toBeTruthy());
    expect(screen.getByText(/your league hubs/i)).toBeTruthy();
    await waitFor(() => expect(screen.getAllByText('View →').length).toBeGreaterThanOrEqual(1));
  });

  it('uses a two-column desktop grid for league cards', async () => {
    stubFetch();
    const { container } = renderHub();
    await waitFor(() => expect(screen.getByText('The Steele Spreadsheet')).toBeTruthy());
    expect(container.querySelector('.md\\:grid-cols-2')).toBeTruthy();
  });
});
