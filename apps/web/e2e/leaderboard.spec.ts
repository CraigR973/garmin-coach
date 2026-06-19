import { test, expect } from '@playwright/test';
import { seedAuth, blockSupabase, catchAllApi } from './helpers';

const LEADERBOARD = [
  {
    rank: 1,
    player_id: 'p1',
    player_name: 'Alice',
    total_points: 45,
    match_points: 40,
    knockout_winner_points: 5,
    special_points: 0,
    is_active: true,
  },
  {
    rank: 2,
    player_id: 'p2',
    player_name: 'Bob',
    total_points: 38,
    match_points: 35,
    knockout_winner_points: 3,
    special_points: 0,
    is_active: true,
  },
];

// Slug seeded by seedAuth (matches MOCK_LEAGUE.slug)
const SLUG = 'steele-spreadsheet';

test.describe('Leaderboard', () => {
  test('shows players ranked by points', async ({ page }) => {
    await seedAuth(page);
    await blockSupabase(page);
    // catchAllApi FIRST, specific route registered after takes priority (LIFO)
    await catchAllApi(page);

    await page.route('**/api/v1/leagues/*/leaderboard', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(LEADERBOARD),
      }),
    );

    await page.goto(`/leagues/${SLUG}/leaderboard`);

    await expect(page.getByTestId('leaderboard-row-p1')).toBeVisible();
    await expect(page.getByTestId('leaderboard-row-p2')).toBeVisible();

    const rows = page.getByTestId(/^leaderboard-row-/);
    await expect(rows.first()).toContainText('Alice');
  });

  test('leaderboard update: re-entering the page reflects new scores', async ({ page }) => {
    await seedAuth(page);
    await blockSupabase(page);
    await catchAllApi(page);

    let callCount = 0;
    await page.route('**/api/v1/leagues/*/leaderboard', (route) => {
      callCount++;
      const data =
        callCount === 1
          ? LEADERBOARD
          : [
              { ...LEADERBOARD[0], total_points: 52 },
              { ...LEADERBOARD[1], total_points: 38 },
            ];
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) });
    });

    await page.goto(`/leagues/${SLUG}/leaderboard`);
    await expect(page.getByTestId('leaderboard-row-p1')).toContainText('45');

    // Navigate away and back — triggers a fresh fetch
    await page.goto('/');
    await page.goto(`/leagues/${SLUG}/leaderboard`);
    await expect(page.getByTestId('leaderboard-row-p1')).toContainText('52');
  });

  test('old /leaderboard URL redirects to leagues hub', async ({ page }) => {
    await seedAuth(page);
    await blockSupabase(page);
    await catchAllApi(page);

    await page.goto('/leaderboard');

    // M9: old /leaderboard redirects to the Leagues hub, not a per-league URL
    await expect(page).toHaveURL('/leagues');
  });
});
