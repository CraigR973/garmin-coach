import { expect, test, type Page } from '@playwright/test';

const userId = '11111111-1111-4111-8111-111111111111';
const analysisId = '22222222-2222-4222-8222-222222222222';
const dailyMetricId = '33333333-3333-4333-8333-333333333333';
const sleepId = '44444444-4444-4444-8444-444444444444';
const workoutId = '55555555-5555-4555-8555-555555555555';
const manualEntryId = '66666666-6666-4666-8666-666666666666';

const meta = { generatedAtUtc: '2026-08-15T07:10:00Z' };

const dailyLoopEnvelope = {
  data: {
    subjectDate: '2026-08-15',
    timezone: 'Europe/London',
    loopState: {
      dayPhase: 'pre_training',
      blockPhase: 'build',
      nextAction: 'await_training',
      atBlockBoundary: false,
    },
    holiday: { isActive: false, awayTonight: false, activeWindow: null },
    hostedTtsConsent: false,
    morningAnalysis: {
      id: analysisId,
      generatedAtUtc: '2026-08-15T06:40:00Z',
      verdict: 'green',
      promptVersion: 'morning-v29',
      modelName: 'claude-sonnet-4-6',
      outputMarkdown: '**Green light.** Train as planned today.',
      planAdjustments: ['Keep the scheduled ride.'],
      reasons: ['Sleep and HRV are in range.'],
      readinessInterpretation: 'load_driven',
      thermalReview: {},
      metricsVsBaselines: [
        {
          metricKey: 'sleep_score',
          label: 'Sleep score',
          currentValue: 60,
          baselineMedian: 76,
          lowerQuartile: 70,
          upperQuartile: 82,
          sampleCount: 28,
        },
        {
          metricKey: 'resting_heart_rate_bpm',
          label: 'Resting HR',
          currentValue: 48,
          baselineMedian: 49,
          lowerQuartile: 46,
          upperQuartile: 53,
          sampleCount: 28,
        },
        {
          metricKey: 'body_battery_charge',
          label: 'Body Battery charge',
          currentValue: 69,
          baselineMedian: 68,
          lowerQuartile: 59.5,
          upperQuartile: 72,
          sampleCount: 83,
          basis: "Garmin's overnight charge accumulated from midnight to this morning's sync.",
        },
        {
          metricKey: 'body_battery_drain',
          label: 'Body Battery drain',
          currentValue: null,
          baselineMedian: 67,
          lowerQuartile: 57.5,
          upperQuartile: 75,
          sampleCount: 83,
          unavailableReason:
            'This drain is still a part-day value at the morning sync; compare it with your full-day baseline after the day closes.',
        },
      ],
      ageComparison: {
        age: 57,
        ageBand: '50-59',
        fitnessAge: 48,
        fitnessAgeDelta: 9,
        fitnessAgeTone: 'good',
        rows: [
          {
            metricKey: 'resting_heart_rate_bpm',
            label: 'Resting HR',
            value: 48,
            unit: 'bpm',
            ageAverage: 71,
            ageBand: '50-59',
            betterDirection: 'lower',
            tone: 'good',
            descriptor: 'Better than average',
            bandLow: null,
            bandHigh: null,
            garminTargetLow: null,
            garminTargetHigh: null,
          },
          {
            metricKey: 'vo2max',
            label: 'VO2max',
            value: 54,
            unit: '',
            ageAverage: 31,
            ageBand: '50-59',
            betterDirection: 'higher',
            tone: 'good',
            descriptor: 'Much better than average',
            bandLow: null,
            bandHigh: null,
            garminTargetLow: null,
            garminTargetHigh: null,
          },
        ],
        sleepRows: [
          {
            metricKey: 'rem_sleep_min',
            label: 'REM',
            value: 54,
            unit: 'm',
            ageAverage: null,
            ageBand: '50-59',
            betterDirection: 'higher',
            tone: 'warn',
            descriptor: 'Below the healthy range for your age',
            bandLow: 65,
            bandHigh: 90,
            garminTargetLow: 80,
            garminTargetHigh: 120,
          },
          {
            metricKey: 'deep_sleep_min',
            label: 'Deep',
            value: 80,
            unit: 'm',
            ageAverage: null,
            ageBand: '50-59',
            betterDirection: 'higher',
            tone: 'good',
            descriptor: 'In the healthy range for your age',
            bandLow: 45,
            bandHigh: 85,
            garminTargetLow: 60,
            garminTargetHigh: 110,
          },
        ],
      },
      weeklyMix: {
        weekStart: '2026-08-10',
        subjectDate: '2026-08-15',
        buckets: [
          { bucket: 'vo2', label: 'VO2', target: 1, done: 1, due: 1, remainingPlanned: 0, atRisk: false },
          {
            bucket: 'sweet_spot',
            label: 'Sweet Spot',
            target: 1,
            done: 0,
            due: 1,
            remainingPlanned: 1,
            atRisk: true,
          },
        ],
        shortfall: null,
      },
      todayActions: [],
      feedback: null,
    },
    briefGeneration: { status: 'ready', reason: null },
    dailyMetrics: {
      id: dailyMetricId,
      userId,
      calendarDate: '2026-08-15',
      recordedAtUtc: '2026-08-15T06:25:00Z',
      readinessScore: 72,
      readinessLevel: 'Ready',
      readinessSleepScore: 78,
      recoveryTimeMin: 180,
      acuteLoad: 640,
      trainingStatus: 'productive',
      hrvLastNightAvgMs: 50,
      hrvWeeklyAvgMs: 48,
      hrvStatus: 'balanced',
      restingHeartRateBpm: 45,
      bodyBatteryCharged: 63,
      bodyBatteryDrained: 19,
      bodyBatteryEnd: 79,
      vo2max: 54,
      rawPayload: {},
    },
    sleep: {
      id: sleepId,
      userId,
      calendarDate: '2026-08-15',
      sleepStartUtc: '2026-08-14T22:15:00Z',
      sleepEndUtc: '2026-08-15T06:15:00Z',
      score: 70,
      ageAdjustedScore: 74,
      qualifier: 'Good',
      durationSec: 28800,
      deepSleepSec: 4800,
      lightSleepSec: 13200,
      remSleepSec: 3240,
      awakeSleepSec: 1800,
      averageSpo2Pct: 96.4,
      averageRespiration: 13.4,
      restingHeartRateBpm: 45,
      avgOvernightHrvMs: 50,
      hrvStatus: 'balanced',
      factorsJson: {},
      rawPayload: {},
    },
    manualEntry: {
      id: manualEntryId,
      userId,
      entryDate: '2026-08-15',
      entryAtUtc: '2026-08-15T06:32:00Z',
      subjectiveScore: 8,
      feel: 'slept well',
      actualWorkoutJson: {},
      supplementsJson: {},
      foodJson: {},
      notes: null,
    },
    postWorkoutAnalyses: [],
    postFlexibilityAnalyses: [],
    postStrengthAnalyses: [],
    postWalkAnalyses: [],
    plannedWorkouts: [
      {
        id: workoutId,
        userId,
        planBlockId: null,
        workoutDate: '2026-08-15',
        version: 1,
        title: 'Sweet Spot Light',
        workoutType: 'bike_sweet_spot',
        status: 'planned',
        isActive: true,
        plannedDurationMin: 48,
        intensityTarget: '100% FTP intervals',
        structuredWorkout: {},
        source: 'test',
        adherence: null,
        delivery: {
          liveStatus: 'pushed',
          liveOrigin: 'baseline',
          intervalsEventId: 'evt_test',
          changed: false,
          adjustment: null,
        },
      },
    ],
    thermalState: {
      latestTemperatureC: 20.2,
      targetTemperatureC: 18,
      capturedAtUtc: '2026-08-15T06:00:00Z',
      thermalReview: {},
      fans: [
        {
          id: 'fan-bedroom',
          label: 'Bedroom fan',
          autoEnabled: true,
          autoTarget: true,
          mode: 'idle',
          isOn: false,
          speed: null,
          respondingToC: null,
        },
      ],
    },
    sleepProjection: {
      status: 'personalized',
      tone: 'protect',
      headline: 'Protect tonight',
      summary: 'Protect tonight after a hard session.',
      evidence: ['Harder session today'],
      prepActions: ['Start wind-down early'],
      protocol: {},
    },
    remInterventionCheckIn: {
      assignmentId: '77777777-7777-4777-8777-777777777777',
      periodLabel: '2026-W33',
      windowStart: '2026-08-10',
      windowEnd: '2026-08-16',
      wakeDate: '2026-08-15',
      interventions: [
        {
          id: 'consistent_wake',
          action: 'Keep the normal wake time.',
          status: 'unknown',
        },
        {
          id: 'wind_down',
          action: 'Start the wind-down 30 minutes earlier.',
          status: 'applied',
        },
      ],
    },
    dataQualityWarnings: [],
    walkingBrief: {
      asOfDate: '2026-08-15',
      window4w: { sessionCount: 0, totalDistanceM: 0, totalDurationMin: 0, sessionsPerWeek: 0 },
      window12w: { sessionCount: 0, totalDistanceM: 0, totalDurationMin: 0, sessionsPerWeek: 0 },
      recentSessions: [],
      trend: 'insufficient_data',
      trendReason: 'Only 0 walk(s) in the last 28 days.',
    },
  },
  meta,
  errors: [],
};

