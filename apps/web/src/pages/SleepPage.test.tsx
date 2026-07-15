import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Navigate, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { DailyLoopEnvelope } from '@/hooks/useDailyLoop';
import { SleepPage } from './SleepPage';

const apiFetchMock = vi.fn();

vi.mock('@/lib/api', () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const snapshot: DailyLoopEnvelope = {
  data: {
    subjectDate: '2026-06-20',
    timezone: 'Europe/London',
    hostedTtsConsent: false,
    holiday: {
      isActive: false,
      activeWindow: null,
    },
    morningAnalysis: {
      id: '22222222-2222-4222-8222-222222222222',
      generatedAtUtc: '2026-06-20T06:35:00Z',
      verdict: 'green',
      promptVersion: 'morning-v1',
      modelName: 'claude-sonnet-4-6',
      outputMarkdown: '**Green light**',
      planAdjustments: [],
      reasons: ['Sleep and HRV are in range.'],
      readinessInterpretation: 'load_driven',
      todayActions: [],
      thermalReview: {},
      metricsVsBaselines: [
        {
          metricKey: 'hrv_7_day_avg_ms',
          label: 'HRV (7-day)',
          currentValue: 50,
          baselineMedian: 49,
          lowerQuartile: 43,
          upperQuartile: 57,
          sampleCount: 14,
          excludedSampleCount: 70,
          reliabilityStartDate: '2026-06-11',
        },
      ],
      ageComparison: {
        ageBand: '50–59',
        rows: [],
        sleepRows: [
          {
            metricKey: 'sleep_duration_hours',
            label: 'Duration',
            value: 7.2,
            unit: ' h',
            ageAverage: 7.1,
            bandLow: 6.5,
            bandHigh: 8,
            garminTargetLow: null,
            garminTargetHigh: null,
            ageBand: '50–59',
            betterDirection: 'higher',
            tone: 'good',
            descriptor: 'Healthy for your age',
          },
          {
            metricKey: 'rem_sleep_pct',
            label: 'REM',
            value: 18.2,
            unit: '%',
            ageAverage: 19,
            bandLow: 15,
            bandHigh: 23,
            garminTargetLow: 21,
            garminTargetHigh: 31,
            ageBand: '50–59',
            betterDirection: 'higher',
            tone: 'good',
            descriptor: 'Healthy for your age',
          },
        ],
      },
    },
    dailyMetrics: null,
    sleep: null,
    manualEntry: null,
    postWorkoutAnalyses: [],
    postFlexibilityAnalyses: [],
    postStrengthAnalyses: [],
    postWalkAnalyses: [],
    plannedWorkouts: [
      {
        id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
        userId: '11111111-1111-4111-8111-111111111111',
        workoutDate: '2026-06-20',
        version: 3,
        source: 'plan_import',
        isActive: true,
        title: 'Endurance spin',
        workoutType: 'bike_endurance',
        status: 'planned',
        plannedDurationMin: 75,
        intensityTarget: 'Z2',
        planBlockId: null,
        structuredWorkout: {},
      },
    ],
    thermalState: {
      latestTemperatureC: 17.4,
      targetTemperatureC: 17,
      capturedAtUtc: '2026-06-20T06:25:00Z',
      overnightLowC: 11.2,
      overnightWindMaxMph: 12,
      overnightWindGustMph: 18,
      thermalReview: {},
      fans: [
        {
          id: 'fan-bedroom',
          label: 'Bedroom fan',
          model: 'DR-HPF008S',
          autoEnabled: true,
          autoTarget: true,
          mode: 'control',
          isOn: true,
          speed: 5,
          oscillating: true,
          presetMode: 'normal',
          respondingToC: 20.1,
        },
      ],
    },
    sleepProjection: {
      status: 'personalized',
      tone: 'protect',
      headline: "Protect tonight's wind-down",
      summary: 'A late hard session plus a warm room may make sleep more fragile.',
      evidence: ['Latest session started 18:05.'],
      prepActions: ['Bring the wind-down forward.'],
      protocol: {
        preCoolTemperatureC: 17,
        coherenceBreathingTime: '20:00',
        latestSnackTime: '21:30',
        sealTargetTime: '22:00',
        bedtime: '23:15',
      },
    },
    breathworkBrief: {
      asOfDate: '2026-06-20',
      trend: 'stable',
      trendReason: 'You have kept the evening breathing habit steady across the last month.',
      window4w: {
        sessionCount: 18,
        totalDurationMin: 54,
        sessionsPerWeek: 4.5,
      },
      window12w: {
        sessionCount: 54,
        totalDurationMin: 162,
        sessionsPerWeek: 4.5,
      },
      recentSessions: [],
    },
    chronicSuggestions: {
      status: 'active',
      headline: 'Chronic sleep patterns to work on',
      summary: '1 repeated pattern stood out across 24 recent nights.',
      evidenceWindow: {
        startDate: '2026-06-05',
        endDate: '2026-07-02',
        weeks: 4,
        nightsObserved: 24,
        nightsRequired: 21,
      },
      items: [
        {
          id: 'chronic-rem_sleep_pct',
          metricKey: 'rem_sleep_pct',
          label: 'REM',
          title: 'Protect REM consistency',
          summary: 'REM has repeatedly missed its age norm; training load is the strongest measured lever to check first.',
          tone: 'watch',
          priority: 1,
          evidence: [
            '14 of 24 measured nights missed typical 50–59 value 21%.',
            'Higher load nights averaged 5 points lower sleep score.',
          ],
          actions: [
            'Treat high-load or late-training evenings as protect nights: shorten the admin tail and start wind-down earlier.',
            'Make 23:15 the latest normal lights-out target for the next week.',
          ],
          driver: {
            driver: 'prev_day_training_load',
            label: 'training load',
            coefficient: -0.61,
            sampleCount: 18,
            summary: 'Higher load nights averaged 5 points lower sleep score.',
          },
          rotation: { periodLabel: '2026-W28', shown: 2, total: 12 },
        },
      ],
    },
    dataQualityWarnings: [],
  },
  meta: {
    generatedAtUtc: '2026-06-20T06:40:00Z',
  },
  errors: [],
};

const overnightSnapshot = {
  data: {
    night: '2026-06-19',
    timezone: 'Europe/London',
    windowStartUtc: '2026-06-19T20:30:00Z',
    windowEndUtc: '2026-06-20T08:00:00Z',
    thresholds: { onC: 19.5, criticalC: 20.0 },
    temperature: [{ t: '2026-06-19T22:00:00Z', c: 20.4 }],
    fan: [],
    sleep: null,
    summary: {
      minTempC: 19,
      maxTempC: 21,
      fanRanMinutes: 210,
      peakSpeed: 5,
      warningMinutes: 210,
      criticalMinutes: 60,
      roomVerdict: 'red',
    },
    nights: ['2026-06-19'],
  },
  meta: { generatedAtUtc: '2026-06-20T08:05:00Z' },
  errors: [],
};

const historicalSnapshot: DailyLoopEnvelope = {
  ...snapshot,
  data: {
    ...snapshot.data,
    subjectDate: '2026-06-19',
    morningAnalysis: {
      ...snapshot.data.morningAnalysis!,
      id: '33333333-3333-4333-8333-333333333333',
      outputMarkdown: '**Steadier night**',
      metricsVsBaselines: [
        {
          metricKey: 'hrv_7_day_avg_ms',
          label: 'HRV (7-day)',
          currentValue: 47,
          baselineMedian: 49,
          lowerQuartile: 43,
          upperQuartile: 57,
          sampleCount: 14,
          excludedSampleCount: 70,
          reliabilityStartDate: '2026-06-10',
        },
      ],
      ageComparison: {
        ageBand: '50–59',
        rows: [],
        sleepRows: [
          {
            metricKey: 'sleep_duration_hours',
            label: 'Duration',
            value: 7.8,
            unit: ' h',
            ageAverage: 7.1,
            bandLow: 6.5,
            bandHigh: 8,
            garminTargetLow: null,
            garminTargetHigh: null,
            ageBand: '50–59',
            betterDirection: 'higher',
            tone: 'good',
            descriptor: 'Healthy for your age',
          },
        ],
      },
    },
    plannedWorkouts: [
      {
        id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
        userId: '11111111-1111-4111-8111-111111111111',
        workoutDate: '2026-06-19',
        version: 2,
        source: 'plan_import',
        isActive: true,
        title: 'Tempo ride',
        workoutType: 'bike_tempo',
        status: 'completed',
        plannedDurationMin: 60,
        intensityTarget: 'Z3',
        planBlockId: null,
        structuredWorkout: {},
      },
      {
        id: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
        userId: '11111111-1111-4111-8111-111111111111',
        workoutDate: '2026-06-19',
        version: 1,
        source: 'plan_action_add',
        isActive: true,
        title: 'Mobility reset',
        workoutType: 'mobility',
        status: 'planned',
        plannedDurationMin: 20,
        intensityTarget: null,
        planBlockId: null,
        structuredWorkout: {},
      },
    ],
    sleep: {
      id: '44444444-4444-4444-8444-444444444444',
      userId: '11111111-1111-4111-8111-111111111111',
      calendarDate: '2026-06-19',
      sleepStartUtc: '2026-06-18T22:35:00Z',
      sleepEndUtc: '2026-06-19T06:50:00Z',
      score: 81,
      ageAdjustedScore: 85,
      qualifier: 'good',
      durationSec: 29700,
      deepSleepSec: 4200,
      lightSleepSec: 16200,
      remSleepSec: 5400,
      awakeSleepSec: 900,
      unmeasurableSleepSec: 0,
      averageSpo2Pct: 96,
      lowestSpo2Pct: 93,
      averageRespiration: 14.2,
      restingHeartRateBpm: 52,
      avgOvernightHrvMs: 48,
      hrvStatus: 'balanced',
      avgSleepStress: 18,
      restlessMomentsCount: 8,
      bodyBatteryChange: 62,
      factorsJson: {},
      rawPayload: {},
    },
    chronicSuggestions: undefined,
  },
};

const historicalOvernightSnapshot = {
  ...overnightSnapshot,
  data: {
    ...overnightSnapshot.data,
    night: '2026-06-18',
    temperature: [{ t: '2026-06-18T22:00:00Z', c: 19.2 }],
    summary: {
      minTempC: 18,
      maxTempC: 19,
      fanRanMinutes: 60,
      peakSpeed: 3,
      warningMinutes: 0,
      criticalMinutes: 0,
      roomVerdict: 'green',
    },
    nights: ['2026-06-19', '2026-06-18'],
  },
};

function renderWithSnapshot(
  loopSnapshot: DailyLoopEnvelope,
  options?: {
    dailyLoopByPath?: Record<string, DailyLoopEnvelope>;
    overnightByPath?: Record<string, typeof overnightSnapshot>;
    verdictsByPath?: Record<string, { data: { from: string; to: string; verdicts: Record<string, string | null> }; meta: { generatedAtUtc: string }; errors: never[] }>;
  },
) {
  apiFetchMock.mockImplementation((path: string) => {
    if (path.startsWith('/api/v1/sleep/verdicts')) {
      return Promise.resolve(
        options?.verdictsByPath?.[path] ?? {
          data: {
            from: '2026-06-30',
            to: '2026-08-09',
            verdicts: {
              '2026-06-19': 'amber',
              '2026-06-20': 'green',
            },
          },
          meta: { generatedAtUtc: '2026-06-20T06:41:00Z' },
          errors: [],
        },
      );
    }
    if (path.startsWith('/api/v1/bedroom/overnight')) {
      return Promise.resolve(options?.overnightByPath?.[path] ?? overnightSnapshot);
    }
    return Promise.resolve(options?.dailyLoopByPath?.[path] ?? loopSnapshot);
  });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <SleepPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  apiFetchMock.mockClear();
});

