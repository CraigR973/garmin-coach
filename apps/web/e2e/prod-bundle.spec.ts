import { test, expect } from '@playwright/test';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';

function readDistTextFiles(dir: string): string {
  return readdirSync(dir)
    .map((entry) => {
      const fullPath = join(dir, entry);
      if (statSync(fullPath).isDirectory()) return readDistTextFiles(fullPath);
      if (!/\.(html|js|css|json|txt|svg)$/.test(entry)) return '';
      return readFileSync(fullPath, 'utf8');
    })
    .join('\n');
}

// Positive case: prod bundle built WITH VITE_API_URL must load without errors.
test('prod bundle loads without page errors when VITE_API_URL is set', async ({ page }) => {
  const pageErrors: string[] = [];
  page.on('pageerror', (err) => pageErrors.push(err.message));

  await page.goto('/');
  await page.waitForLoadState('domcontentloaded');

  expect(
    pageErrors,
    `Unexpected page errors in prod bundle: ${pageErrors.join(', ')}`,
  ).toHaveLength(0);

  // Page must render something — not a blank screen
  const bodyHTML = await page.locator('body').innerHTML();
  expect(bodyHTML.trim().length, 'Page body should not be empty').toBeGreaterThan(0);
});

test('prod bundle does not contain dev mock auth bypass strings', async () => {
  const bundleText = readDistTextFiles(join(process.cwd(), 'dist'));

  expect(bundleText).not.toContain('__wc2026_dev_mock__');
  expect(bundleText).not.toContain('Dev-only mock bypass');
});