const bedroomEnvelope = {
  data: {
    night: '2026-08-14',
    timezone: 'Europe/London',
    windowStartUtc: '2026-08-14T20:30:00Z',
    windowEndUtc: '2026-08-15T08:00:00Z',
    thresholds: { onC: 19.5, criticalC: 20 },
    temperature: [],
    fan: [],
    sleep: null,
    summary: null,
    nights: ['2026-08-14'],
  },
  meta,
  errors: [],
};

async function seedApp(page: Page, dailyLoop: unknown = dailyLoopEnvelope) {
  await page.addInitScript(() => {
    localStorage.setItem('coach_device_token', 'test-device-token');
    localStorage.setItem(
      'coach_player',
      JSON.stringify({
        id: '11111111-1111-4111-8111-111111111111',
        displayName: 'Mark',
        role: 'player',
        timezone: 'Europe/London',
      }),
    );
  });

  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/v1/daily-loop') {
      await route.fulfill({ json: dailyLoop });
      return;
    }
    if (url.pathname === '/api/v1/coach/messages' || /\/api\/v1\/briefs\/.+\/messages/.test(url.pathname)) {
      await route.fulfill({ json: { data: { messages: [] }, meta, errors: [] } });
      return;
    }
    if (url.pathname === '/api/v1/sleep/verdicts') {
      await route.fulfill({
        json: {
          data: { from: url.searchParams.get('from') ?? '2026-08-01', to: url.searchParams.get('to') ?? '2026-08-31', verdicts: { '2026-08-15': 'green' } },
          meta,
          errors: [],
        },
      });
      return;
    }
    if (url.pathname === '/api/v1/bedroom/overnight') {
      await route.fulfill({ json: bedroomEnvelope });
      return;
    }
    await route.fulfill({ status: 404, json: { detail: `Unhandled ${url.pathname}` } });
  });
}

