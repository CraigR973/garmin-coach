import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? 'github' : 'html',
  use: {
    baseURL: 'http://localhost:5173',
    trace: 'on-first-retry',
  },
  projects: [
    // Mocked tests (no backend required) — exclude smoke + prod-bundle tests
    { name: 'chromium', testIgnore: ['**/smoke.spec.ts', '**/prod-bundle*.spec.ts'], use: { ...devices['Desktop Chrome'] } },
    { name: 'firefox', testIgnore: ['**/smoke.spec.ts', '**/prod-bundle*.spec.ts'], use: { ...devices['Desktop Firefox'] } },
    { name: 'webkit', testIgnore: ['**/smoke.spec.ts', '**/prod-bundle*.spec.ts'], use: { ...devices['Desktop Safari'] } },
    // Full-stack smoke test — requires FastAPI + Postgres running locally
    { name: 'smoke', testMatch: ['**/smoke.spec.ts'], use: { ...devices['Desktop Chrome'] } },
  ],
  webServer: {
    command: 'pnpm dev',
    url: 'http://localhost:5173',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