describe('SleepPage', () => {
  it('gates the sleep surface to the check-in hero before a check-in or brief exists (Batch 103)', async () => {
    const gated = JSON.parse(JSON.stringify(snapshot)) as DailyLoopEnvelope;
    gated.data.morningAnalysis = null;
    renderWithSnapshot(gated);

    expect(await screen.findByRole('region', { name: 'Say good morning' })).toBeTruthy();
    expect(screen.getByText('Sleep calendar')).toBeTruthy();
    expect(screen.getByRole('button', { name: /show calendar/i })).toBeTruthy();
    expect(screen.queryByRole('tab', { name: 'Last night' })).toBeNull();
    expect(screen.queryByText("Last night's sleep")).toBeNull();
    expect(screen.queryByText("Tonight's sleep prep")).toBeNull();
    expect(screen.getByText("Today's sleep")).toBeTruthy();
    expect(screen.getAllByRole('link', { name: /morning check-in/i })).toHaveLength(2);
  });

  it('renders the Last night view with the metrics table and overnight chart', async () => {
    const checkedIn = JSON.parse(JSON.stringify(snapshot)) as DailyLoopEnvelope;
    checkedIn.data.manualEntry = {
      id: '12121212-1212-4121-8121-121212121212',
      userId: '11111111-1111-4111-8111-111111111111',
      entryDate: '2026-06-20',
      entryAtUtc: '2026-06-20T07:00:00Z',
      actualWorkoutJson: {},
      supplementsJson: {},
      foodJson: {},
    };
    renderWithSnapshot(checkedIn);

    expect(await screen.findByText("Last night's sleep")).toBeTruthy();
    expect(screen.getByText('Status')).toBeTruthy();
    expect(screen.getByText('in range')).toBeTruthy();
    expect(screen.getByText('Sleep stages vs your age')).toBeTruthy();
    expect(screen.getByText('Chronic sleep patterns to work on')).toBeTruthy();
    expect(screen.getByText('Protect REM consistency')).toBeTruthy();
    expect(screen.getByText(/Rotating focus/)).toBeTruthy();
    expect(screen.getByText('Duration')).toBeTruthy();
    expect(screen.getByText('REM')).toBeTruthy();
    expect(screen.getByText('Overnight room & fan')).toBeTruthy();
    expect((await screen.findByTestId('overnight-room-verdict-badge')).textContent).toBe('Red');
  });

  it('switches to the Tonight view with breathwork context and a link to Climate', async () => {
    const user = userEvent.setup();
    const checkedIn = JSON.parse(JSON.stringify(snapshot)) as DailyLoopEnvelope;
    checkedIn.data.manualEntry = {
      id: '12121212-1212-4121-8121-121212121212',
      userId: '11111111-1111-4111-8111-111111111111',
      entryDate: '2026-06-20',
      entryAtUtc: '2026-06-20T07:00:00Z',
      actualWorkoutJson: {},
      supplementsJson: {},
      foodJson: {},
    };
    renderWithSnapshot(checkedIn);

    await screen.findByText("Last night's sleep");
    await user.click(screen.getByRole('tab', { name: 'Tonight' }));

    expect(await screen.findByText("Protect tonight's wind-down")).toBeTruthy();
    expect(screen.getByText(/late hard session/)).toBeTruthy();
    expect(screen.getByText("Right now this is based on today's training.")).toBeTruthy();
    expect(screen.getByText('Breathwork rhythm')).toBeTruthy();
    expect(screen.getByText(/18 sessions · 54 min in 4 weeks/i)).toBeTruthy();
    expect(screen.getByText(/Indoor 17\.4°C · fan on auto/)).toBeTruthy();
    expect(screen.queryByText('Indoor now')).toBeNull();
    expect(screen.queryByText('Thermostat')).toBeNull();
    expect(screen.queryByText('Overnight low')).toBeNull();
    expect(screen.queryByText(/^Wind$/)).toBeNull();
    const link = screen.getByRole('link', { name: /open climate/i });
    expect(link.getAttribute('href')).toBe('/environment');
  });

  it('lets Mark browse an earlier night from the sleep calendar and loads that date history', async () => {
    const user = userEvent.setup();
    const checkedIn = JSON.parse(JSON.stringify(snapshot)) as DailyLoopEnvelope;
    checkedIn.data.manualEntry = {
      id: '12121212-1212-4121-8121-121212121212',
      userId: '11111111-1111-4111-8111-111111111111',
      entryDate: '2026-06-20',
      entryAtUtc: '2026-06-20T07:00:00Z',
      actualWorkoutJson: {},
      supplementsJson: {},
      foodJson: {},
    };

    renderWithSnapshot(checkedIn, {
      dailyLoopByPath: {
        '/api/v1/daily-loop?subject_date=2026-06-19': historicalSnapshot,
      },
      overnightByPath: {
        '/api/v1/bedroom/overnight?date=2026-06-18': historicalOvernightSnapshot,
      },
    });

    await screen.findByText("Last night's sleep");
    await user.click(screen.getByRole('button', { name: /show calendar/i }));
    await user.click(screen.getByRole('button', { name: 'Friday 19 June 2026 - Amber verdict' }));

    expect(
      await screen.findByRole('heading', {
        name: /Sleep for Friday.*19/,
      }),
    ).toBeTruthy();
    expect(screen.getByText('Selected: Fri 19 Jun')).toBeTruthy();
    expect(await screen.findByText('The whole day')).toBeTruthy();
    expect(screen.getByText('Tempo ride')).toBeTruthy();
    expect(screen.getByText('Mobility reset')).toBeTruthy();
    expect(screen.getByText('Good to go')).toBeTruthy();
    expect((await screen.findByTestId('overnight-room-verdict-badge')).textContent).toBe('Green');
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/daily-loop?subject_date=2026-06-19');
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/bedroom/overnight?date=2026-06-18');
  });

  it('lets Mark browse past dates before today is unlocked while keeping today gated', async () => {
    const user = userEvent.setup();
    const gated = JSON.parse(JSON.stringify(snapshot)) as DailyLoopEnvelope;
    gated.data.morningAnalysis = null;

    renderWithSnapshot(gated, {
      dailyLoopByPath: {
        '/api/v1/daily-loop?subject_date=2026-06-19': historicalSnapshot,
      },
      overnightByPath: {
        '/api/v1/bedroom/overnight?date=2026-06-18': historicalOvernightSnapshot,
      },
    });

    expect(await screen.findByRole('region', { name: 'Say good morning' })).toBeTruthy();
    expect(screen.getByText("Today's sleep")).toBeTruthy();

    await user.click(screen.getByRole('button', { name: /show calendar/i }));
    expect(screen.getByText('June 2026')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: 'Friday 19 June 2026 - Amber verdict' }));

    expect(await screen.findByRole('heading', { name: /Sleep for Friday.*19/ })).toBeTruthy();
    expect(screen.getByText('The whole day')).toBeTruthy();
    expect(screen.queryByText("Today's sleep")).toBeNull();
  });

  it('/bedroom redirects into /environment', async () => {
    apiFetchMock.mockImplementation((path: string) =>
      Promise.resolve(path.startsWith('/api/v1/bedroom/overnight') ? overnightSnapshot : snapshot),
    );
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/bedroom']}>
          <Routes>
            <Route path="/environment" element={<div>Climate page</div>} />
            <Route path="/bedroom" element={<Navigate to="/environment" replace />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText('Climate page')).toBeTruthy();
  });

  it('shows a holiday-away placeholder on Tonight instead of sleep prep and climate', async () => {
    const holidaySnapshot = JSON.parse(JSON.stringify(snapshot)) as DailyLoopEnvelope;
    holidaySnapshot.data.holiday = {
      isActive: true,
      activeWindow: { startDate: '2026-07-12', endDate: '2026-07-16' },
    };
    renderWithSnapshot(holidaySnapshot);

    await userEvent.click(await screen.findByRole('tab', { name: /tonight/i }));

    expect(await screen.findByText('Holiday away')).toBeTruthy();
    expect(
      screen.getAllByText((_, node) => node?.textContent?.includes('Thursday, July 16') ?? false).length,
    ).toBeGreaterThan(0);
    expect(screen.getByRole('link', { name: /open holiday/i })).toBeTruthy();
    expect(screen.queryByText("Protect tonight's wind-down")).toBeNull();
    expect(screen.queryByText('Bedroom climate')).toBeNull();
  });

  it('shows a dormant placeholder on Last night instead of the fan chart while on holiday (Batch 113)', async () => {
    const holidaySnapshot = JSON.parse(JSON.stringify(snapshot)) as DailyLoopEnvelope;
    holidaySnapshot.data.holiday = {
      isActive: true,
      activeWindow: { startDate: '2026-07-12', endDate: '2026-07-16' },
    };
    holidaySnapshot.data.manualEntry = {
      id: '12121212-1212-4121-8121-121212121212',
      userId: '11111111-1111-4111-8111-111111111111',
      entryDate: '2026-06-20',
      entryAtUtc: '2026-06-20T07:00:00Z',
      actualWorkoutJson: {},
      supplementsJson: {},
      foodJson: {},
    };
    renderWithSnapshot(holidaySnapshot);

    expect(await screen.findByText('Holiday away')).toBeTruthy();
    expect(screen.getByText("The overnight room/fan chart stays dormant while you are away.")).toBeTruthy();
    expect(screen.queryByText('Overnight room & fan')).toBeNull();
  });

  it('offers a manual morning check-in link from the Sleep page when the surface unlocked without one (Batch 60)', async () => {
    // The sleep surface can unlock via the 09:30 backstop's auto-generated brief
    // without Mark having checked in himself — `manualEntry` is still null, so
    // the optional check-in link stays offered.
    renderWithSnapshot(snapshot);

    const link = await screen.findByRole('link', { name: /morning check-in/i });
    expect(link.getAttribute('href')).toBe('/check-in');
  });

  it('drops the "Add today\'s check-in" card once he has actually checked in (Batch 114)', async () => {
    const checkedIn = JSON.parse(JSON.stringify(snapshot)) as DailyLoopEnvelope;
    checkedIn.data.manualEntry = {
      id: '12121212-1212-4121-8121-121212121212',
      userId: '11111111-1111-4111-8111-111111111111',
      entryDate: '2026-06-20',
      entryAtUtc: '2026-06-20T07:00:00Z',
      actualWorkoutJson: {},
      supplementsJson: {},
      foodJson: {},
    };
    renderWithSnapshot(checkedIn);

    await screen.findByText("Last night's sleep");
    expect(screen.queryByRole('link', { name: /morning check-in/i })).toBeNull();
  });

  it('leads with the "say good morning" CTA when neither a check-in nor brief exists yet (Batch 95/103)', async () => {
    const gated = JSON.parse(JSON.stringify(snapshot)) as DailyLoopEnvelope;
    gated.data.morningAnalysis = null;
    renderWithSnapshot(gated);

    expect(await screen.findByRole('region', { name: 'Say good morning' })).toBeTruthy();
    const cta = screen.getByRole('link', { name: /get today's brief/i });
    expect(cta.getAttribute('href')).toBe('/check-in');
  });

  it('does not show the "say good morning" CTA once a check-in exists', async () => {
    const checkedIn = JSON.parse(JSON.stringify(snapshot)) as DailyLoopEnvelope;
    checkedIn.data.manualEntry = {
      id: '12121212-1212-4121-8121-121212121212',
      userId: '11111111-1111-4111-8111-111111111111',
      entryDate: '2026-06-20',
      entryAtUtc: '2026-06-20T07:00:00Z',
      actualWorkoutJson: {},
      supplementsJson: {},
      foodJson: {},
    };
    apiFetchMock.mockImplementation((path: string) =>
      Promise.resolve(path.startsWith('/api/v1/bedroom/overnight') ? overnightSnapshot : checkedIn),
    );
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <SleepPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await screen.findByText("Last night's sleep");
    expect(screen.queryByText('Say good morning')).toBeNull();
  });

  it('renders the shared error state when the daily loop fails to load', async () => {
    apiFetchMock.mockImplementation((path: string) =>
      path === '/api/v1/daily-loop'
        ? Promise.reject(new Error('Network down'))
        : Promise.reject(new Error(`Unexpected request: ${path}`)),
    );
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <SleepPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Sleep data couldn't load")).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeTruthy();
  });
});