async function visitThemed(page: Page, route: string, theme: 'light' | 'dark') {
  await page.goto(route);
  await page.evaluate((value) => {
    localStorage.setItem('sss_theme', value);
  }, theme);
  await page.reload();
  await expect(page.getByRole('link', { name: 'Home' }).first()).toBeVisible();
  await expect(page.locator('html')).toHaveClass(new RegExp(`\\b${theme}\\b`));
}

test.beforeEach(async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await seedApp(page);
});

test('representative pages keep rendered text contrast at AA in both themes', async ({ page }) => {
  const failures: string[] = [];
  for (const theme of ['light', 'dark'] as const) {
    for (const route of ['/', '/brief', '/sleep']) {
      await visitThemed(page, route, theme);
      const routeFailures = await page.evaluate(contrastFailures);
      failures.push(...routeFailures.map((failure) => `${theme} ${route}: ${failure}`));
    }
  }

  expect(failures).toEqual([]);
});

test('primary daily-path controls meet the rendered 44px hit-area floor', async ({ page }) => {
  const failures: string[] = [];
  for (const route of ['/check-in', '/brief', '/settings']) {
    await page.goto(route);
    await expect(page.getByRole('link', { name: 'Home' }).first()).toBeVisible();
    const routeFailures = await page.evaluate(hitAreaFailures);
    failures.push(...routeFailures.map((failure) => `${route}: ${failure}`));
  }

  expect(failures).toEqual([]);
});

