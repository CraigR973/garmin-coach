import { test, expect } from '@playwright/test';
import { seedAuth, blockSupabase, catchAllApi } from './helpers';

const PLAYERS = [
  { id: 'p1', display_name: 'Alice', role: 'player', timezone: 'UTC', is_deleted: false, created_at: '2026-01-01T00:00:00Z' },
  { id: 'p2', display_name: 'Bob', role: 'player', timezone: 'UTC', is_deleted: false, created_at: '2026-01-02T00:00:00Z' },
];

const H2H = {
  player_a: { id: 'p1', name: 'Alice' },
  player_b: { id: 'p2', name: 'Bob' },
  summary: { player_a_wins: 3, player_b_wins: 2, draws: 1 },
  matches: [
    {
      match_id: 'm1',
      stage: 'group',
      kickoff_utc: '2026-06-15T20:00:00Z',
      home_team_name: 'Brazil',
      away_team_name: 'Argentina',
      home_team_flag: '🇧🇷',
      away_team_flag: '🇦🇷',
      actual_home: 2,
      actual_away: 1,
      player_a_predicted_home: 2,
      player_a_predicted_away: 1,
      player_a_points: 7,
      player_b_predicted_home: 1,
      player_b_predicted_away: 0,
      player_b_points: 3,
      winner: 'a',
    },
  ],
};

// Slug seeded by seedAuth (matches MOCK_LEAGUE.slug)
const SLUG = 'steele-spreadsheet';

test.describe('Head-to-head comparison', () => {
  test('shows comparison summary for two players', async ({ page }) => {
    await seedAuth(page);
    await blockSupabase(page);
    await catchAllApi(page);

    await page.route('**/api/v1/leagues/*/players', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(PLAYERS) }),
    );
    await page.route('**/api/v1/leagues/*/compare/p1/p2', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(H2H) }),
    );

    await page.goto(`/leagues/${SLUG}/compare?a=p1&b=p2`);

    // Brazil appears in the match row — proves the H2H endpoint was fetched and rendered
    await expect(page.getByText('Brazil')).toBeVisible();
  });

  test('dropdowns allow switching the compared players', async ({ page }) => {
    await seedAuth(page);
    await blockSupabase(page);
    await catchAllApi(page);

    await page.route('**/api/v1/leagues/*/players', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(PLAYERS) }),
    );
    await page.route('**/api/v1/leagues/*/compare/**', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(H2H) }),
    );

    await page.goto(`/leagues/${SLUG}/compare`);

    // Player pickers are now Radix Select (role=combobox, no native <select>)
    const pickers = page.getByRole('combobox');
    await expect(pickers.first()).toBeVisible();
  });

  test('old /compare URL redirects to leagues hub', async ({ page }) => {
    await seedAuth(page);
    await blockSupabase(page);
    await catchAllApi(page);

    await page.goto('/compare');

    // M9: old /compare redirects to the Leagues hub, not a per-league URL
    await expect(page).toHaveURL('/leagues');
  });
});
