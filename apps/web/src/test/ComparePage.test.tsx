import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from '@/contexts/AuthContext';
import { LeagueProvider } from '@/contexts/LeagueContext';
import { ComparePage } from '@/pages/ComparePage';

const MOCK_LEAGUE = [{ slug: 'steele-spreadsheet', name: 'The Steele Spreadsheet', description: null, privacy: 'private', member_count: 2, max_members: null, created_at: '2026-01-01T00:00:00Z' }];

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const MY_ID = 'aa000000-0000-0000-0000-000000000001';
const ID_BOB = 'bb000000-0000-0000-0000-000000000001';
const ID_CAR = 'cc000000-0000-0000-0000-000000000001';

const PLAYERS = [
  {
    id: MY_ID,
    display_name: 'Alice',
    role: 'player',
    timezone: 'UTC',
    is_deleted: false,
    created_at: '2026-01-01T00:00:00Z',
  },
  {
    id: ID_BOB,
    display_name: 'Bob',
    role: 'player',
    timezone: 'UTC',
    is_deleted: false,
    created_at: '2026-01-02T00:00:00Z',
  },
  {
    id: ID_CAR,
    display_name: 'Carol',
    role: 'player',
    timezone: 'UTC',
    is_deleted: false,
    created_at: '2026-01-03T00:00:00Z',
  },
];

const H2H_ALICE_BOB = {
  player_a: { id: MY_ID, name: 'Alice' },
  player_b: { id: ID_BOB, name: 'Bob' },
  summary: { player_a_wins: 2, player_b_wins: 1, draws: 1 },
  matches: [
    {
      match_id: 'm1',
      stage: 'group',
      kickoff_utc: '2026-06-14T18:00:00Z',
      home_team_name: 'Brazil',
      away_team_name: 'Germany',
      home_team_flag: '🇧🇷',
      away_team_flag: '🇩🇪',
      actual_home: 2,
      actual_away: 1,
      player_a_predicted_home: 2,
      player_a_predicted_away: 1,
      player_a_points: 10,
      player_b_predicted_home: 1,
      player_b_predicted_away: 1,
      player_b_points: 0,
      winner: 'a',
    },
    {
      match_id: 'm2',
      stage: 'group',
      kickoff_utc: '2026-06-15T18:00:00Z',
      home_team_name: 'France',
      away_team_name: 'Spain',
      home_team_flag: '🇫🇷',
      away_team_flag: '🇪🇸',
      actual_home: 1,
      actual_away: 1,
      player_a_predicted_home: 0,
      player_a_predicted_away: 0,
      player_a_points: 0,
      player_b_predicted_home: 1,
      player_b_predicted_away: 1,
      player_b_points: 10,
      winner: 'b',
    },
    {
      match_id: 'm3',
      stage: 'r16',
      kickoff_utc: '2026-07-01T20:00:00Z',
      home_team_name: 'Argentina',
      away_team_name: 'Portugal',
      home_team_flag: '🇦🇷',
      away_team_flag: '🇵🇹',
      actual_home: 2,
      actual_away: 0,
      player_a_predicted_home: null,
      player_a_predicted_away: null,
      player_a_points: 5,
      player_b_predicted_home: null,
      player_b_predicted_away: null,
      player_b_points: 5,
      winner: 'draw',
    },
  ],
};

const H2H_EMPTY = {
  player_a: { id: MY_ID, name: 'Alice' },
  player_b: { id: ID_CAR, name: 'Carol' },
  summary: { player_a_wins: 0, player_b_wins: 0, draws: 0 },
  matches: [],
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeFetch(h2hPayload: unknown = H2H_ALICE_BOB) {
  return vi.fn((url: string) => {
    if (url.includes('/leagues/mine')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(MOCK_LEAGUE) });
    }
    if (url.endsWith('/players')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(PLAYERS) });
    }
    if (url.includes('/compare/')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(h2hPayload) });
    }
    return Promise.reject(new Error(`Unexpected fetch: ${url}`));
  });
}

function makeQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

const FAKE_JWT = 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJwMSIsImV4cCI6OTk5OTk5OTk5OX0.fake';

