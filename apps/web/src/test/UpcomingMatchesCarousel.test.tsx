import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { axe } from 'jest-axe';
import { AuthProvider } from '@/contexts/AuthContext';
import { UpcomingMatchesCarousel } from '@/components/UpcomingMatchesCarousel';

// jsdom cannot evaluate CSS custom properties — disable color-contrast only.
const AXE_CONFIG = { rules: { 'color-contrast': { enabled: false } } };

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const FAKE_JWT = 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJwMSIsImV4cCI6OTk5OTk5OTk5OX0.fake';
const STORED_PLAYER = JSON.stringify({
  id: 'p1',
  displayName: 'Alice',
  role: 'player',
  timezone: 'UTC',
});

type Overrides = Partial<Record<string, unknown>>;

function baseMatch(n: number, overrides: Overrides = {}) {
  return {
    id: `m${n}`,
    match_number: n,
    stage: 'group',
    group_id: 'ga',
    home_team: { id: `h${n}`, name: `Home${n}`, code: 'HOM', flag_emoji: '🏴' },
    away_team: { id: `a${n}`, name: `Away${n}`, code: 'AWY', flag_emoji: '🏳️' },
    home_team_placeholder: null,
    away_team_placeholder: null,
    kickoff_utc: `2026-06-${String(10 + n).padStart(2, '0')}T18:00:00Z`,
    venue: null,
    status: 'scheduled',
    actual_home_score: null,
    actual_away_score: null,
    extra_time: false,
    penalties: false,
    postponed_reason: null,
    ...overrides,
  };
}

function resolve(payload: unknown) {
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(payload) });
}

function makeFetch(matches: unknown[], predictions: unknown[]) {
  return vi.fn((url: string, opts?: RequestInit) => {
    if (url.includes('/api/v1/matches')) return resolve(matches);
    if (url.includes('/api/v1/predictions/me')) return resolve(predictions);
    if (url.includes('/api/v1/predictions/') && opts?.method === 'PUT') return resolve({});
    return Promise.reject(new Error(`Unexpected fetch: ${url}`));
  });
}

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

