import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from '@/contexts/AuthContext';
import { SchedulePage } from '@/pages/SchedulePage';

// ---------------------------------------------------------------------------
// Fixtures — one group match (with teams) + seeded knockout matches whose
// teams are still TBD (placeholder source refs only).
// ---------------------------------------------------------------------------

const GROUP_MATCH = {
  id: 'mg1',
  match_number: 1,
  stage: 'group',
  group_id: 'ga',
  home_team: { id: 't1', name: 'Mexico', code: 'MEX', flag_emoji: '🇲🇽' },
  away_team: { id: 't2', name: 'South Africa', code: 'RSA', flag_emoji: '🇿🇦' },
  home_team_placeholder: null,
  away_team_placeholder: null,
  kickoff_utc: '2026-06-11T19:00:00Z',
  venue: 'Estadio Azteca, Mexico City',
  status: 'scheduled',
  actual_home_score: null,
  actual_away_score: null,
  extra_time: false,
  penalties: false,
  postponed_reason: null,
};

const R32_MATCH = {
  id: 'm73',
  match_number: 73,
  stage: 'r32',
  group_id: null,
  home_team: null,
  away_team: null,
  home_team_placeholder: 'Winner Group A',
  away_team_placeholder: 'Best 3rd #1',
  kickoff_utc: '2026-06-28T19:00:00Z',
  venue: 'Estadio Azteca, Mexico City',
  status: 'scheduled',
  actual_home_score: null,
  actual_away_score: null,
  extra_time: false,
  penalties: false,
  postponed_reason: null,
};

const R16_MATCH = {
  ...R32_MATCH,
  id: 'm89',
  match_number: 89,
  stage: 'r16',
  home_team_placeholder: 'Winner of Match 73',
  away_team_placeholder: 'Winner of Match 74',
  kickoff_utc: '2026-07-04T18:00:00Z',
};

function makeFetch(matches: unknown[]) {
  return vi.fn((url: string) => {
    if (url.includes('/api/v1/matches')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(matches) });
    }
    if (url.includes('/api/v1/predictions/me')) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve([
            {
              id: 'p1',
              player_id: 'player-1',
              match_id: 'mg1',
              predicted_home: 2,
              predicted_away: 1,
              submitted_at: null,
              update_count: 1,
              points_awarded: null,
              points_breakdown: null,
              updated_at: '2026-06-01T00:00:00Z',
            },
          ]),
      });
    }
    return Promise.reject(new Error(`Unexpected fetch: ${url}`));
  });
}

const FAKE_JWT = 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJwMSIsImV4cCI6OTk5OTk5OTk5OX0.fake';
const STORED_PLAYER = JSON.stringify({
  id: 'p1',
  displayName: 'Alice',
  role: 'player',
  timezone: 'UTC',
});

function renderPage() {
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

  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <AuthProvider>
          <SchedulePage />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe('SchedulePage knockout skeleton', () => {
  it('renders seeded knockout rounds grouped by round — not "No matches found"', async () => {
    vi.stubGlobal('fetch', makeFetch([GROUP_MATCH, R32_MATCH, R16_MATCH]));
    renderPage();
    await waitFor(() => expect(screen.getByText('Round of 32')).toBeTruthy());
    expect(screen.getByText('Round of 16')).toBeTruthy();
    expect(screen.queryByText('No matches found')).toBeNull();
  });

  it('shows placeholder labels for knockout matches whose teams are TBD', async () => {
    vi.stubGlobal('fetch', makeFetch([GROUP_MATCH, R32_MATCH, R16_MATCH]));
    renderPage();
    // Placeholders are rendered as short codes; full text on title attribute.
    await waitFor(() => expect(screen.getByText('WA')).toBeTruthy());
    expect(screen.getByText('B3#')).toBeTruthy();
    expect(screen.getByText('W73')).toBeTruthy();
  });

  it('still groups group-stage matches under a date heading', async () => {
    vi.stubGlobal('fetch', makeFetch([GROUP_MATCH, R32_MATCH]));
    renderPage();
    // Group match keeps its team label and a date-based section header.
    await waitFor(() => expect(screen.getByText(/MEX/)).toBeTruthy());
    expect(screen.getByText(/Jun 2026/)).toBeTruthy();
  });

  it('shows compact personal prediction status on schedule cards', async () => {
    vi.stubGlobal('fetch', makeFetch([GROUP_MATCH, R32_MATCH]));
    renderPage();

    await waitFor(() => expect(screen.getByText('Predicted 2-1')).toBeTruthy());
    expect(screen.getByText('Missing')).toBeTruthy();
  });
});
