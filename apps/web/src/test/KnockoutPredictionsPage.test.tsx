import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from '@/contexts/AuthContext';
import { KnockoutPredictionsPage } from '@/pages/KnockoutPredictionsPage';

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const HOME_TEAM = { id: 't1', name: 'Brazil', code: 'BRA', flag_emoji: '🇧🇷' };
const AWAY_TEAM = { id: 't2', name: 'Germany', code: 'GER', flag_emoji: '🇩🇪' };

const R32_MATCH_SCHEDULED = {
  id: 'm73',
  match_number: 73,
  stage: 'r32',
  group_id: null,
  home_team: HOME_TEAM,
  away_team: AWAY_TEAM,
  home_team_placeholder: '1A',
  away_team_placeholder: 'T1',
  kickoff_utc: '2026-07-01T20:00:00Z',
  venue: 'MetLife Stadium',
  status: 'scheduled',
  actual_home_score: null,
  actual_away_score: null,
  extra_time: false,
  penalties: false,
  postponed_reason: null,
};

const R32_MATCH_LOCKED = {
  ...R32_MATCH_SCHEDULED,
  id: 'm74',
  match_number: 74,
  home_team: { id: 't3', name: 'France', code: 'FRA', flag_emoji: '🇫🇷' },
  away_team: { id: 't4', name: 'Spain', code: 'ESP', flag_emoji: '🇪🇸' },
  status: 'locked',
};

const R32_MATCH_COMPLETED = {
  ...R32_MATCH_SCHEDULED,
  id: 'm75',
  match_number: 75,
  home_team: { id: 't5', name: 'Argentina', code: 'ARG', flag_emoji: '🇦🇷' },
  away_team: { id: 't6', name: 'Portugal', code: 'POR', flag_emoji: '🇵🇹' },
  status: 'completed',
  actual_home_score: 2,
  actual_away_score: 0,
};

// Group stage match — should be filtered out
const GROUP_MATCH = {
  id: 'mg1',
  match_number: 1,
  stage: 'group',
  group_id: 'ga',
  home_team: HOME_TEAM,
  away_team: AWAY_TEAM,
  home_team_placeholder: null,
  away_team_placeholder: null,
  kickoff_utc: '2026-06-11T20:00:00Z',
  venue: 'MetLife Stadium',
  status: 'completed',
  actual_home_score: 1,
  actual_away_score: 0,
  extra_time: false,
  penalties: false,
  postponed_reason: null,
};

const KO_PRED = {
  id: 'kp1',
  player_id: 'p1',
  match_id: 'm73',
  predicted_winner_id: 't1',
  submitted_at: '2026-06-30T10:00:00Z',
  update_count: 0,
  points_awarded: null,
  updated_at: '2026-06-30T10:00:00Z',
};

const KO_PRED_COMPLETED = {
  id: 'kp2',
  player_id: 'p1',
  match_id: 'm75',
  predicted_winner_id: 't5',
  submitted_at: '2026-06-30T10:00:00Z',
  update_count: 0,
  points_awarded: 5,
  updated_at: '2026-06-30T10:00:00Z',
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

interface FetchOverrides {
  matches?: unknown[];
  knockoutPredictions?: unknown[];
  putResult?: unknown;
}

function makeFetch(overrides: FetchOverrides = {}) {
  const matches = overrides.matches ?? [GROUP_MATCH, R32_MATCH_SCHEDULED];
  const knockoutPredictions = overrides.knockoutPredictions ?? [KO_PRED];
  const putResult = overrides.putResult ?? { ...KO_PRED, update_count: 1 };

  return vi.fn((url: string, opts?: RequestInit) => {
    if (url.includes('/api/v1/matches')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(matches) });
    }
    if (url.includes('/api/v1/knockout-predictions/me')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(knockoutPredictions) });
    }
    if (url.includes('/api/v1/knockout-predictions/') && opts?.method === 'PUT') {
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(putResult) });
    }
    return Promise.reject(new Error(`Unexpected fetch: ${url}`));
  });
}

function makeQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
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
    <QueryClientProvider client={makeQueryClient()}>
      <MemoryRouter>
        <AuthProvider>
          <KnockoutPredictionsPage />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.restoreAllMocks();
});

