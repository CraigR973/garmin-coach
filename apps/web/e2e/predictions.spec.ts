import { test, expect } from '@playwright/test';
import {
  seedAuth,
  blockSupabase,
  catchAllApi,
  GROUP_A,
  makeMatch,
  makePrediction,
  FAKE_JWT,
} from './helpers';

async function mockPredictionsPage(
  page: Parameters<typeof seedAuth>[0],
  matches: Record<string, unknown>[],
  predictions: Record<string, unknown>[],
) {
  // catchAllApi registered first — more specific handlers below take priority via LIFO
  await catchAllApi(page);
  await page.route('**/api/v1/groups*', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([GROUP_A]),
    }),
  );
  await page.route('**/api/v1/matches*', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(matches),
    }),
  );
  await page.route('**/api/v1/matches?stage=group', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(matches),
    }),
  );
  await page.route('**/api/v1/predictions/me*', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(predictions),
    }),
  );
}

// ---------------------------------------------------------------------------
// Critical flow: predict → see points
// ---------------------------------------------------------------------------

test.describe('Predict → auto-fetch result → see points', () => {
  test('shows points badge for a completed match', async ({ page }) => {
    await seedAuth(page);
    await blockSupabase(page);

    const completedMatch = makeMatch({
      status: 'completed',
      actual_home_score: 2,
      actual_away_score: 1,
    });
    const prediction = makePrediction({ points_awarded: 7 });

    await mockPredictionsPage(page, [completedMatch], [prediction]);

    await page.goto('/predictions/group');

    await expect(page.getByTestId('points-badge')).toContainText('7 pts');
  });

  test('player can enter a score and trigger a save', async ({ page }) => {
    await seedAuth(page);
    await blockSupabase(page);

    const scheduledMatch = makeMatch();
    const emptyPrediction = makePrediction({
      predicted_home: null,
      predicted_away: null,
      points_awarded: null,
    });

    await mockPredictionsPage(page, [scheduledMatch], [emptyPrediction]);

    let saveCalled = false;
    await page.route('**/api/v1/predictions/m1', (route) => {
      saveCalled = true;
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ...emptyPrediction, predicted_home: 2, predicted_away: 0 }),
      });
    });

    await page.goto('/predictions/group');

    const homeInput = page.getByRole('spinbutton', { name: 'Home score for match 1' });
    await homeInput.fill('2');
    const awayInput = page.getByRole('spinbutton', { name: 'Away score for match 1' });
    await awayInput.fill('0');

    await page.getByRole('button', { name: /save group a/i }).click();

    await expect.poll(() => saveCalled, { timeout: 5000 }).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Lock enforcement
// ---------------------------------------------------------------------------

test.describe('Lock enforcement', () => {
  test('score inputs are disabled for locked matches', async ({ page }) => {
    await seedAuth(page);
    await blockSupabase(page);

    const lockedMatch = makeMatch({ status: 'locked' });
    const prediction = makePrediction({ predicted_home: 1, predicted_away: 0 });

    await mockPredictionsPage(page, [lockedMatch], [prediction]);

    await page.goto('/predictions/group');

    const homeInput = page.getByRole('spinbutton', { name: 'Home score for match 1' });
    await expect(homeInput).toBeDisabled();
    const awayInput = page.getByRole('spinbutton', { name: 'Away score for match 1' });
    await expect(awayInput).toBeDisabled();
  });
});

// ---------------------------------------------------------------------------
// Reschedule flow
// ---------------------------------------------------------------------------

test.describe('Reschedule flow', () => {
  test('new kickoff time is displayed when match is rescheduled', async ({ page }) => {
    await seedAuth(page);
    await blockSupabase(page);

    const rescheduledMatch = makeMatch({ kickoff_utc: '2026-06-15T20:00:00Z' });

    await mockPredictionsPage(page, [rescheduledMatch], []);

    await page.goto('/predictions/group');

    const card = page.getByTestId('prediction-card-m1');
    await expect(card).toContainText('15 Jun');
  });
});

// ---------------------------------------------------------------------------
// Postponement flow
// ---------------------------------------------------------------------------

test.describe('Postponement flow', () => {
  test('postponed match shows Postponed badge and inputs are disabled', async ({ page }) => {
    await seedAuth(page);
    await blockSupabase(page);

    const postponedMatch = makeMatch({
      status: 'postponed',
      postponed_reason: 'Venue unavailable',
    });
    const prediction = makePrediction({ predicted_home: 1, predicted_away: 1 });

    await mockPredictionsPage(page, [postponedMatch], [prediction]);

    await page.goto('/predictions/group');

    const card = page.getByTestId('prediction-card-m1');
    await expect(card).toContainText('Postponed');
    await expect(card).toContainText('Venue unavailable');

    const homeInput = page.getByRole('spinbutton', { name: 'Home score for match 1' });
    await expect(homeInput).toBeDisabled();
  });
});

// ---------------------------------------------------------------------------
// Login → predictions (full critical flow start)
// ---------------------------------------------------------------------------

test.describe('Login → predict flow', () => {
  test('player can log in and reach the predictions page', async ({ page }) => {
    await catchAllApi(page);
    await blockSupabase(page);

    // Suppress first-run onboarding so FirstRunController doesn't redirect to /about
    // after login completes (this test exercises JWT/predictions, not onboarding).
    await page.addInitScript(() => {
      localStorage.setItem('sss_tour_seen', '1');
      localStorage.setItem('sss_notif_prompt_seen', '1');
      localStorage.setItem('sss_firstrun_launchpad_seen', '1');
    });

    await page.route('**/api/v1/auth/login', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          access_token: FAKE_JWT,
          refresh_token: 'fake-refresh',
          player: { id: 'p1', display_name: 'Alice', role: 'player', timezone: 'UTC' },
        }),
      }),
    );

    await page.route('**/api/v1/groups*', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([GROUP_A]),
      }),
    );
    await page.route('**/api/v1/matches?stage=group', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([makeMatch()]),
      }),
    );
    await page.route('**/api/v1/matches*', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([makeMatch()]),
      }),
    );
    await page.route('**/api/v1/predictions/me*', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([makePrediction()]),
      }),
    );

    await page.goto('/login');
    // LoginPage now uses email + PIN (no combobox name picker)
    await page.getByLabel('Email').fill('alice@example.com');
    await page.getByLabel('PIN digit 1').fill('1');
    await page.getByRole('button', { name: /sign in/i }).click();

    await page.goto('/predictions/group');
    await expect(page.getByTestId('prediction-card-m1')).toBeVisible();
  });
});
