/**
 * Multi-league end-to-end spec.
 *
 * Covers the full acceptance flow:
 *   signup → create league → create invite → join → predict → leaderboard
 *
 * All API calls are mocked at the Playwright route level. LIFO ordering rule:
 * register catch-all FIRST, specific routes AFTER (last registered = highest priority).
 */
import { test, expect } from '@playwright/test';
import {
  blockSupabase,
  catchAllApi,
  fillPinGroup,
  FAKE_JWT,
  FAKE_REFRESH,
  GROUP_A,
  MOCK_LEAGUE,
  PLAYER,
  seedAuth,
  makeMatch,
  makePrediction,
} from './helpers';

// ---------------------------------------------------------------------------
// 1. Signup — new player can create an account
// ---------------------------------------------------------------------------

test.describe('signup', () => {
  test('new player can sign up and is redirected to dashboard', async ({ page }) => {
    // catchAllApi FIRST so specific routes take priority (LIFO)
    await catchAllApi(page);
    await blockSupabase(page);

    await page.route('**/api/v1/auth/signup', (route) =>
      route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({
          access_token: FAKE_JWT,
          refresh_token: FAKE_REFRESH,
          player: { id: 'p-new', display_name: 'Alice S.', role: 'player', timezone: 'UTC' },
        }),
      }),
    );

    await page.goto('/signup');
    await expect(page.getByRole('heading', { name: /create account/i })).toBeVisible();

    await page.getByLabel(/email/i).fill('alice@example.com');
    await page.getByLabel(/first name/i).fill('Alice');
    await page.getByLabel(/last name/i).fill('Smith');
    await fillPinGroup(page.getByRole('group', { name: 'PIN', exact: true }), '1234');
    await fillPinGroup(page.getByRole('group', { name: 'Confirm PIN', exact: true }), '1234');
    await page.getByRole('button', { name: /create account/i }).click();

    await expect(page).toHaveURL('/');
  });

  test('shows error when email already exists', async ({ page }) => {
    await catchAllApi(page);
    await blockSupabase(page);

    await page.route('**/api/v1/auth/signup', (route) =>
      route.fulfill({
        status: 409,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Email already registered' }),
      }),
    );

    await page.goto('/signup');
    await page.getByLabel(/email/i).fill('alice@example.com');
    await page.getByLabel(/first name/i).fill('Alice');
    await page.getByLabel(/last name/i).fill('Smith');
    await fillPinGroup(page.getByRole('group', { name: 'PIN', exact: true }), '1234');
    await fillPinGroup(page.getByRole('group', { name: 'Confirm PIN', exact: true }), '1234');
    await page.getByRole('button', { name: /create account/i }).click();

    await expect(page.getByRole('alert')).toContainText(/already exists/i);
  });
});

// ---------------------------------------------------------------------------
// 2. Create league — authenticated player can create a league
// ---------------------------------------------------------------------------

test.describe('create league', () => {
  test('admin can create a league and is redirected to the league page', async ({ page }) => {
    await seedAuth(page);
    await catchAllApi(page);
    await blockSupabase(page);

    const newLeague = { ...MOCK_LEAGUE, slug: 'my-new-league', name: 'My New League' };

    await page.route('**/api/v1/leagues', (route) => {
      if (route.request().method() === 'POST') {
        route.fulfill({
          status: 201,
          contentType: 'application/json',
          body: JSON.stringify(newLeague),
        });
      } else {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify([MOCK_LEAGUE]),
        });
      }
    });

    await page.goto('/leagues/new');
    await expect(page.getByRole('heading', { name: /create a league/i })).toBeVisible();

    await page.getByLabel(/league name/i).fill('My New League');
    await page.getByRole('button', { name: /create league/i }).click();

    await expect(page).toHaveURL('/leagues/my-new-league/leaderboard');
  });

  test('shows validation error when league name is empty', async ({ page }) => {
    await seedAuth(page);
    await catchAllApi(page);
    await blockSupabase(page);

    await page.goto('/leagues/new');
    await page.getByRole('button', { name: /create league/i }).click();
    // HTML5 required validation fires — league name input is required
    const nameInput = page.getByLabel(/league name/i);
    await expect(nameInput).toBeFocused();
  });
});

// ---------------------------------------------------------------------------
// 3. Invite — admin can create an invite link
// ---------------------------------------------------------------------------

test.describe('create invite', () => {
  test('admin sees invite link after creating an invite', async ({ page }) => {
    await seedAuth(page, { ...PLAYER, role: 'admin' });
    await catchAllApi(page);
    await blockSupabase(page);

    const createdInvite = {
      id: 'inv-1',
      token: 'tok-abc123',
      league_id: 'league-1',
      created_by: 'p1',
      invitee_email: null,
      display_name_hint: null,
      expires_at: new Date(Date.now() + 7 * 86400 * 1000).toISOString(),
      used_at: null,
      created_at: new Date().toISOString(),
    };

    await page.route(`**/api/v1/leagues/${MOCK_LEAGUE.slug}/invites`, (route) => {
      if (route.request().method() === 'POST') {
        route.fulfill({
          status: 201,
          contentType: 'application/json',
          body: JSON.stringify(createdInvite),
        });
      } else {
        // Return the created invite so the token is visible in the list
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify([createdInvite]),
        });
      }
    });

    await page.goto(`/leagues/${MOCK_LEAGUE.slug}/admin/invites`);
    await expect(page.getByRole('heading', { name: 'Invites', exact: true })).toBeVisible();

    // "Generate invite link" is inside the collapsed "Advanced" disclosure — open it first
    await page.getByText('Advanced: one-time private link').click();
    await page.getByRole('button', { name: /generate invite link/i }).click();

    // After creation the invite link (containing the token) should appear on the page
    await expect(page.getByText('tok-abc123')).toBeVisible();
  });
});

