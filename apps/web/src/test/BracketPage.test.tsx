import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from '@/contexts/AuthContext';
import { BracketPage } from '@/pages/BracketPage';

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const T = {
  bra: { id: 't-bra', name: 'Brazil', code: 'BRA', flag_emoji: '🇧🇷' },
  ger: { id: 't-ger', name: 'Germany', code: 'GER', flag_emoji: '🇩🇪' },
  fra: { id: 't-fra', name: 'France', code: 'FRA', flag_emoji: '🇫🇷' },
  esp: { id: 't-esp', name: 'Spain', code: 'ESP', flag_emoji: '🇪🇸' },
  arg: { id: 't-arg', name: 'Argentina', code: 'ARG', flag_emoji: '🇦🇷' },
  por: { id: 't-por', name: 'Portugal', code: 'POR', flag_emoji: '🇵🇹' },
};

function makeMatch(overrides: Partial<Record<string, unknown>>) {
  return {
    id: 'm',
    match_number: 73,
    stage: 'r32',
    group_id: null,
    home_team: T.bra,
    away_team: T.ger,
    home_team_placeholder: '1A',
    away_team_placeholder: '2B',
    kickoff_utc: '2026-07-01T20:00:00Z',
    venue: 'MetLife Stadium',
    status: 'scheduled',
    actual_home_score: null,
    actual_away_score: null,
    extra_time: false,
    penalties: false,
    postponed_reason: null,
    ...overrides,
  };
}

const GROUP_MATCH = makeMatch({ id: 'mg1', match_number: 1, stage: 'group' });

// R32 match — Brazil vs Germany, scheduled, user picked Brazil
const R32_SCHEDULED = makeMatch({ id: 'm-r32', match_number: 73, stage: 'r32' });

// R32 match with TBD placeholders (no teams yet)
const R32_PLACEHOLDER = makeMatch({
  id: 'm-r32-tbd',
  match_number: 74,
  stage: 'r32',
  home_team: null,
  away_team: null,
  home_team_placeholder: '1B',
  away_team_placeholder: '2C',
});

// Completed R32 — Argentina beat Portugal 2-0; user picked Argentina (correct)
const R32_COMPLETED_CORRECT = makeMatch({
  id: 'm-r32-c1',
  match_number: 75,
  stage: 'r32',
  home_team: T.arg,
  away_team: T.por,
  status: 'completed',
  actual_home_score: 2,
  actual_away_score: 0,
});

// Completed R32 — France beat Spain 1-0; user picked Spain (wrong)
const R32_COMPLETED_WRONG = makeMatch({
  id: 'm-r32-c2',
  match_number: 76,
  stage: 'r32',
  home_team: T.fra,
  away_team: T.esp,
  status: 'completed',
  actual_home_score: 1,
  actual_away_score: 0,
});

const FINAL_MATCH = makeMatch({
  id: 'm-final',
  match_number: 103,
  stage: 'final',
  home_team: null,
  away_team: null,
  home_team_placeholder: 'SF1 winner',
  away_team_placeholder: 'SF2 winner',
});

const THIRD_PLACE_MATCH = makeMatch({
  id: 'm-tp',
  match_number: 102,
  stage: 'third_place',
  home_team: null,
  away_team: null,
  home_team_placeholder: 'SF1 loser',
  away_team_placeholder: 'SF2 loser',
});

const KO_PRED_BRAZIL = {
  id: 'kp1',
  player_id: 'p1',
  match_id: 'm-r32',
  predicted_winner_id: T.bra.id,
  submitted_at: '2026-06-30T10:00:00Z',
  update_count: 0,
  points_awarded: null,
  updated_at: '2026-06-30T10:00:00Z',
};

const KO_PRED_ARG_CORRECT = {
  id: 'kp2',
  player_id: 'p1',
  match_id: 'm-r32-c1',
  predicted_winner_id: T.arg.id,
  submitted_at: '2026-06-30T10:00:00Z',
  update_count: 0,
  points_awarded: 5,
  updated_at: '2026-06-30T10:00:00Z',
};

