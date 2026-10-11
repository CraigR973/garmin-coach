import { expect, test } from '@playwright/test';

const comparison = {
  test: { asProposed: '2026-10-20: FTP Ramp Test', yourPlan: null },
  vo2Sessions: Array.from({ length: 12 }, (_, index) => ({
    week: index + 2,
    asProposed: '2026-10-27: VO₂ 30/30 · 20 min above 106% FTP',
    yourPlan: '2026-10-26: VO₂ 30/30 · 18 min above 106% FTP',
  })),
  recoveryWeeks: [3, 6, 9].map((week) => ({ week, asProposed: 324, yourPlan: 364 })),
};

const envelope = {
  data: {
    draft: {
      status: 'draft',
      framework: '13-week 2121',
      planName: 'Plan No. 3',
      planNumber: 3,
      whyThisPlan: ['This proposal uses 30/30s then 30/15s for VO₂.'],
      startDate: '2026-10-19',
      endDate: '2027-01-17',
      ftpWatts: 280,
      athleteName: 'Mark',
      generatedAtUtc: '2026-10-11T12:00:00Z',
      lockedAtUtc: null,
      weeks: [],
    },
    canGenerate: false,
    planComparison: comparison,
  },
  meta: { generatedAtUtc: '2026-10-11T12:00:00Z' },
  errors: [],
};

test('accept comparison fits phone and desktop', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('coach_device_token', 'test-device-token');
    localStorage.setItem('coach_player', JSON.stringify({
      id: '11111111-1111-4111-8111-111111111111',
      displayName: 'Mark',
      role: 'player',
      timezone: 'Europe/London',
    }));
  });
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/v1/block-generator') {
      await route.fulfill({ json: envelope });
    } else {
      await route.fulfill({ status: 404, json: { detail: `Unhandled ${path}` } });
    }
  });

  for (const [width, height] of [[390, 844], [1280, 800]] as const) {
    await page.setViewportSize({ width, height });
    await page.goto('/builder');
    await page.getByRole('button', { name: 'Accept this plan' }).click();
    const dialog = page.getByRole('dialog', { name: 'As proposed → your plan' });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByText('Recovery weeks · total minutes')).toBeVisible();
    await expect.poll(async () => {
      const box = await dialog.boundingBox();
      return box ? box.x >= 0 && box.x + box.width <= width : false;
    }).toBe(true);
    expect(await dialog.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
    await dialog.evaluate((element) => { element.scrollTop = element.scrollHeight; });
    await expect(dialog.getByRole('button', { name: 'Accept your plan' })).toBeVisible();
  }
});