describe('KnockoutPredictionsPage', () => {
  it('shows bracket teaser when no knockout matches exist', async () => {
    vi.stubGlobal('fetch', makeFetch({ matches: [GROUP_MATCH] }));
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/Knockout picks open after group stage/i)).toBeTruthy(),
    );
  });

  it('renders the R32 round pill when R32 matches exist', async () => {
    vi.stubGlobal('fetch', makeFetch());
    renderPage();
    await waitFor(() => expect(screen.getByText('R32')).toBeTruthy());
  });

  it('shows team names as clickable buttons', async () => {
    vi.stubGlobal('fetch', makeFetch());
    renderPage();
    await waitFor(() => expect(screen.getByText(/Brazil/)).toBeTruthy());
    expect(screen.getByText(/Germany/)).toBeTruthy();
  });

  it('highlights the saved pick', async () => {
    vi.stubGlobal('fetch', makeFetch());
    renderPage();
    // Brazil (home team t1) is the saved pick — button should have picked styling
    await waitFor(() => {
      const brazilBtn = screen.getByText(/Brazil/).closest('button');
      expect(brazilBtn?.className).toMatch(/border-primary/);
    });
  });

  it('calls the API when a team button is clicked', async () => {
    const fetchMock = makeFetch({ knockoutPredictions: [] });
    vi.stubGlobal('fetch', fetchMock);
    renderPage();
    await waitFor(() => expect(screen.getByText(/Germany/)).toBeTruthy());

    const germanyBtn = screen.getByText(/Germany/).closest('button')!;
    fireEvent.click(germanyBtn);

    await waitFor(() => {
      const putCalls = (fetchMock.mock.calls as [string, RequestInit | undefined][]).filter(
        ([url, opts]) =>
          url.includes('/api/v1/knockout-predictions/') && opts?.method === 'PUT',
      );
      expect(putCalls.length).toBeGreaterThan(0);
    });
  });

  it('shows round lock banner when a match is locked', async () => {
    vi.stubGlobal('fetch', makeFetch({ matches: [GROUP_MATCH, R32_MATCH_LOCKED] }));
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/This round is locked/i)).toBeTruthy(),
    );
  });

  it('disables team buttons when round is locked', async () => {
    vi.stubGlobal('fetch', makeFetch({ matches: [GROUP_MATCH, R32_MATCH_LOCKED] }));
    renderPage();
    await waitFor(() => expect(screen.getByText(/France/)).toBeTruthy());
    const franceBtn = screen.getByText(/France/).closest('button')!;
    expect(franceBtn.disabled).toBe(true);
  });

  it('shows points badge for a completed match with a correct pick', async () => {
    vi.stubGlobal(
      'fetch',
      makeFetch({
        matches: [GROUP_MATCH, R32_MATCH_COMPLETED],
        knockoutPredictions: [KO_PRED_COMPLETED],
      }),
    );
    renderPage();
    await waitFor(() => expect(screen.getByText('R32')).toBeTruthy());
    // Points badge should appear (5 pts) — round total + per-match both show now
    await waitFor(() => expect(screen.getAllByText(/pts?/i).length).toBeGreaterThan(0), { timeout: 2000 });
  });

  it('filters out group-stage matches — no group match cards shown', async () => {
    vi.stubGlobal('fetch', makeFetch());
    renderPage();
    await waitFor(() => expect(screen.getByText('R32')).toBeTruthy());
    // The group match teams (Brazil/Germany) appear only from the knockout match
    // — but the group match itself should not create a second card
    const brazilEls = screen.getAllByText(/Brazil/);
    // Should appear once (in the R32 card) — group match is filtered out
    expect(brazilEls.length).toBe(1);
  });

  it('shows multiple round tabs when matches exist in multiple stages', async () => {
    const qfMatch = { ...R32_MATCH_SCHEDULED, id: 'mqf1', match_number: 95, stage: 'qf' };
    vi.stubGlobal('fetch', makeFetch({ matches: [GROUP_MATCH, R32_MATCH_SCHEDULED, qfMatch] }));
    renderPage();
    await waitFor(() => expect(screen.getByText('R32')).toBeTruthy());
    expect(screen.getByText('QF')).toBeTruthy();
  });

  it('auto-selects the earliest open round — skips a finished R32 to land on R16', async () => {
    const r16Open = {
      ...R32_MATCH_SCHEDULED,
      id: 'm89',
      match_number: 89,
      stage: 'r16',
      home_team: { id: 't7', name: 'Italy', code: 'ITA', flag_emoji: '🇮🇹' },
      away_team: { id: 't8', name: 'Netherlands', code: 'NED', flag_emoji: '🇳🇱' },
      status: 'scheduled',
    };
    // R32 is completed (round locked); R16 is open with real teams → R16 is the
    // round that needs attention, so it should be active without any click.
    vi.stubGlobal(
      'fetch',
      makeFetch({
        matches: [GROUP_MATCH, R32_MATCH_COMPLETED, r16Open],
        knockoutPredictions: [],
      }),
    );
    renderPage();

    // Lands on R16: its teams are visible…
    await waitFor(() => expect(screen.getByText(/Italy/)).toBeTruthy());
    // …and the finished R32 panel (Argentina/Portugal) is not the active one.
    expect(screen.queryByText(/Argentina/)).toBeNull();
  });

  it('renders a per-round placeholder list (not the teaser) when teams are TBD', async () => {
    // Seeded R32 row with no resolved teams — only positional placeholders.
    const r32Placeholder = {
      ...R32_MATCH_SCHEDULED,
      id: 'm73p',
      home_team: null,
      away_team: null,
      home_team_placeholder: 'Winner Group A',
      away_team_placeholder: 'Best 3rd #1',
    };
    vi.stubGlobal(
      'fetch',
      makeFetch({ matches: [GROUP_MATCH, r32Placeholder], knockoutPredictions: [] }),
    );
    renderPage();

    await waitFor(() => expect(screen.getByText('R32')).toBeTruthy());
    // The bracket teaser must NOT show — there are seeded rows.
    expect(screen.queryByText(/Knockout picks open after group stage/i)).toBeNull();
    // Placeholder labels are rendered as short codes in the (disabled) team buttons.
    expect(screen.getByText('WA')).toBeTruthy();
    const placeholderBtn = screen.getByText('WA').closest('button')!;
    expect(placeholderBtn.disabled).toBe(true);
  });
});
