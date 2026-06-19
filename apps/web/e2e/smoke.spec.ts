/**
 * Full-stack smoke test: join → predict → lock → result → leaderboard.
 *
 * Requires a running FastAPI backend at http://localhost:8000 and a seeded
 * Postgres database. Run locally with: pnpm e2e:smoke
 * In CI this runs in the dedicated "smoke" job (see .github/workflows/ci.yml).
 *
 * Scoring expectation: predicted 1-0, actual 1-0, group stage → 7 pts
 *   (3 pts correct result + 4 pts exact score bonus).
 */
import { type APIRequestContext, type Locator, type Page, expect, test } from '@playwright/test';
import { blockSupabase } from './helpers';

const API_URL = 'http://localhost:8000';
const PLAYER_NAME = 'SmokePlayer';
const PLAYER_PIN = '2222';
// The seed makes the admin an admin of the default Steele league; M5 moved
// invite creation under /leagues/{slug}/.
const LEAGUE_SLUG = 'steele-spreadsheet';

// Run all tests in this file in declaration order — each step feeds the next.
test.describe.configure({ mode: 'serial' });

async function fillPinGroup(group: Locator, pin: string) {
  for (let i = 0; i < pin.length; i++) {
    await group.getByLabel(`PIN digit ${i + 1}`).fill(pin[i]);
  }
}

async function unlockStoredSessionIfNeeded(page: Page) {
  const unlockHeading = page.getByRole('heading', { name: 'Unlock Calcio' });
  const isLocked = await unlockHeading.isVisible({ timeout: 3_000 }).catch(() => false);
  if (!isLocked) return;

  const pinEntry = page.getByRole('group', { name: 'PIN', exact: true });
  await fillPinGroup(pinEntry, PLAYER_PIN);
  await page.getByRole('button', { name: 'Unlock with PIN' }).click();
}