const KO_PRED_ESP_WRONG = {
  id: 'kp3',
  player_id: 'p1',
  match_id: 'm-r32-c2',
  predicted_winner_id: T.esp.id,
  submitted_at: '2026-06-30T10:00:00Z',
  update_count: 0,
  points_awarded: 0,
  updated_at: '2026-06-30T10:00:00Z',
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

interface FetchOverrides {
  matches?: unknown[];
  knockoutPredictions?: unknown[];
}

function makeFetch(overrides: FetchOverrides = {}) {
  const matches = overrides.matches ?? [GROUP_MATCH, R32_SCHEDULED];
  const knockoutPredictions = overrides.knockoutPredictions ?? [KO_PRED_BRAZIL];

  return vi.fn((url: string) => {
    if (url.includes('/api/v1/matches')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(matches) });
    }
    if (url.includes('/api/v1/knockout-predictions/me')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(knockoutPredictions) });
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
          <BracketPage />
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

describe('BracketPage', () => {
  it('shows bracket teaser when no knockout matches exist', async () => {
    vi.stubGlobal('fetch', makeFetch({ matches: [GROUP_MATCH] }));
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/The bracket arrives after group stage/i)).toBeTruthy(),
    );
  });

  it('renders the round-of-32 column header', async () => {
    vi.stubGlobal('fetch', makeFetch());
    renderPage();
    await waitFor(() => expect(screen.getByText(/ROUND OF 32/i)).toBeTruthy());
  });

  it('renders all five round headers (R32 → R16 → QF → SF → F)', async () => {
    vi.stubGlobal('fetch', makeFetch());
    renderPage();
    await waitFor(() => expect(screen.getByText(/ROUND OF 32/i)).toBeTruthy());
    expect(screen.getByText(/ROUND OF 16/i)).toBeTruthy();
    expect(screen.getByText(/QUARTER-FINALS/i)).toBeTruthy();
    expect(screen.getByText(/SEMI-FINALS/i)).toBeTruthy();
    expect(screen.getByText(/^FINAL$/i)).toBeTruthy();
  });

  it('renders team names from a real match', async () => {
    vi.stubGlobal('fetch', makeFetch());
    renderPage();
    await waitFor(() => expect(screen.getByText(/Brazil/)).toBeTruthy());
    expect(screen.getByText(/Germany/)).toBeTruthy();
  });

  it('renders placeholder text for matches with no teams yet', async () => {
    vi.stubGlobal('fetch', makeFetch({ matches: [R32_PLACEHOLDER] }));
    renderPage();
    await waitFor(() => expect(screen.getByText('1B')).toBeTruthy());
    expect(screen.getByText('2C')).toBeTruthy();
  });

  it('marks the predicted winner with data-picked=true', async () => {
    vi.stubGlobal('fetch', makeFetch());
    renderPage();
    await waitFor(() => {
      const card = screen.getByTestId('bracket-match-m-r32');
      const brazilRow = within(card).getByText(/Brazil/).closest('[data-team-id]');
      expect(brazilRow?.getAttribute('data-picked')).toBe('true');
    });
    const card = screen.getByTestId('bracket-match-m-r32');
    const germanyRow = within(card).getByText(/Germany/).closest('[data-team-id]');
    expect(germanyRow?.getAttribute('data-picked')).toBe('false');
  });

  it('marks correct predictions for completed matches', async () => {
    vi.stubGlobal(
      'fetch',
      makeFetch({
        matches: [R32_COMPLETED_CORRECT],
        knockoutPredictions: [KO_PRED_ARG_CORRECT],
      }),
    );
    renderPage();
    await waitFor(() => {
      const card = screen.getByTestId('bracket-match-m-r32-c1');
      const argRow = within(card).getByText(/Argentina/).closest('[data-team-id]');
      expect(argRow?.getAttribute('data-correct')).toBe('true');
    });
  });

  it('marks wrong predictions for completed matches', async () => {
    vi.stubGlobal(
      'fetch',
      makeFetch({
        matches: [R32_COMPLETED_WRONG],
        knockoutPredictions: [KO_PRED_ESP_WRONG],
      }),
    );
    renderPage();
    await waitFor(() => {
      const card = screen.getByTestId('bracket-match-m-r32-c2');
      const espRow = within(card).getByText(/Spain/).closest('[data-team-id]');
      expect(espRow?.getAttribute('data-wrong')).toBe('true');
    });
  });

  it('renders actual scores on completed matches', async () => {
    vi.stubGlobal(
      'fetch',
      makeFetch({
        matches: [R32_COMPLETED_CORRECT],
        knockoutPredictions: [KO_PRED_ARG_CORRECT],
      }),
    );
    renderPage();
    await waitFor(() => {
      const card = screen.getByTestId('bracket-match-m-r32-c1');
      expect(within(card).getByText('2')).toBeTruthy();
      expect(within(card).getByText('0')).toBeTruthy();
    });
  });

  it('renders the final match', async () => {
    vi.stubGlobal('fetch', makeFetch({ matches: [R32_SCHEDULED, FINAL_MATCH] }));
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId('bracket-match-m-final')).toBeTruthy(),
    );
  });

  it('renders the third-place playoff as a separate block', async () => {
    vi.stubGlobal('fetch', makeFetch({ matches: [R32_SCHEDULED, THIRD_PLACE_MATCH] }));
    renderPage();
    await waitFor(() => expect(screen.getByText(/THIRD PLACE/i)).toBeTruthy());
    expect(screen.getByTestId('bracket-match-m-tp')).toBeTruthy();
  });

  it('wraps the SVG in a horizontally scrollable container', async () => {
    vi.stubGlobal('fetch', makeFetch());
    renderPage();
    await waitFor(() => {
      const container = screen.getByTestId('bracket-scroll-container');
      expect(container.className).toMatch(/overflow-x-auto/);
    });
  });

  it('filters out group-stage matches', async () => {
    vi.stubGlobal('fetch', makeFetch({ matches: [GROUP_MATCH, R32_SCHEDULED] }));
    renderPage();
    await waitFor(() => expect(screen.getByText(/Brazil/)).toBeTruthy());
    // Brazil only appears in the R32 card — group match is filtered.
    expect(screen.getAllByText(/Brazil/).length).toBe(1);
  });
});
