import type { Page, Locator, Route } from '@playwright/test';

/** Fill a PinInput segmented component — scope to entry or confirm group using exact:true. */
export async function fillPinGroup(group: Locator, pin: string) {
  for (let i = 0; i < pin.length; i++) {
    await group.getByLabel(`PIN digit ${i + 1}`).fill(pin[i]);
  }
}

// Far-future JWT: {"sub":"p1","exp":9999999999}
export const FAKE_JWT =
  'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJwMSIsImV4cCI6OTk5OTk5OTk5OX0.fake';
export const FAKE_REFRESH = 'fake-refresh-token';

export const PLAYER = {
  id: 'p1',
  displayName: 'Alice',
  role: 'player' as const,
  timezone: 'UTC',
};

export const ADMIN_PLAYER = {
  id: 'admin1',
  displayName: 'Admin',
  role: 'admin' as const,
  timezone: 'UTC',
};

export const MOCK_LEAGUE = {
  slug: 'steele-spreadsheet',
  name: 'The Steele Spreadsheet',
  description: null,
  privacy: 'private',
  member_count: 2,
  max_members: null,
  created_at: '2026-01-01T00:00:00Z',
};

export async function seedAuth(
  page: Page,
  player: typeof PLAYER | typeof ADMIN_PLAYER = PLAYER,
) {
  await page.addInitScript(
    ({ jwt, p }) => {
      localStorage.setItem('wc2026_access', jwt);
      // No refresh token — the fake JWT expires in 2286, so refresh is never
      // needed. Omitting it keeps initialRequiresUnlock = false so the PIN
      // relock gate doesn't block mocked-API tests.
      localStorage.setItem('wc2026_player', JSON.stringify(p));
      // Suppress first-run modals so focused page tests are not blocked by onboarding UI.
      localStorage.setItem('sss_tour_seen', '1');
      localStorage.setItem('sss_notif_prompt_seen', '1');
      localStorage.setItem('sss_firstrun_launchpad_seen', '1');
      localStorage.setItem('sss_join_install_dismissed', '1');
    },
    { jwt: FAKE_JWT, p: player },
  );
}

// Abort Supabase realtime so tests don't hang on unreachable WebSocket connections
export async function blockSupabase(page: Page) {
  await page.route('**/*.supabase.co/**', (route: Route) => route.abort());
  await page.route('**/realtime/v1/**', (route: Route) => route.abort());
}

// Catch-all: fulfill any remaining /api/v1/ requests with an empty response.
// /leagues/mine returns a minimal league so LeagueProvider doesn't redirect to /welcome.
// IMPORTANT: Playwright uses LIFO ordering — the catch-all is registered FIRST (lower priority)
// and the specific /leagues/mine handler is registered SECOND (higher LIFO priority, always wins).
export async function catchAllApi(page: Page) {
  await page.route('**/api/v1/**', (route: Route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }),
  );
  // Registered after catch-all → higher LIFO priority → always wins for /leagues/mine
  await page.route('**/api/v1/leagues/mine', (route: Route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([MOCK_LEAGUE]),
    }),
  );
}

// Shared fixture data

export const GROUP_A: Record<string, unknown> = {
  id: 'g-a',
  name: 'A',
  standings: [],
};

export const TEAM_BRA = { id: 't-bra', name: 'Brazil', code: 'BRA', flag_emoji: '🇧🇷' };
export const TEAM_ARG = { id: 't-arg', name: 'Argentina', code: 'ARG', flag_emoji: '🇦🇷' };

export function makeMatch(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: 'm1',
    match_number: 1,
    stage: 'group',
    group_id: 'g-a',
    home_team: TEAM_BRA,
    away_team: TEAM_ARG,
    home_team_placeholder: null,
    away_team_placeholder: null,
    kickoff_utc: new Date(Date.now() + 3 * 24 * 60 * 60 * 1000).toISOString(),
    venue: 'Estadio Nacional',
    status: 'scheduled',
    actual_home_score: null,
    actual_away_score: null,
    extra_time: false,
    penalties: false,
    postponed_reason: null,
    ...overrides,
  };
}

export function makePrediction(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: 'pred-1',
    player_id: 'p1',
    match_id: 'm1',
    predicted_home: 2,
    predicted_away: 1,
    submitted_at: new Date().toISOString(),
    update_count: 1,
    points_awarded: null,
    updated_at: new Date().toISOString(),
    ...overrides,
  };
}
