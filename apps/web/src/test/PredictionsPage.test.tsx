import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent, act } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from '@/contexts/AuthContext';
import { PredictionsPage } from '@/pages/PredictionsPage';
import { GroupPredictionsPage } from '@/pages/GroupPredictionsPage';

const GROUP_A = { id: 'ga', name: 'A', standings: [] };
const GROUP_B = { id: 'gb', name: 'B', standings: [] };

const MATCH_SCHEDULED = {
  id: 'm1',
  match_number: 1,
  stage: 'group',
  group_id: 'ga',
  group_name: 'A',
  home_team: { id: 't1', name: 'Brazil', code: 'BRA', flag_emoji: 'BR' },
  away_team: { id: 't2', name: 'Germany', code: 'GER', flag_emoji: 'DE' },
  home_team_placeholder: null,
  away_team_placeholder: null,
  kickoff_utc: '2026-06-11T20:00:00Z',
  venue: 'MetLife Stadium',
  status: 'scheduled',
  actual_home_score: null,
  actual_away_score: null,
  extra_time: false,
  penalties: false,
  postponed_reason: null,
};

const MATCH_LOCKED = {
  ...MATCH_SCHEDULED,
  id: 'm2',
  match_number: 2,
  kickoff_utc: '2026-06-12T20:00:00Z',
  status: 'locked',
  home_team: { id: 't3', name: 'France', code: 'FRA', flag_emoji: 'FR' },
  away_team: { id: 't4', name: 'Spain', code: 'ESP', flag_emoji: 'ES' },
};

const MATCH_CANCELLED = {
  ...MATCH_SCHEDULED,
  id: 'm3',
  match_number: 3,
  kickoff_utc: '2026-06-13T20:00:00Z',
  status: 'cancelled',
  home_team: { id: 't5', name: 'Italy', code: 'ITA', flag_emoji: 'IT' },
  away_team: { id: 't6', name: 'England', code: 'ENG', flag_emoji: 'EN' },
};

const MATCH_COMPLETED = {
  ...MATCH_SCHEDULED,
  id: 'm4',
  match_number: 4,
  kickoff_utc: '2026-06-14T20:00:00Z',
  status: 'completed',
  actual_home_score: 2,
  actual_away_score: 1,
  home_team: { id: 't7', name: 'Argentina', code: 'ARG', flag_emoji: 'AR' },
  away_team: { id: 't8', name: 'Portugal', code: 'POR', flag_emoji: 'PT' },
};

const MATCH_SCHEDULED_NOPRED = {
  ...MATCH_SCHEDULED,
  id: 'm5',
  match_number: 5,
  kickoff_utc: '2026-06-15T18:00:00Z',
  home_team: { id: 't9', name: 'Mexico', code: 'MEX', flag_emoji: 'MX' },
  away_team: { id: 't10', name: 'USA', code: 'USA', flag_emoji: 'US' },
};

const MATCH_KNOCKOUT = {
  ...MATCH_SCHEDULED,
  id: 'm73',
  match_number: 73,
  stage: 'r32',
  group_id: null,
  group_name: null,
  kickoff_utc: '2026-06-28T19:00:00Z',
  home_team: null,
  away_team: null,
  home_team_placeholder: 'Winner Group A',
  away_team_placeholder: 'Best 3rd #1',
};

const PRED_SCHEDULED = {
  id: 'p1',
  player_id: 'player-1',
  match_id: 'm1',
  predicted_home: 1,
  predicted_away: 0,
  submitted_at: null,
  update_count: 1,
  points_awarded: null,
  points_breakdown: null,
  updated_at: '2026-06-01T00:00:00Z',
};

const PRED_COMPLETED = {
  id: 'p2',
  player_id: 'player-1',
  match_id: 'm4',
  predicted_home: 2,
  predicted_away: 1,
  submitted_at: null,
  update_count: 1,
  points_awarded: 5,
  points_breakdown: { goals: 2, result: 3, exact: 0, total: 5, no_prediction: false },
  updated_at: '2026-06-01T00:00:00Z',
};

