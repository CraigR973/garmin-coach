import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from '@/contexts/AuthContext';
import { PlayerProfilePage } from '@/pages/PlayerProfilePage';

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const PLAYER_ID = 'bb000000-0000-0000-0000-000000000001';
const MY_ID = 'aa000000-0000-0000-0000-000000000001';

const STATS: Record<string, unknown> = {
  player_id: PLAYER_ID,
  player_name: 'Bob',
  total_predictions_settled: 12,
  accuracy_pct: 66.7,
  exact_rate_pct: 25.0,
  avg_pts_per_prediction: 4.5,
  total_points: 54,
  best_round: 'group',
  best_round_points: 40,
  worst_round: 'r16',
  worst_round_points: 14,
  current_streak: 3,
  avg_prediction_timing_mins: 180,
  match_points: 40,
  knockout_winner_points: 9,
  special_points: 5,
  exact_count: 4,
  correct_result_count: 9,
  correct_goals_count: 11,
  specials_correct_count: 1,
  ko_winner_correct_count: 2,
};

const MY_STATS: Record<string, unknown> = {
  player_id: MY_ID,
  player_name: 'Alice',
  total_predictions_settled: 10,
  accuracy_pct: 70.0,
  exact_rate_pct: 20.0,
  avg_pts_per_prediction: 5.0,
  total_points: 50,
  best_round: 'group',
  best_round_points: 38,
  worst_round: 'r16',
  worst_round_points: 12,
  current_streak: 2,
  avg_prediction_timing_mins: 240,
};

const RECENT_PREDS = [
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
    predicted_home: 2,
    predicted_away: 1,
    points_awarded: 10,
    points_breakdown: { goals: 2, result: 3, exact: 5, total: 10, no_prediction: false },
  },
];

// U24 reveal-gated board. Default fixture: everything revealed (locked).
const PROFILE_PREDS: Record<string, unknown> = {
  specials_revealed: true,
  group: [
    {
      match_id: 'g1',
      stage: 'group',
      kickoff_utc: '2026-06-14T18:00:00Z',
      home_team_name: 'Argentina',
      away_team_name: 'Mexico',
      home_team_flag: '🇦🇷',
      away_team_flag: '🇲🇽',
      actual_home: null,
      actual_away: null,
      predicted_home: 3,
      predicted_away: 0,
      points_awarded: null,
      points_breakdown: null,
    },
  ],
  knockout: [
    {
      match_id: 'k1',
      // Use a stage not asserted elsewhere (best=group, worst=r16) to avoid
      // STAGE_LABEL collisions in the broader page tests.
      stage: 'qf',
      kickoff_utc: '2026-07-01T18:00:00Z',
      home_team_name: 'France',
      away_team_name: 'Spain',
      home_team_flag: '🇫🇷',
      away_team_flag: '🇪🇸',
      predicted_winner_id: 'team-france',
      predicted_winner_name: 'France',
      points_awarded: 4,
    },
  ],
  specials: [
    {
      prediction_type: 'tournament_winner',
      // Distinct team name (recent preds already render Brazil/Germany) so the
      // recent-predictions test's getByText(/Brazil/) stays unambiguous.
      predicted_team_id: 'team-portugal',
      predicted_team_name: 'Portugal',
      predicted_player_name: null,
      points_awarded: null,
    },
  ],
};

// Specials still hidden (tournament not started) and nothing else revealed.
const PROFILE_PREDS_HIDDEN: Record<string, unknown> = {
  specials_revealed: false,
  group: [],
  knockout: [],
  specials: [],
};

const HOME_WITH_ROLLUP: Record<string, unknown> = {
  todo: {
    specials_submitted: true,
    specials_lock_at: null,
    upcoming_unpredicted: 0,
    next_match: null,
  },
  rollup: {
    matchday: '2026-06-11',
    points_gained: 10,
    match_count: 2,
    matches: [
      {
        match_id: 'match-1',
        kickoff_utc: '2026-06-11T18:00:00Z',
        home_label: '🇧🇷 Brazil',
        away_label: '🇲🇽 Mexico',
        home_flag: '🇧🇷',
        away_flag: '🇲🇽',
        actual_home: 2,
        actual_away: 1,
        predicted_home: 2,
        predicted_away: 1,
        points_breakdown: { goals: 2, result: 3, exact: 5, total: 10, no_prediction: false },
      },
    ],
  },
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeFetch(
  targetId: string = PLAYER_ID,
  profilePreds: Record<string, unknown> = PROFILE_PREDS,
) {
  return vi.fn((url: string) => {
    // Order matters: the profile-predictions path also contains "/predictions".
    if (url.includes('/profile-predictions')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(profilePreds) });
    }
    if (url.includes(`/api/v1/stats/${targetId}`)) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(STATS) });
    }
    if (url.includes('/api/v1/stats/me')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(MY_STATS) });
    }
    if (url.includes('/api/v1/me/home')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(HOME_WITH_ROLLUP) });
    }
    if (url.includes('/predictions/recent')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(RECENT_PREDS) });
    }
    return Promise.reject(new Error(`Unexpected fetch: ${url}`));
  });
}

function makeQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

const FAKE_JWT = 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJwMSIsImV4cCI6OTk5OTk5OTk5OX0.fake';