// ---------------------------------------------------------------------------
// 4. Join — a player can join a league via an invite token
// ---------------------------------------------------------------------------

test.describe('join via invite', () => {
  test('player can accept an invite and land on the league page', async ({ page }) => {
    await catchAllApi(page);
    await blockSupabase(page);

    await page.route('**/api/v1/auth/invite/**', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ display_name_hint: 'Bob J.' }),
      }),
    );

    await page.route('**/api/v1/auth/join', (route) =>
      route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({
          access_token: FAKE_JWT,
          refresh_token: FAKE_REFRESH,
          player: { id: 'p2', display_name: 'Bob J.', role: 'player', timezone: 'UTC' },
        }),
      }),
    );

    await page.goto('/join/tok-abc123');
    await expect(page.getByRole('heading', { name: /join the league/i })).toBeVisible();
    await expect(page.getByLabel(/display name/i)).toHaveValue('Bob J.');

    await fillPinGroup(page.getByRole('group', { name: 'PIN', exact: true }), '5678');
    await fillPinGroup(page.getByRole('group', { name: 'Confirm PIN', exact: true }), '5678');
    await page.getByRole('button', { name: /join league/i }).click();

    await expect(page).toHaveURL('/');
  });
});

// ---------------------------------------------------------------------------
// 5. Predict — player can submit a prediction for a match
// ---------------------------------------------------------------------------

test.describe('predictions', () => {
  test('player can submit a score prediction for an upcoming match', async ({ page }) => {
    await seedAuth(page);
    await catchAllApi(page);
    await blockSupabase(page);

    const match = makeMatch({ id: 'm-wc1', status: 'scheduled', group_id: GROUP_A.id });
    const prediction = makePrediction({ match_id: 'm-wc1', predicted_home: 2, predicted_away: 1 });

    // Group predictions now live at /predictions/group. The all-matches checklist
    // at /predictions uses the same predictions feed plus the full matches feed.
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
        body: JSON.stringify([match]),
      }),
    );

    await page.route('**/api/v1/matches*', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([match]),
      }),
    );

    await page.route('**/api/v1/predictions*', (route) => {
      if (route.request().method() === 'POST' || route.request().method() === 'PUT') {
        route.fulfill({
          status: route.request().method() === 'POST' ? 201 : 200,
          contentType: 'application/json',
          body: JSON.stringify(prediction),
        });
      } else {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify([]),
        });
      }
    });

    await page.goto('/predictions/group');
    await expect(page.getByTestId(`prediction-card-${match.id}`)).toBeVisible();

    // Fill in home and away score (spinbuttons are inside the card)
    const card = page.getByTestId(`prediction-card-${match.id}`);
    await card.getByRole('spinbutton').nth(0).fill('2');
    await card.getByRole('spinbutton').nth(1).fill('1');

    // Save button is at the group-panel level ("Save Group A"), not inside the card
    const saveBtn = page.getByRole('button', { name: /save group/i });
    await saveBtn.click();

    // After save the dirty count drops to 0 → button becomes disabled
    await expect(saveBtn).toBeDisabled();
  });
});

// ---------------------------------------------------------------------------
// 6. Leaderboard — player sees per-league standings
// ---------------------------------------------------------------------------

test.describe('leaderboard', () => {
  test('player sees the per-league leaderboard', async ({ page }) => {
    await seedAuth(page);
    await catchAllApi(page);
    await blockSupabase(page);

    const entries = [
      {
        rank: 1,
        player_id: 'p1',
        player_name: 'Alice',
        total_points: 55,
        match_points: 50,
        knockout_winner_points: 5,
        special_points: 0,
        is_active: true,
      },
      {
        rank: 2,
        player_id: 'p2',
        player_name: 'Bob',
        total_points: 30,
        match_points: 30,
        knockout_winner_points: 0,
        special_points: 0,
        is_active: true,
      },
    ];

    await page.route(`**/api/v1/leagues/${MOCK_LEAGUE.slug}/leaderboard`, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(entries),
      }),
    );

    await page.goto(`/leagues/${MOCK_LEAGUE.slug}/leaderboard`);

    await expect(page.getByTestId('leaderboard-row-p1')).toBeVisible();
    await expect(page.getByTestId('leaderboard-row-p2')).toBeVisible();

    // Alice should appear before Bob (rank 1 vs 2)
    const rows = page.getByTestId(/leaderboard-row-/);
    await expect(rows.nth(0)).toContainText('Alice');
    await expect(rows.nth(1)).toContainText('Bob');
  });

  test('old global /leaderboard path is not a success', async ({ page }) => {
    // Smoke-test that the deprecated path is not a successful API response.
    // Vite dev server returns 4xx/5xx for unhandled /api/v1/* paths.
    const resp = await page.request.get('/api/v1/leaderboard');
    expect(resp.ok()).toBe(false);
  });
});