function renderPage(initialPath = '/compare', h2hPayload: unknown = H2H_ALICE_BOB) {
  const storedPlayer = JSON.stringify({
    id: MY_ID,
    displayName: 'Alice',
    role: 'player',
    timezone: 'UTC',
  });

  vi.stubGlobal('localStorage', {
    getItem: (k: string) => {
      if (k === 'wc2026_player') return storedPlayer;
      if (k === 'wc2026_access') return FAKE_JWT;
      return null;
    },
    setItem: vi.fn(),
    removeItem: vi.fn(),
    clear: vi.fn(),
  });

  vi.stubGlobal('fetch', makeFetch(h2hPayload));

  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <MemoryRouter initialEntries={[initialPath]}>
        <AuthProvider>
          <LeagueProvider>
            <Routes>
              <Route path="/compare" element={<ComparePage />} />
            </Routes>
          </LeagueProvider>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('ComparePage', () => {
  it('renders the page heading', () => {
    renderPage();
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Head-to-Head');
  });

  it('shows an empty state when no second player is picked', async () => {
    renderPage();
    await waitFor(() => {
      // Player list has loaded (Alice + Bob + Carol)
      expect(screen.getAllByText('Alice').length).toBeGreaterThanOrEqual(1);
    });
    expect(
      screen.getByText(/Select two players/i),
    ).toBeInTheDocument();
  });

  it('renders comparison when both players are in URL', async () => {
    renderPage(`/compare?a=${MY_ID}&b=${ID_BOB}`);
    await waitFor(() => {
      // Summary numbers
      expect(screen.getByText('2', { selector: '.font-display' })).toBeInTheDocument();
    });
    // Two "1"s appear: B wins (1) and draws (1)
    const ones = screen.getAllByText('1', { selector: '.font-display' });
    expect(ones.length).toBeGreaterThanOrEqual(2);

    // Match teams appear
    expect(screen.getByText(/Brazil/)).toBeInTheDocument();
    expect(screen.getByText(/Germany/)).toBeInTheDocument();
    expect(screen.getByText(/France/)).toBeInTheDocument();
  });

  it('highlights the winning side per match', async () => {
    renderPage(`/compare?a=${MY_ID}&b=${ID_BOB}`);
    await waitFor(() => {
      expect(screen.getByText(/Brazil/)).toBeInTheDocument();
    });

    const aCells = screen.getAllByTestId('player-a-cell');
    const bCells = screen.getAllByTestId('player-b-cell');

    expect(aCells).toHaveLength(3);
    expect(bCells).toHaveLength(3);

    // Match 1 — A wins
    expect(aCells[0].className).toMatch(/bg-primary\/10/);
    expect(bCells[0].className).not.toMatch(/bg-primary\/10/);

    // Match 2 — B wins
    expect(aCells[1].className).not.toMatch(/bg-primary\/10/);
    expect(bCells[1].className).toMatch(/bg-primary\/10/);

    // Match 3 — draw, neither highlighted
    expect(aCells[2].className).not.toMatch(/bg-primary\/10/);
    expect(bCells[2].className).not.toMatch(/bg-primary\/10/);
  });

  it('shows summary counts correctly', async () => {
    renderPage(`/compare?a=${MY_ID}&b=${ID_BOB}`);
    await waitFor(() => {
      expect(screen.getByText(/Brazil/)).toBeInTheDocument();
    });

    // Summary bar has 3 columns; A name appears in summary, picker option, and match column header
    const aliceMatches = screen.getAllByText('Alice');
    expect(aliceMatches.length).toBeGreaterThanOrEqual(2);

    const bobMatches = screen.getAllByText('Bob');
    expect(bobMatches.length).toBeGreaterThanOrEqual(2);
  });

  it('renders zero-match empty state when no settled matches in common', async () => {
    renderPage(`/compare?a=${MY_ID}&b=${ID_CAR}`, H2H_EMPTY);
    await waitFor(() => {
      expect(
        screen.getByText(/No settled matches in common yet/i),
      ).toBeInTheDocument();
    });
  });

  it('renders the actual score per match', async () => {
    renderPage(`/compare?a=${MY_ID}&b=${ID_BOB}`);
    await waitFor(() => {
      expect(screen.getByText(/actual 2–1/)).toBeInTheDocument();
      expect(screen.getByText(/actual 1–1/)).toBeInTheDocument();
      expect(screen.getByText(/actual 2–0/)).toBeInTheDocument();
    });
  });

  it('renders predicted scores in each player column', async () => {
    renderPage(`/compare?a=${MY_ID}&b=${ID_BOB}`);
    await waitFor(() => {
      expect(screen.getByText(/Brazil/)).toBeInTheDocument();
    });

    // First match — A: 2-1, B: 1-1
    const aCells = screen.getAllByTestId('player-a-cell');
    expect(within(aCells[0]).getByText('2–1')).toBeInTheDocument();
    expect(within(aCells[0]).getByText(/10/)).toBeInTheDocument();

    const bCells = screen.getAllByTestId('player-b-cell');
    expect(within(bCells[0]).getByText('1–1')).toBeInTheDocument();
    expect(within(bCells[0]).getByText(/^0$/)).toBeInTheDocument();
  });

  it('handles knockout predictions (no predicted score) gracefully', async () => {
    renderPage(`/compare?a=${MY_ID}&b=${ID_BOB}`);
    await waitFor(() => {
      expect(screen.getByText(/Argentina/)).toBeInTheDocument();
    });

    // R16 match — both predictions show as em-dash
    const aCells = screen.getAllByTestId('player-a-cell');
    expect(within(aCells[2]).getByText('—')).toBeInTheDocument();
  });
});
