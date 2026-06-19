import { test, expect } from '@playwright/test';
import { blockSupabase, catchAllApi, fillPinGroup, FAKE_JWT } from './helpers';

test.describe('Join flow', () => {
  test('player can join with a valid invite token and is redirected home', async ({ page }) => {
    // catchAllApi FIRST — specific handlers registered after take priority (LIFO)
    await catchAllApi(page);
    await blockSupabase(page);

    await page.route('**/api/v1/auth/invite/**', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ display_name_hint: 'Test Player' }),
      }),
    );

    await page.route('**/api/v1/auth/join', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          access_token: FAKE_JWT,
          refresh_token: 'fake-refresh',
          player: { id: 'p1', display_name: 'Test Player', role: 'player', timezone: 'UTC' },
        }),
      }),
    );

    await page.goto('/join/test-token');
    await expect(page.getByRole('heading', { name: /join the league/i })).toBeVisible();

    // Name pre-filled from hint
    await expect(page.getByLabel(/display name/i)).toHaveValue('Test Player');

    await fillPinGroup(page.getByRole('group', { name: 'PIN', exact: true }), '1234');
    await fillPinGroup(page.getByRole('group', { name: 'Confirm PIN', exact: true }), '1234');
    await page.getByRole('button', { name: /join league/i }).click();

    // window.location.href = '/' is called on success
    await expect(page).toHaveURL('/');
  });

  test('shows error when invite token is invalid', async ({ page }) => {
    await catchAllApi(page);
    await blockSupabase(page);

    await page.route('**/api/v1/auth/invite/**', (route) =>
      route.fulfill({
        status: 400,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Invite token not found or expired' }),
      }),
    );

    await page.goto('/join/bad-token');
    await expect(page.getByRole('alert')).toContainText(/not found|expired/i);
  });
});