function renderCarousel(fetchMock: ReturnType<typeof makeFetch>) {
  stubAuth();
  vi.stubGlobal('fetch', fetchMock);
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <MemoryRouter>
        <AuthProvider>
          <UpcomingMatchesCarousel />
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

describe('UpcomingMatchesCarousel', () => {
  it('caps the carousel at the next 8 scheduled matches', async () => {
    const matches = Array.from({ length: 10 }, (_, i) => baseMatch(i + 1));
    renderCarousel(makeFetch(matches, []));

    await waitFor(() => expect(screen.queryByTestId('prediction-card-m1')).toBeTruthy());
    const cards = screen.getAllByTestId(/^prediction-card-/);
    expect(cards.length).toBe(8);
  });

  it('shows the soonest matches first and drops the overflow (match 9/10 absent)', async () => {
    const matches = Array.from({ length: 10 }, (_, i) => baseMatch(i + 1));
    renderCarousel(makeFetch(matches, []));

    await waitFor(() => expect(screen.queryByTestId('prediction-card-m1')).toBeTruthy());
    expect(screen.queryByTestId('prediction-card-m8')).toBeTruthy();
    expect(screen.queryByTestId('prediction-card-m9')).toBeNull();
  });

  it('renders the saved prediction in a predicted card', async () => {
    const matches = [baseMatch(1), baseMatch(2)];
    const predictions = [{ match_id: 'm1', predicted_home: 1, predicted_away: 0, points_awarded: null }];
    renderCarousel(makeFetch(matches, predictions));

    await waitFor(() => expect(screen.queryByTestId('prediction-card-m1')).toBeTruthy());
    const homeInput = screen.getByLabelText('Home score for match 1') as HTMLInputElement;
    expect(homeInput.value).toBe('1');
  });

  it('shows the not-predicted warning for an unpredicted scheduled card', async () => {
    const matches = [baseMatch(1), baseMatch(2)];
    const predictions = [{ match_id: 'm1', predicted_home: 1, predicted_away: 0, points_awarded: null }];
    renderCarousel(makeFetch(matches, predictions));

    // m2 has no prediction → warning present (and exactly one, for m2)
    await waitFor(() => expect(screen.queryByTestId('not-predicted-warning')).toBeTruthy());
    expect(screen.getAllByTestId('not-predicted-warning').length).toBe(1);
  });

  it('shows the Predicted indicator on a predicted card (uniform footer)', async () => {
    const matches = [baseMatch(1), baseMatch(2)];
    const predictions = [{ match_id: 'm1', predicted_home: 1, predicted_away: 0, points_awarded: null }];
    renderCarousel(makeFetch(matches, predictions));

    // m1 is predicted → exactly one "Predicted" indicator; m2 stays "not predicted"
    await waitFor(() => expect(screen.queryByTestId('predicted-indicator')).toBeTruthy());
    expect(screen.getAllByTestId('predicted-indicator').length).toBe(1);
    expect(screen.getByTestId('predicted-indicator').textContent).toMatch(/Predicted/i);
  });

  it('autosaves an inline edit via the shared hook (debounced PUT)', async () => {
    const matches = [baseMatch(1)];
    const predictions = [{ match_id: 'm1', predicted_home: 1, predicted_away: 0, points_awarded: null }];
    const fetchMock = makeFetch(matches, predictions);
    renderCarousel(fetchMock);

    await waitFor(() => expect(screen.queryByLabelText('Home score for match 1')).toBeTruthy());
    fireEvent.change(screen.getByLabelText('Home score for match 1'), { target: { value: '3' } });

    await waitFor(
      () => {
        const puts = (fetchMock.mock.calls as unknown as [string, RequestInit][]).filter(
          ([url, opts]) => url.includes('/api/v1/predictions/m1') && opts?.method === 'PUT',
        );
        expect(puts.length).toBeGreaterThan(0);
      },
      { timeout: 2500 },
    );
  });

  it('ends with a "See full schedule" card linking to /schedule', async () => {
    renderCarousel(makeFetch([baseMatch(1)], []));

    await waitFor(() => expect(screen.queryByTestId('carousel-see-all')).toBeTruthy());
    const link = screen.getByRole('link', { name: /see full schedule/i });
    expect(link.getAttribute('href')).toBe('/schedule');
  });

  it('excludes knockout matches (group-stage scores v1)', async () => {
    const matches = [baseMatch(1), baseMatch(2, { stage: 'round_of_32' })];
    renderCarousel(makeFetch(matches, []));

    await waitFor(() => expect(screen.queryByTestId('prediction-card-m1')).toBeTruthy());
    expect(screen.queryByTestId('prediction-card-m2')).toBeNull();
  });

  it('excludes locked matches (prediction window closed)', async () => {
    const matches = [baseMatch(1, { status: 'locked' }), baseMatch(2)];
    renderCarousel(makeFetch(matches, []));

    await waitFor(() => expect(screen.queryByTestId('prediction-card-m2')).toBeTruthy());
    expect(screen.queryByTestId('prediction-card-m1')).toBeNull();
  });

  it('excludes live matches (live hub moved to U27)', async () => {
    const matches = [
      baseMatch(1, { status: 'live', actual_home_score: 1, actual_away_score: 0 }),
      baseMatch(2),
    ];
    renderCarousel(makeFetch(matches, []));

    await waitFor(() => expect(screen.queryByTestId('prediction-card-m2')).toBeTruthy());
    expect(screen.queryByTestId('prediction-card-m1')).toBeNull();
  });

  it('excludes completed matches', async () => {
    const matches = [baseMatch(1), baseMatch(2, { status: 'completed' })];
    renderCarousel(makeFetch(matches, []));

    await waitFor(() => expect(screen.queryByTestId('prediction-card-m1')).toBeTruthy());
    expect(screen.queryByTestId('prediction-card-m2')).toBeNull();
  });

  it('self-hides when no scheduled matches remain', async () => {
    const matches = [
      baseMatch(1, { status: 'locked' }),
      baseMatch(2, { status: 'live', actual_home_score: 1, actual_away_score: 0 }),
      baseMatch(3, { status: 'completed' }),
      baseMatch(4, { stage: 'round_of_32' }),
    ];
    renderCarousel(makeFetch(matches, []));

    // No open-to-predict group matches → the whole section unmounts.
    await waitFor(() => expect(screen.queryByText('Upcoming')).toBeNull());
    expect(screen.queryByRole('list', { name: 'Upcoming matches' })).toBeNull();
  });

  it('exposes ARIA list + per-card group semantics with labels', async () => {
    renderCarousel(makeFetch([baseMatch(1)], []));

    await waitFor(() => expect(screen.queryByRole('list', { name: 'Upcoming matches' })).toBeTruthy());
    const groups = screen.getAllByRole('group');
    expect(groups.length).toBe(1);
    expect(groups[0].getAttribute('aria-label')).toMatch(/Home1 versus Away1/);
  });

  it('has no axe violations', async () => {
    const matches = [
      baseMatch(1),
      baseMatch(2),
    ];
    const predictions = [{ match_id: 'm1', predicted_home: 1, predicted_away: 0, points_awarded: null }];
    const { container } = renderCarousel(makeFetch(matches, predictions));

    await waitFor(() => expect(screen.queryByTestId('prediction-card-m1')).toBeTruthy());
    const results = await axe(container, AXE_CONFIG);
    expect(results).toHaveNoViolations();
  }, 10_000);
});
