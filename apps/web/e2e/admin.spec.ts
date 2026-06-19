import { test, expect } from '@playwright/test';
import { seedAuth, blockSupabase, catchAllApi, ADMIN_PLAYER } from './helpers';

const SYNC_STATUS = {
  last_sync_at: '2026-05-16T10:00:00Z',
  last_sync_action: 'result_auto_fetched',
  next_run_at: new Date(Date.now() + 30 * 60 * 1000).toISOString(),
  recent_errors: [],
};

const RESULT_WITH_OVERRIDE = {
  match_id: 'm1',
  match_number: 1,
  status: 'completed',
  kickoff_utc: '2026-06-15T20:00:00Z',
  home_team: 'Brazil',
  away_team: 'Argentina',
  actual_home_score: 2,
  actual_away_score: 1,
  extra_time: false,
  penalties: false,
  result_source: 'override',
  result_entered_at: '2026-06-15T22:15:00Z',
};

test.describe('Admin override', () => {
  test('admin can trigger a manual sync (override)', async ({ page }) => {
    await seedAuth(page, ADMIN_PLAYER);
    await blockSupabase(page);
    await catchAllApi(page);

    await page.route('**/api/v1/admin/sync/status', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(SYNC_STATUS),
      }),
    );

    let triggerCalled = false;
    await page.route('**/api/v1/admin/sync/trigger', (route) => {
      triggerCalled = true;
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ...SYNC_STATUS, last_sync_action: 'sync_triggered' }),
      });
    });

    await page.goto('/admin/sync');
    await expect(page.getByRole('heading', { name: /sync status/i })).toBeVisible();

    await page.getByRole('button', { name: /sync now/i }).click();

    await expect.poll(() => triggerCalled, { timeout: 5000 }).toBe(true);
    await expect(page.getByText('Sync triggered successfully')).toBeVisible();
  });

  test('admin results page shows override-tagged results', async ({ page }) => {
    await seedAuth(page, ADMIN_PLAYER);
    await blockSupabase(page);
    await catchAllApi(page);

    await page.route('**/api/v1/admin/results', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([RESULT_WITH_OVERRIDE]),
      }),
    );

    await page.goto('/admin/results');

    await expect(page.getByText('Brazil')).toBeVisible();
    await expect(page.getByText('Override', { exact: true })).toBeVisible();
  });

  test('non-admin is redirected away from admin pages', async ({ page }) => {
    await seedAuth(page); // regular player
    await blockSupabase(page);
    await catchAllApi(page);

    await page.goto('/admin/sync');

    // ProtectedRoute with requireAdmin redirects non-admins to /
    await expect(page).toHaveURL('/');
  });

  test('superadmin can view all leagues on /admin/all-leagues', async ({ page }) => {
    await seedAuth(page, ADMIN_PLAYER);
    await blockSupabase(page);
    await catchAllApi(page);

    const LEAGUES = [
      { slug: 'steele-spreadsheet', name: 'The Steele Spreadsheet', privacy: 'private', member_count: 5, created_at: '2026-01-01T00:00:00Z' },
      { slug: 'test-league', name: 'Test League', privacy: 'public_open', member_count: 2, created_at: '2026-02-01T00:00:00Z' },
    ];

    await page.route('**/api/v1/admin/leagues', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(LEAGUES),
      }),
    );

    await page.goto('/admin/all-leagues');

    await expect(page.getByText('The Steele Spreadsheet')).toBeVisible();
    await expect(page.getByText('Test League')).toBeVisible();
  });

  test('superadmin can delete a league from /admin/all-leagues', async ({ page }) => {
    await seedAuth(page, ADMIN_PLAYER);
    await blockSupabase(page);
    await catchAllApi(page);

    const LEAGUES = [
      { slug: 'test-league', name: 'Test League', privacy: 'public_open', member_count: 1, created_at: '2026-02-01T00:00:00Z' },
    ];

    await page.route('**/api/v1/admin/leagues', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(LEAGUES),
      }),
    );

    let deleteCalled = false;
    await page.route('**/api/v1/leagues/test-league', (route) => {
      if (route.request().method() === 'DELETE') {
        deleteCalled = true;
        route.fulfill({ status: 204 });
      } else {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(LEAGUES[0]),
        });
      }
    });

    await page.goto('/admin/all-leagues');
    await expect(page.getByText('Test League')).toBeVisible();

    // Click delete button for the test league
    await page.getByRole('button', { name: /delete test league/i }).click();

    // Confirm dialog appears
    await expect(page.getByRole('dialog')).toBeVisible();
    await page.getByRole('button', { name: /delete league/i }).click();

    await expect.poll(() => deleteCalled, { timeout: 5000 }).toBe(true);
  });
});
