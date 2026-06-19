import { defineConfig, devices } from '@playwright/test';

// Separate config for prod-bundle tests. CI builds the app with vite build
// and starts vite preview manually — no managed webServer here.
export default defineConfig({
  testDir: './e2e',
  testMatch: ['**/prod-bundle*.spec.ts'],
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  reporter: process.env.CI ? 'github' : 'html',
  use: {
    baseURL: 'http://localhost:4173',
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'prod-bundle',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