test('check-in renders only the issued REM actions with explicit application states', async ({
  page,
}) => {
  await page.goto('/check-in');

  await expect(page.getByText("Last night's REM focus")).toBeVisible();
  await expect(page.getByText('Keep the normal wake time.')).toBeVisible();
  await expect(page.getByText('Start the wind-down 30 minutes earlier.')).toBeVisible();
  await expect(page.getByText(/watch already supplies REM and awake time/i)).toBeVisible();
  await expect(page.getByText(/Unknown stays unknown/i)).toBeVisible();
  await expect(
    page.getByLabel('consistent_wake response').getByRole('button', { name: 'Not sure' }),
  ).toHaveAttribute('aria-pressed', 'true');
  await expect(
    page.getByLabel('wind_down response').getByRole('button', { name: 'Tried it' }),
  ).toHaveAttribute('aria-pressed', 'true');
});

test('unsynced Home and Sleep promise a sync instead of claiming the data is already in', async ({
  page,
}) => {
  const unsyncedEnvelope = {
    ...dailyLoopEnvelope,
    data: {
      ...dailyLoopEnvelope.data,
      morningAnalysis: null,
      briefGeneration: null,
      dailyMetrics: null,
      sleep: null,
      manualEntry: null,
    },
  };
  await page.unroute('**/api/v1/**');
  await seedApp(page, unsyncedEnvelope);

  for (const route of ['/', '/sleep']) {
    await page.goto(route);
    await expect(page.getByRole('region', { name: 'Say good morning' })).toBeVisible();
    await expect(
      page.getByText(/sync your overnight data before I read your day/i),
    ).toBeVisible();
    await expect(page.getByText(/your overnight data's already in/i)).toHaveCount(0);
  }
});

test('live morning Body Battery is honest at mobile and desktop widths', async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });

  for (const viewport of [
    { width: 390, height: 844 },
    { width: 1280, height: 900 },
  ]) {
    await page.setViewportSize(viewport);
    await page.goto('/sleep');

    const charge = page.getByRole('row').filter({ hasText: 'Body Battery charge' });
    await expect(charge).toContainText('69');
    await expect(charge).toContainText('overnight charge accumulated from midnight');

    const drain = page.getByRole('row').filter({ hasText: 'Body Battery drain' });
    await expect(drain).toContainText('—');
    await expect(drain).toContainText('still a part-day value');
    await expect(drain).not.toContainText('57.5–75');

    await expect(page.locator('.vite-error-overlay')).toHaveCount(0);
    await expect(page.locator('body')).not.toHaveText('');
  }

  expect(consoleErrors).toEqual([]);
});