const NO_PRED_CANCELLED = {
  id: 'p3',
  player_id: 'player-1',
  match_id: 'm3',
  predicted_home: null,
  predicted_away: null,
  submitted_at: null,
  update_count: 1,
  points_awarded: 0,
  points_breakdown: null,
  updated_at: '2026-06-01T00:00:00Z',
};

function makeFetch(overrides: Record<string, unknown> = {}) {
  const defaults: Record<string, unknown> = {
    groups: [GROUP_A, GROUP_B],
    matches: [MATCH_SCHEDULED, MATCH_LOCKED, MATCH_CANCELLED, MATCH_COMPLETED],
    predictions: [PRED_SCHEDULED, PRED_COMPLETED, NO_PRED_CANCELLED],
  };
  const data = { ...defaults, ...overrides };

  return vi.fn((url: string) => {
    if (url.includes('/api/v1/groups')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(data.groups) });
    }
    if (url.includes('/api/v1/matches')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(data.matches) });
    }
    if (url.includes('/api/v1/predictions/me')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(data.predictions) });
    }
    if (url.includes('/api/v1/predictions/')) {
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) });
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

function renderPage(
  Component: typeof PredictionsPage | typeof GroupPredictionsPage,
  initialEntries: string[] = ['/predictions'],
) {
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
      <MemoryRouter initialEntries={initialEntries}>
        <AuthProvider>
          <Component />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe('PredictionsPage', () => {
  it('renders the all/group/knockout/specials sub-nav on the all-matches route', async () => {
    vi.stubGlobal('fetch', makeFetch());
    renderPage(PredictionsPage);

    await waitFor(() => expect(screen.getByRole('link', { name: 'All' })).toHaveAttribute('aria-current', 'page'));
    expect(screen.getByRole('link', { name: 'Group' })).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Knockout' })).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Specials' })).toBeTruthy();
  });

  it('shows all matches in kickoff order, including knockout fixtures', async () => {
    vi.stubGlobal('fetch', makeFetch({
      matches: [MATCH_KNOCKOUT, MATCH_COMPLETED, MATCH_SCHEDULED],
      predictions: [PRED_SCHEDULED, PRED_COMPLETED],
    }));
    const { container } = renderPage(PredictionsPage);

    await waitFor(() => expect(screen.getByRole('button', { name: 'Upcoming' })).toHaveAttribute('aria-pressed', 'true'));
    fireEvent.click(screen.getByRole('button', { name: 'All' }));
    await waitFor(() => expect(screen.getByTestId('prediction-card-m73')).toBeTruthy());

    const ids = Array.from(container.querySelectorAll('[data-testid^="prediction-card-"]')).map(
      (el) => el.getAttribute('data-testid'),
    );
    expect(ids).toEqual([
      'prediction-card-m1',
      'prediction-card-m4',
      'prediction-card-m73',
    ]);
    expect(screen.getByText('Round of 32')).toBeTruthy();
  });

  it('defaults to upcoming matches so editable predicted games stay visible', async () => {
    vi.stubGlobal('fetch', makeFetch({
      matches: [MATCH_SCHEDULED, MATCH_SCHEDULED_NOPRED, MATCH_LOCKED, MATCH_COMPLETED],
      predictions: [PRED_SCHEDULED, PRED_COMPLETED],
    }));
    renderPage(PredictionsPage);

    await waitFor(() => expect(screen.getByTestId('prediction-card-m5')).toBeTruthy());
    expect(screen.getByRole('button', { name: 'Upcoming' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByTestId('prediction-card-m1')).toBeTruthy();
    expect(screen.queryByTestId('prediction-card-m2')).toBeNull();
    expect(screen.queryByTestId('prediction-card-m4')).toBeNull();
  });

  it('enables save visible changes after editing an open match', async () => {
    vi.stubGlobal('fetch', makeFetch({
      matches: [MATCH_SCHEDULED, MATCH_SCHEDULED_NOPRED],
      predictions: [PRED_SCHEDULED],
    }));
    renderPage(PredictionsPage);

    await waitFor(() => expect(screen.getByRole('button', { name: 'Upcoming' })).toHaveAttribute('aria-pressed', 'true'));
    await waitFor(() => expect(screen.getByLabelText('Home score for match 1')).toBeTruthy());
    fireEvent.change(screen.getByLabelText('Home score for match 1'), { target: { value: '3' } });

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Save visible changes/i })).toHaveProperty('disabled', false);
    });
  });

  it('calls PUT /api/v1/predictions/{match_id} when save visible changes is clicked', async () => {
    const fetchMock = makeFetch({
      matches: [MATCH_SCHEDULED, MATCH_SCHEDULED_NOPRED],
      predictions: [PRED_SCHEDULED],
    });
    vi.stubGlobal('fetch', fetchMock);
    renderPage(PredictionsPage);

    await waitFor(() => expect(screen.getByRole('button', { name: 'Upcoming' })).toHaveAttribute('aria-pressed', 'true'));
    await waitFor(() => expect(screen.getByLabelText('Home score for match 1')).toBeTruthy());
    fireEvent.change(screen.getByLabelText('Home score for match 1'), { target: { value: '3' } });

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Save visible changes/i })).toHaveProperty('disabled', false);
    });

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /Save visible changes/i }));
    });

    await waitFor(() => {
      const putCalls = (fetchMock.mock.calls as unknown as [string, RequestInit][]).filter(
        ([url, opts]) => url.includes('/api/v1/predictions/m1') && opts?.method === 'PUT',
      );
      expect(putCalls.length).toBeGreaterThan(0);
    });
  });
});

