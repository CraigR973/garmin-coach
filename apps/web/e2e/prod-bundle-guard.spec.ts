import { test, expect } from '@playwright/test';

// Negative case: prod bundle built WITHOUT VITE_API_URL.
// The R5.1 guard (apps/web/src/lib/api.ts + AuthContext.tsx) must throw at
// module-load time. If it doesn't, this test fails — the guard has silently regressed.
test('VITE_API_URL guard throws when env var is absent from prod build', async ({ page }) => {
  const pageErrors: string[] = [];
  page.on('pageerror', (err) => pageErrors.push(err.message));

  await page.goto('/');
  await page.waitForLoadState('domcontentloaded');

  const guardError = pageErrors.find((m) => m.includes('VITE_API_URL is required'));
  expect(
    guardError,
    `R5.1 guard did not fire — VITE_API_URL was absent from the build but no module-load error was thrown. ` +
      `All page errors seen: [${pageErrors.join('; ')}]`,
  ).toBeTruthy();
});
