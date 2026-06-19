import { test, expect } from '@playwright/test';
import { blockSupabase, catchAllApi, FAKE_JWT, PLAYER } from './helpers';

test.describe('JWT refresh', () => {
  test('transparent refresh: expiring token is refreshed before the first API call', async ({
    page,
  }) => {
    // catchAllApi FIRST so specific handlers registered after take priority (LIFO)
    await catchAllApi(page);
    await blockSupabase(page);

    // Seed an access token expiring in 30s — isAccessTokenExpiringSoon() returns true
    await page.addInitScript((player) => {
      const exp = Math.floor(Date.now() / 1000) + 30;
      const payload = btoa(JSON.stringify({ sub: player.id, exp }));
      const expiringJwt = `eyJhbGciOiJIUzI1NiJ9.${payload}.fake`;
      localStorage.setItem('wc2026_access', expiringJwt);
      localStorage.setItem('wc2026_refresh', 'old-refresh-token');
      localStorage.setItem('wc2026_player', JSON.stringify(player));
      // Suppress first-run onboarding so FirstRunController doesn't redirect away
      localStorage.setItem('sss_tour_seen', '1');
      localStorage.setItem('sss_notif_prompt_seen', '1');
      localStorage.setItem('sss_firstrun_launchpad_seen', '1');
    }, PLAYER);

    let refreshCalled = false;
    await page.route('**/api/v1/auth/refresh', (route) => {
      refreshCalled = true;
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          access_token: FAKE_JWT,
          refresh_token: 'new-refresh-token',
        }),
      });
    });

    await page.route('**/api/v1/leagues/*/leaderboard', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
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
        ]),
      }),
    );

    await page.goto('/leagues/steele-spreadsheet/leaderboard');
    await expect(page.getByTestId('leaderboard-row-p1')).toBeVisible();
    expect(refreshCalled).toBe(true);
  });

  test('on-demand refresh: 401 response triggers refresh and retries the request', async ({
    page,
  }) => {
    await catchAllApi(page);
    await blockSupabase(page);

    // Seed a valid (far-future) token so proactive refresh is skipped
    await page.addInitScript((player) => {
      localStorage.setItem(
        'wc2026_access',
        'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJwMSIsImV4cCI6OTk5OTk5OTk5OX0.fake',
      );
      localStorage.setItem('wc2026_refresh', 'valid-refresh-token');
      localStorage.setItem('wc2026_player', JSON.stringify(player));
      // Suppress first-run onboarding so FirstRunController doesn't redirect away
      localStorage.setItem('sss_tour_seen', '1');
      localStorage.setItem('sss_notif_prompt_seen', '1');
      localStorage.setItem('sss_firstrun_launchpad_seen', '1');
    }, PLAYER);

    let attempt = 0;
    await page.route('**/api/v1/leagues/*/leaderboard', (route) => {
      attempt++;
      if (attempt === 1) {
        route.fulfill({
          status: 401,
          contentType: 'application/json',
          body: '{"detail":"Unauthorized"}',
        });
      } else {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify([
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
          ]),
        });
      }
    });

    await page.route('**/api/v1/auth/refresh', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ access_token: FAKE_JWT, refresh_token: 'new-refresh' }),
      }),
    );

    await page.goto('/leagues/steele-spreadsheet/leaderboard');
    await expect(page.getByTestId('leaderboard-row-p1')).toBeVisible();
  });
});
