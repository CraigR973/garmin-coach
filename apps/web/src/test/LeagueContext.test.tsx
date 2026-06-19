import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { LeagueProvider, useLeague } from '@/contexts/LeagueContext';
import { AuthProvider } from '@/contexts/AuthContext';

const FAKE_JWT = 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJwMSIsImV4cCI6OTk5OTk5OTk5OX0.fake';
const STORED_PLAYER = JSON.stringify({ id: 'p1', displayName: 'Alice', role: 'player', timezone: 'UTC' });

const MOCK_LEAGUE = {
  slug: 'steele-spreadsheet',
  name: 'The Steele Spreadsheet',
  description: null,
  privacy: 'private',
  member_count: 2,
  max_members: null,
  created_at: '2026-01-01T00:00:00Z',
};

function makeQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
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

function LeagueDisplay() {
  const { leagues, isLoading } = useLeague();
  if (isLoading) return <div>loading</div>;
  return (
    <div>
      <div data-testid="count">{leagues.length}</div>
      {leagues.map((l) => (
        <div key={l.slug} data-testid={`league-${l.slug}`}>{l.name}</div>
      ))}
    </div>
  );
}

function renderWithLeague(leagues: unknown[]) {
  vi.stubGlobal('fetch', (url: string) => {
    if (url.includes('/leagues/mine')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(leagues) });
    }
    return Promise.reject(new Error('unexpected'));
  });

  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <MemoryRouter>
        <AuthProvider>
          <LeagueProvider>
            <LeagueDisplay />
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

describe('LeagueContext', () => {
  it('loads leagues and exposes them', async () => {
    renderWithLeague([MOCK_LEAGUE]);
    await waitFor(() => expect(screen.getByTestId('count').textContent).toBe('1'));
    expect(screen.getByTestId('league-steele-spreadsheet').textContent).toBe('The Steele Spreadsheet');
  });

  it('shows empty list when no leagues', async () => {
    renderWithLeague([]);
    await waitFor(() => {
      expect(screen.queryByTestId('count')).toBeTruthy();
    });
  });

  it('exposes multiple leagues', async () => {
    const second = { ...MOCK_LEAGUE, slug: 'friends-league', name: 'Friends League' };
    renderWithLeague([MOCK_LEAGUE, second]);
    await waitFor(() => expect(screen.getByTestId('count').textContent).toBe('2'));
  });

  it('useLeague throws when used outside LeagueProvider', () => {
    const ThrowingComponent = () => {
      useLeague();
      return null;
    };
    expect(() =>
      render(
        <MemoryRouter>
          <ThrowingComponent />
        </MemoryRouter>,
      ),
    ).toThrow('useLeague must be used within LeagueProvider');
  });
});
