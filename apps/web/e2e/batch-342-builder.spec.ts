import { expect, test } from '@playwright/test';

const day = (offset: number) => new Date(Date.UTC(2026, 9, 19 + offset)).toISOString().slice(0, 10);
const weeks = Array.from({ length: 13 }, (_, index) => ({
  weekNumber: index + 1,
  blockType: 'build',
  label: 'BUILD',
  startDate: day(index * 7),
  endDate: day(index * 7 + 6),
  totalMin: 440,
  workouts: Array.from({ length: 7 }, (_, dayOffset) => index === 2 && dayOffset === 3 ? {
    id: 'sweet-spot', dayOffset, slot: 0, kind: 'sweet_spot',
    workoutDate: day(index * 7 + dayOffset), title: 'Sweet Spot (2 × 25 min @ 89%)',
    workoutType: 'bike_sweet_spot', plannedDurationMin: 70,
    intensityTarget: '89% FTP', structuredWorkout: { format: 'bike', steps: [] },
  } : {
    id: `ride-${index}-${dayOffset}`, dayOffset, slot: 0, kind: 'zone2',
    workoutDate: day(index * 7 + dayOffset), title: 'Endurance ride',
    workoutType: 'bike_zone2', plannedDurationMin: 60,
    intensityTarget: '65% FTP', structuredWorkout: { format: 'bike', steps: [] },
  }),
}));

test('the 13-week builder opens short and edits a 25-minute block in minutes', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('coach_device_token', 'test-device-token');
    localStorage.setItem('coach_player', JSON.stringify({
      id: '11111111-1111-4111-8111-111111111111', displayName: 'Mark',
      role: 'player', timezone: 'Europe/London',
    }));
  });
  await page.route('**/api/v1/**', async (route) => {
    if (new URL(route.request().url()).pathname === '/api/v1/block-generator') {
      await route.fulfill({ json: {
        data: {
          draft: {
            status: 'draft', framework: '13-week 2121', planName: 'Plan No. 3',
            startDate: day(0), endDate: day(90), ftpWatts: 280, athleteName: 'Mark',
            generatedAtUtc: '2026-10-12T12:00:00Z', lockedAtUtc: null, weeks,
          },
          canGenerate: false,
          sessionEdits: {
            'sweet-spot': { minutes: null, fixed: null, intervals: {
              repeat: 2, workSec: 1500, workPct: 89, restSec: 180, restPct: 60,
              label: '2 × 25 min @ 89%', matchingSets: 1,
            } },
          },
        },
        meta: { generatedAtUtc: '2026-10-12T12:00:00Z' }, errors: [],
      } });
    } else {
      await route.fulfill({ status: 404, json: { detail: 'Unavailable in this fixture' } });
    }
  });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/builder');
  await expect(page.getByRole('button', { name: 'Show weeks 3–13' })).toBeVisible();
  await expect(page.getByText('Week 13 · BUILD')).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollHeight)).toBeLessThan(22 * 844);

  await page.getByRole('button', { name: 'Show weeks 3–13' }).click();
  await expect(page.getByText('Week 13 · BUILD')).toBeVisible();
  await page.getByRole('button', { name: /Change Sweet Spot.*Thu 5 Nov/ }).click();
  await expect(page.getByLabel('Effort (minutes)')).toHaveValue('25');
  await expect(page.getByLabel('Recovery (minutes)')).toHaveValue('3');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