function renderPage(
  playerId: string = PLAYER_ID,
  currentUserId: string = MY_ID,
  profilePreds: Record<string, unknown> = PROFILE_PREDS,
) {
  const storedPlayer = JSON.stringify({
    id: currentUserId,
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

  vi.stubGlobal('fetch', makeFetch(playerId, profilePreds));

  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <MemoryRouter initialEntries={[`/players/${playerId}`]}>
        <AuthProvider>
          <Routes>
            <Route path="/players/:id" element={<PlayerProfilePage />} />
          </Routes>
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

describe('PlayerProfilePage', () => {
  it('renders the player name as heading', async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Bob');
    });
  });

  it('shows total points stat card', async () => {
    renderPage();
    await waitFor(() => {
      // "Total Points" and "54" appear in both stat card and H2H column
      expect(screen.getAllByText('Total Points').length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText('54').length).toBeGreaterThanOrEqual(1);
    });
  });

  it('shows accuracy and exact rate', async () => {
    renderPage();
    await waitFor(() => {
      // 66.7% appears in stat card and H2H column
      expect(screen.getAllByText('66.7%').length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText('Exact Score')).toBeInTheDocument();
      expect(screen.getAllByText('25%').length).toBeGreaterThanOrEqual(1);
    });
  });

  it('shows best and worst round', async () => {
    renderPage();
    await waitFor(() => {
      // 'Group Stage' appears in best-round section and recent-preds stage column
      expect(screen.getAllByText('Group Stage').length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText('Round of 16')).toBeInTheDocument();
      expect(screen.getByText('40 pts')).toBeInTheDocument();
    });
  });

  it('shows H2H mini table when viewing another player', async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText('You vs Bob')).toBeInTheDocument();
      // H2H section has a dedicated heading — check for the section header text
      expect(screen.getAllByText('Total Points').length).toBeGreaterThanOrEqual(2);
    });
  });

  it('does not show H2H table when viewing own profile', async () => {
    renderPage(MY_ID, MY_ID);
    await waitFor(() => {
      expect(screen.queryByText(/You vs/)).not.toBeInTheDocument();
    });
  });

  it('shows the latest matchday block on your own profile using the home rollup', async () => {
    renderPage(MY_ID, MY_ID);
    await waitFor(() => {
      expect(screen.getByText('Latest Matchday')).toBeInTheDocument();
      expect(screen.getByText('+10 pts')).toBeInTheDocument();
      expect(screen.getAllByText(/Brazil/).length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText(/you 2.1/i)).toBeInTheDocument();
    });
  });

  it('shows recent predictions table with match info', async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText('Recent Predictions')).toBeInTheDocument();
      expect(screen.getByText(/Brazil/)).toBeInTheDocument();
      expect(screen.getByText(/Germany/)).toBeInTheDocument();
    });
  });

  it('shows the relocated points-source breakdown on the profile', async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText('How I Earned My Points')).toBeInTheDocument();
      expect(screen.getAllByText('Match').length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText('Knockout').length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText('Special').length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText('Precision tiebreakers')).toBeInTheDocument();
      expect(
        screen.getByText(/order used when points are tied: exact, result, goals, specials, then knockout-winner picks/i),
      ).toBeInTheDocument();
    });
  });

  it('shows streak stat card', async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText('Current Streak')).toBeInTheDocument();
    });
  });

  it('includes link back to leagues hub', async () => {
    renderPage();
    await waitFor(() => {
      // PageHeader back chip renders 'Back' (navigate(-1)) in the loaded state
      expect(screen.getByText('Back')).toBeInTheDocument();
    });
  });

  // U24 — reveal-gated sections
  it('renders the locked group predictions section', async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText('Group Predictions')).toBeInTheDocument();
      expect(screen.getByText(/Argentina/)).toBeInTheDocument();
      expect(screen.getByText(/Mexico/)).toBeInTheDocument();
    });
  });

  it('renders the knockout predictions section with the backed winner', async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText('Knockout Predictions')).toBeInTheDocument();
      // France appears as both a team in the tie and the picked winner
      expect(screen.getAllByText(/France/).length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText(/Spain/)).toBeInTheDocument();
    });
  });

  it('renders the special predictions section once revealed', async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText('Special Predictions')).toBeInTheDocument();
      expect(screen.getByText('Tournament Winner')).toBeInTheDocument();
    });
  });

  it('hides the specials section when not yet revealed', async () => {
    renderPage(PLAYER_ID, MY_ID, PROFILE_PREDS_HIDDEN);
    await waitFor(() => {
      // stats still load, so the page is rendered…
      expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Bob');
    });
    // …but none of the reveal-gated sections appear
    expect(screen.queryByText('Special Predictions')).not.toBeInTheDocument();
    expect(screen.queryByText('Group Predictions')).not.toBeInTheDocument();
    expect(screen.queryByText('Knockout Predictions')).not.toBeInTheDocument();
  });

  // U33.3 — avatar is a button when viewing own profile, view-only otherwise
  it('avatar is a button when viewing own profile (isSelf)', async () => {
    renderPage(MY_ID, MY_ID);
    await waitFor(() => {
      expect(screen.getByRole('heading', { level: 1 })).toBeInTheDocument();
    });
    const avatarBtn = screen.getByRole('button', { name: /change avatar photo/i });
    expect(avatarBtn).toBeInTheDocument();
  });

  it('avatar is NOT a button when viewing another player', async () => {
    renderPage(PLAYER_ID, MY_ID);
    await waitFor(() => {
      expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Bob');
    });
    expect(screen.queryByRole('button', { name: /change avatar photo/i })).not.toBeInTheDocument();
  });
});