describe('GroupPredictionsPage', () => {
  it('renders group tabs A and B after loading', async () => {
    vi.stubGlobal('fetch', makeFetch());
    renderPage(GroupPredictionsPage, ['/predictions/group']);

    await waitFor(() => expect(screen.getByRole('tab', { name: /Group A/i })).toBeTruthy());
    expect(screen.getByRole('tab', { name: /Group B/i })).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Group' })).toHaveAttribute('aria-current', 'page');
  });

  it('shows scheduled match inputs as editable', async () => {
    vi.stubGlobal('fetch', makeFetch());
    renderPage(GroupPredictionsPage, ['/predictions/group']);

    await waitFor(() => expect(screen.getByRole('tab', { name: /Group A/i })).toBeTruthy());
    expect(screen.getByLabelText('Home score for match 1')).toHaveProperty('disabled', false);
  });

  it('shows locked match inputs as read-only', async () => {
    vi.stubGlobal('fetch', makeFetch());
    renderPage(GroupPredictionsPage, ['/predictions/group']);

    await waitFor(() => expect(screen.getByRole('tab', { name: /Group A/i })).toBeTruthy());
    expect(screen.getByLabelText('Home score for match 2')).toHaveProperty('disabled', true);
  });

  it('shows cancelled match with voided badge and opacity', async () => {
    vi.stubGlobal('fetch', makeFetch());
    renderPage(GroupPredictionsPage, ['/predictions/group']);

    await waitFor(() => expect(screen.getByText('Voided')).toBeTruthy());
    expect(screen.getByTestId('prediction-card-m3').className).toContain('opacity-50');
  });

  it('shows points badge for a completed match', async () => {
    vi.stubGlobal('fetch', makeFetch());
    renderPage(GroupPredictionsPage, ['/predictions/group']);

    await waitFor(() => {
      expect(screen.getByTestId('points-badge').textContent).toBe('5 pts');
    }, { timeout: 3000 });
  });

  it('calls PUT /api/v1/predictions/{match_id} when save group is clicked', async () => {
    const fetchMock = makeFetch();
    vi.stubGlobal('fetch', fetchMock);
    renderPage(GroupPredictionsPage, ['/predictions/group']);

    await waitFor(() => expect(screen.getByLabelText('Home score for match 1')).toBeTruthy());
    fireEvent.change(screen.getByLabelText('Home score for match 1'), { target: { value: '3' } });

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Save Group A/i })).toHaveProperty('disabled', false);
    });

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /Save Group A/i }));
    });

    await waitFor(() => {
      const putCalls = (fetchMock.mock.calls as unknown as [string, RequestInit][]).filter(
        ([url, opts]) => url.includes('/api/v1/predictions/m1') && opts?.method === 'PUT',
      );
      expect(putCalls.length).toBeGreaterThan(0);
    });
  });
});
