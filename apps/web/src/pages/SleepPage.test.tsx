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
    plannedWorkouts: [],
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

function renderWithSnapshot(loopSnapshot: DailyLoopEnvelope) {
  apiFetchMock.mockImplementation((path: string) =>
    Promise.resolve(path.startsWith('/api/v1/bedroom/overnight') ? overnightSnapshot : loopSnapshot),
  );
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
    expect(screen.queryByRole('tab', { name: 'Last night' })).toBeNull();
    expect(screen.queryByText("Last night's sleep")).toBeNull();
    expect(screen.queryByText("Tonight's sleep prep")).toBeNull();
    expect(screen.queryByRole('link', { name: /morning check-in/i })).toBeNull();
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
    expect(screen.getByText('Sleep stages vs your age')).toBeTruthy();
    expect(screen.getByText('Chronic sleep patterns to work on')).toBeTruthy();
    expect(screen.getByText('Protect REM consistency')).toBeTruthy();
    expect(screen.getByText(/Rotating focus/)).toBeTruthy();
    expect(screen.getByText('Duration')).toBeTruthy();
    expect(screen.getByText('REM')).toBeTruthy();
    expect(screen.getByText('Overnight room & fan')).toBeTruthy();
    expect((await screen.findByTestId('overnight-room-verdict-badge')).textContent).toBe('Red');
  });

  it('switches to the Tonight view with the sleep projection and a link to Climate', async () => {
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
    const link = screen.getByRole('link', { name: /open climate/i });
    expect(link.getAttribute('href')).toBe('/environment');
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

  it('offers a manual morning check-in link from the Sleep page once the sleep surface is unlocked (Batch 60)', async () => {
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

    const link = await screen.findByRole('link', { name: /morning check-in/i });
    expect(link.getAttribute('href')).toBe('/check-in');
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