function contrastFailures() {
  type Rgba = { r: number; g: number; b: number; a: number };

  function parseColor(value: string): Rgba | null {
    const match = value.match(/rgba?\(([^)]+)\)/);
    if (!match) return null;
    const parts = match[1].split(',').map((part) => part.trim());
    return {
      r: Number(parts[0]),
      g: Number(parts[1]),
      b: Number(parts[2]),
      a: parts[3] == null ? 1 : Number(parts[3]),
    };
  }

  function channel(value: number): number {
    const normal = value / 255;
    return normal <= 0.03928 ? normal / 12.92 : ((normal + 0.055) / 1.055) ** 2.4;
  }

  function luminance(color: Rgba): number {
    return 0.2126 * channel(color.r) + 0.7152 * channel(color.g) + 0.0722 * channel(color.b);
  }

  function contrast(foreground: Rgba, background: Rgba): number {
    const light = Math.max(luminance(foreground), luminance(background));
    const dark = Math.min(luminance(foreground), luminance(background));
    return (light + 0.05) / (dark + 0.05);
  }

  function blend(top: Rgba, bottom: Rgba): Rgba {
    const alpha = top.a + bottom.a * (1 - top.a);
    if (alpha === 0) return { r: 255, g: 255, b: 255, a: 1 };
    return {
      r: Math.round((top.r * top.a + bottom.r * bottom.a * (1 - top.a)) / alpha),
      g: Math.round((top.g * top.a + bottom.g * bottom.a * (1 - top.a)) / alpha),
      b: Math.round((top.b * top.a + bottom.b * bottom.a * (1 - top.a)) / alpha),
      a: alpha,
    };
  }

  function effectiveBackground(element: Element): Rgba {
    let background = parseColor(getComputedStyle(document.body).backgroundColor) ?? { r: 255, g: 255, b: 255, a: 1 };
    const chain: Element[] = [];
    let current: Element | null = element;
    while (current) {
      chain.unshift(current);
      current = current.parentElement;
    }
    for (const item of chain) {
      const bg = parseColor(getComputedStyle(item).backgroundColor);
      if (bg && bg.a > 0) background = blend(bg, background);
    }
    return background;
  }

  function visibleTextNodes(): Text[] {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        if (!node.textContent?.trim()) return NodeFilter.FILTER_REJECT;
        const parent = node.parentElement;
        if (!parent || parent.closest('[aria-hidden="true"], script, style')) return NodeFilter.FILTER_REJECT;
        const style = getComputedStyle(parent);
        if (style.visibility === 'hidden' || style.display === 'none' || Number(style.opacity) === 0) {
          return NodeFilter.FILTER_REJECT;
        }
        const range = document.createRange();
        range.selectNodeContents(node);
        const visible = Array.from(range.getClientRects()).some((rect) => rect.width > 0 && rect.height > 0);
        range.detach();
        return visible ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
      },
    });
    const nodes: Text[] = [];
    let node = walker.nextNode();
    while (node) {
      nodes.push(node as Text);
      node = walker.nextNode();
    }
    return nodes;
  }

  return visibleTextNodes()
    .map((node) => {
      const parent = node.parentElement;
      if (!parent) return null;
      const foreground = parseColor(getComputedStyle(parent).color);
      if (!foreground || foreground.a === 0) return null;
      const background = effectiveBackground(parent);
      const ratio = contrast(foreground, background);
      if (ratio >= 4.5) return null;
      const text = node.textContent?.trim().replace(/\s+/g, ' ').slice(0, 60);
      return `${ratio.toFixed(2)} ${text}`;
    })
    .filter((failure): failure is string => Boolean(failure));
}

function hitAreaFailures() {
  const selectors = [
    'input[type="range"]',
    'input:not([type="hidden"])',
    'textarea',
    'select',
    'button[role="switch"]',
    'a[href]',
    'button',
  ];
  const controls = Array.from(document.querySelectorAll<HTMLElement>(selectors.join(','))).filter((element) => {
    if (element.matches('[disabled], [aria-hidden="true"]')) return false;
    if (element.closest('[aria-hidden="true"]')) return false;
    const style = getComputedStyle(element);
    if (style.visibility === 'hidden' || style.display === 'none') return false;
    const rect = element.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  });

  return controls
    .map((element) => {
      const rect = element.getBoundingClientRect();
      if (rect.width >= 44 && rect.height >= 44) return null;
      const label =
        element.getAttribute('aria-label') ||
        element.textContent?.trim().replace(/\s+/g, ' ').slice(0, 60) ||
        element.getAttribute('href') ||
        element.tagName.toLowerCase();
      return `${label} ${Math.round(rect.width)}x${Math.round(rect.height)}`;
    })
    .filter((failure): failure is string => Boolean(failure));
}