test.describe('Smoke: join → predict → lock → score → leaderboard', () => {
  let api: APIRequestContext;
  let adminJwt: string;
  let matchId: string;
  let inviteToken: string;
  let playerJwt: string;
  let playerStoredJson: string;  // raw JSON string from localStorage('wc2026_player')
  let playerRefresh: string;

  test.beforeAll(async ({ playwright }) => {
    api = await playwright.request.newContext({ baseURL: API_URL });

    // Wipe any leftover state from a previous interrupted run or Playwright retry.
    await api.delete('/api/v1/test/cleanup');

    // Seed admin profile + group + teams + match.
    const seedResp = await api.post('/api/v1/test/seed');
    expect(seedResp.ok(), `seed failed: ${await seedResp.text()}`).toBeTruthy();
    const seed = await seedResp.json();
    matchId = seed.match_id;

    // Authenticate as the seeded admin (login uses email + pin since M9).
    const loginResp = await api.post('/api/v1/auth/login', {
      data: { email: seed.admin_email, pin: seed.admin_pin },
    });
    expect(loginResp.ok(), `admin login failed: ${await loginResp.text()}`).toBeTruthy();
    adminJwt = (await loginResp.json()).access_token;

    // Create a single-use invite for the smoke player (per-league since M5).
    const inviteResp = await api.post(`/api/v1/leagues/${LEAGUE_SLUG}/invites`, {
      headers: { Authorization: `Bearer ${adminJwt}` },
      data: { display_name_hint: PLAYER_NAME },
    });
    expect(inviteResp.status(), `invite create failed: ${await inviteResp.text()}`).toBe(201);
    inviteToken = (await inviteResp.json()).token;
  });

  test.afterAll(async () => {
    await api.delete('/api/v1/test/cleanup');
    await api.dispose();
  });

  test('player joins via invite link', async ({ page }) => {
    // Block Supabase realtime — placeholder URLs would cause connection errors
    // that can interfere with page navigation in the smoke environment.
    await blockSupabase(page);

    // Capture browser console errors for diagnostics if the test fails.
    const consoleErrors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') consoleErrors.push(msg.text());
    });

    await page.goto(`/join/${inviteToken}`);
    await expect(page.getByRole('heading', { name: /join the league/i })).toBeVisible();

    // The hint pre-fills the name field; overwrite to ensure our known value.
    await page.getByLabel(/display name/i).fill(PLAYER_NAME);
    // PinInput renders individual cells — fill each digit into its labelled cell
    // exact: true is required; without it 'PIN' substring-matches 'Confirm PIN' too
    const pinEntry = page.getByRole('group', { name: 'PIN', exact: true });
    const pinConfirm = page.getByRole('group', { name: 'Confirm PIN', exact: true });
    await fillPinGroup(pinEntry, PLAYER_PIN);
    await fillPinGroup(pinConfirm, PLAYER_PIN);
    await page.getByRole('button', { name: /join league/i }).click();

    // If the join POST fails the page shows a [role="alert"] and stays put.
    // Surface that message immediately rather than timing out with no signal.
    const alert = page.locator('[role="alert"]');
    const didAlert = await alert.isVisible({ timeout: 3_000 }).catch(() => false);
    if (didAlert) {
      const alertText = await alert.textContent().catch(() => '(unreadable)');
      throw new Error(
        `Join form returned an error: "${alertText}". Console errors: ${JSON.stringify(consoleErrors)}`,
      );
    }

    // After joining, new users are redirected to /about (U45 first-run flow).
    // Match the full URL — the intermediate / may be too brief to observe.
    await expect(page).toHaveURL(/\/(about)?$/, { timeout: 10_000 });

    // Capture all 3 auth keys so the leaderboard test can restore a full session.
    const stored = await page.evaluate(() => ({
      access: localStorage.getItem('wc2026_access') ?? '',
      refresh: localStorage.getItem('wc2026_refresh') ?? '',
      player: localStorage.getItem('wc2026_player') ?? '',
    }));
    playerJwt = stored.access;
    playerRefresh = stored.refresh;
    playerStoredJson = stored.player;
    expect(playerJwt, 'access token was not stored after join').not.toBe('');
  });

  test('player predicts the seeded match', async () => {
    // Call the API directly using the JWT obtained from the browser session above.
    const resp = await api.put(`/api/v1/predictions/${matchId}`, {
      headers: { Authorization: `Bearer ${playerJwt}` },
      data: { predicted_home: 1, predicted_away: 0 },
    });
    expect(resp.ok(), `prediction failed: ${await resp.text()}`).toBeTruthy();
  });

  test('match is locked and admin enters the result', async () => {
    // Advance kickoff to the past and flip status=locked — bypasses the scheduler.
    const lockResp = await api.post(`/api/v1/test/lock-now/${matchId}`);
    expect(lockResp.status()).toBe(204);

    // Enter result: home 1-0 away (matches prediction → 7 pts).
    const resultResp = await api.post(`/api/v1/admin/results/${matchId}`, {
      headers: { Authorization: `Bearer ${adminJwt}` },
      data: {
        actual_home_score: 1,
        actual_away_score: 0,
        extra_time: false,
        penalties: false,
      },
    });
    expect(resultResp.ok(), `result entry failed: ${await resultResp.text()}`).toBeTruthy();
  });

  test('player appears on leaderboard with correct points', async ({ page }) => {
    await blockSupabase(page);

    // Restore all three auth keys so ProtectedRoute sees an authenticated session.
    // AuthContext reads wc2026_player synchronously on mount — setting only
    // wc2026_access would leave player=null and trigger a redirect to /login.
    // Also set firstrun keys so FirstRunController doesn't redirect to /about.
    await page.addInitScript(
      ({ access, refresh, player }: { access: string; refresh: string; player: string }) => {
        localStorage.setItem('wc2026_access', access);
        localStorage.setItem('wc2026_refresh', refresh);
        localStorage.setItem('wc2026_player', player);
        localStorage.setItem('sss_tour_seen', '1');
        localStorage.setItem('sss_notif_prompt_seen', '1');
        localStorage.setItem('sss_firstrun_launchpad_seen', '1');
      },
      { access: playerJwt, refresh: playerRefresh, player: playerStoredJson },
    );

    await page.goto(`/leagues/${LEAGUE_SLUG}/leaderboard`);
    await unlockStoredSessionIfNeeded(page);

    // Wait for a row containing the smoke player's name.
    const playerRow = page
      .locator('[data-testid^="leaderboard-row"]')
      .filter({ hasText: PLAYER_NAME });
    await expect(playerRow).toBeVisible({ timeout: 15_000 });

    // Predicted 1-0, actual 1-0, group stage:
    //   2 pts (correct total goals: 1+0 = 1+0)
    //   3 pts (correct result: home win)
    //   5 pts (exact scoreline)
    //   = 10 pts total
    await expect(playerRow).toContainText('10');
  });
});
