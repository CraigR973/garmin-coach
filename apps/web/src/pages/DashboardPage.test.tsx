import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import type { DailyLoopEnvelope } from '@/hooks/useDailyLoop';
import { DashboardPage } from './DashboardPage';

const apiFetchMock = vi.fn();
let onlineStatus = true;

vi.mock('@/lib/api', () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}));

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    player: {
      id: '11111111-1111-4111-8111-111111111111',
      displayName: 'Mark',
      role: 'player',
      timezone: 'Europe/London',
    },
  }),
}));

vi.mock('@/hooks/useOnlineStatus', () => ({
  useOnlineStatus: () => onlineStatus,
}));

const baseSnapshot: DailyLoopEnvelope = {
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
      planAdjustments: ['Keep the scheduled ride.'],
      reasons: ['Sleep and HRV are in range.'],
      readinessInterpretation: 'load_driven',
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
        age: 57,
        ageBand: '50–59',
        fitnessAge: 48,
        fitnessAgeDelta: 9,
        fitnessAgeTone: 'good',
        rows: [
          {
            metricKey: 'vo2max',
            label: 'VO₂max',
            value: 54,
            unit: '',
            ageAverage: 31,
            ageBand: '50–59',
            betterDirection: 'higher',
            tone: 'good',
            descriptor: 'Much better than average',
          },
        ],
      },
    },
    dailyMetrics: {
      id: '33333333-3333-4333-8333-333333333333',
      userId: '11111111-1111-4111-8111-111111111111',
      calendarDate: '2026-06-20',
      recordedAtUtc: '2026-06-20T06:20:00Z',
      readinessScore: 72,
      readinessLevel: 'Ready',
      readinessSleepScore: 78,
      recoveryTimeMin: 180,
      acuteLoad: 640,
      trainingStatus: 'productive',
      hrvLastNightAvgMs: 50,
      hrvWeeklyAvgMs: 48,
      hrvStatus: 'balanced',
      hrvBaselineLowMs: 43,
      hrvBaselineHighMs: 57,
      restingHeartRateBpm: 45,
      stressAvg: 21,
      bodyBatteryCharged: 63,
      bodyBatteryDrained: 19,
      bodyBatteryEnd: 79,
      weightKg: 78.4,
      vo2max: 54,
      rawPayload: {},
    },
    sleep: {
      id: '44444444-4444-4444-8444-444444444444',
      userId: '11111111-1111-4111-8111-111111111111',
      calendarDate: '2026-06-20',
      sleepStartUtc: '2026-06-19T22:15:00Z',
      sleepEndUtc: '2026-06-20T06:15:00Z',
      score: 70,
      ageAdjustedScore: 74,
      qualifier: 'Good',
      durationSec: 28800,
      deepSleepSec: 5400,
      lightSleepSec: 13200,
      remSleepSec: 5400,
      awakeSleepSec: 1800,
      unmeasurableSleepSec: 0,
      averageSpo2Pct: 96.4,
      lowestSpo2Pct: 93.8,
      averageRespiration: 13.4,
      restingHeartRateBpm: 45,
      avgOvernightHrvMs: 50,
      hrvStatus: 'balanced',
      avgSleepStress: 12.2,
      restlessMomentsCount: 3,
      bodyBatteryChange: 55,
      factorsJson: {},
      rawPayload: {},
    },
    manualEntry: null,
    postWorkoutAnalyses: [],
    plannedWorkouts: [
      {
        id: '55555555-5555-4555-8555-555555555555',
        userId: '11111111-1111-4111-8111-111111111111',
        planBlockId: null,
        workoutDate: '2026-06-20',
        version: 1,
        title: 'Tempo ride',
        workoutType: 'bike_tempo',
        status: 'planned',
        isActive: true,
        plannedDurationMin: 60,
        intensityTarget: '85-90% FTP',
        structuredWorkout: {},
        source: 'seed',
        adherence: null,
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
      fan: { autoEnabled: true, mode: 'control', isOn: true, speed: 5, respondingToC: 20.1 },
    },
    dataQualityWarnings: [],
  },
  meta: {
    generatedAtUtc: '2026-06-20T06:40:00Z',
  },
  errors: [],
};

function buildSnapshot(mutator?: (snapshot: DailyLoopEnvelope) => void) {
  const snapshot = JSON.parse(JSON.stringify(baseSnapshot)) as DailyLoopEnvelope;
  mutator?.(snapshot);
  return snapshot;
}

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
    summary: { minTempC: 19, maxTempC: 21, fanRanMinutes: 210, peakSpeed: 5 },
    nights: ['2026-06-19'],
  },
  meta: { generatedAtUtc: '2026-06-20T08:05:00Z' },
  errors: [],
};

function renderPage(snapshot = baseSnapshot) {
  apiFetchMock.mockClear(); // isolate each test's call history (negative assertions)
  apiFetchMock.mockImplementation((path: string) => {
    if (path === '/api/v1/daily-loop') {
      return Promise.resolve(snapshot);
    }
    if (path.startsWith('/api/v1/bedroom/overnight')) {
      return Promise.resolve(overnightSnapshot);
    }
    if (path.includes('/api/v1/workout-delivery/planned-workouts/')) {
      return Promise.resolve({ data: { proposals: [] }, meta: { generatedAtUtc: '2026-06-20T06:45:00Z' }, errors: [] });
    }
    if (path.includes('/api/v1/plan-actions/')) {
      return Promise.resolve({ data: {}, meta: { generatedAtUtc: '2026-06-20T06:45:00Z' }, errors: [] });
    }
    if (path.includes('/post-ride-check-in')) {
      return Promise.resolve(snapshot);
    }
    return Promise.reject(new Error(`Unexpected request: ${path}`));
  });

  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const WORKOUT_ID = '55555555-5555-4555-8555-555555555555';

describe('DashboardPage', () => {
  it('renders the pre-ride flow with sleep snapshot, today card, and detail links', async () => {
    onlineStatus = true;
    renderPage();

    expect((await screen.findAllByText('Good to go')).length).toBeGreaterThan(0);
    expect(screen.getByText("Today's session")).toBeTruthy();
    expect(screen.getByText('Tempo ride')).toBeTruthy();
    // No coach change → the no-changes state: Edit / Swap / Skip, no Approve.
    expect(screen.getByRole('button', { name: /^edit$/i })).toBeTruthy();
    expect(screen.getByRole('button', { name: /swap day/i })).toBeTruthy();
    expect(screen.getByRole('button', { name: /^skip$/i })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /approve & upload/i })).toBeNull();
    expect(screen.getByRole('link', { name: /full morning brief/i }).getAttribute('href')).toBe('/brief');
    expect(screen.getByRole('link', { name: /baselines/i }).getAttribute('href')).toBe('/baselines');
    expect(screen.queryByText('After your ride')).toBeNull();
    // The comparison table now lives inside the "Last night's sleep" card.
    expect(screen.getByText("Last night's sleep")).toBeTruthy();
    expect(screen.getByText('23 above')).toBeTruthy(); // VO₂max vs age-group average, age-only row
    // Batch 31 (redesign): the overnight glance explains *last* night, so it sits
    // in the morning brief next to the sleep snapshot, not the evening bedroom card.
    expect(await screen.findByText('Last night: 19→21 °C, fan ran 3.5 h (peak speed 5)')).toBeTruthy();
  });

  it('edits today’s session with the duration and intensity dials', async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole('button', { name: /^edit$/i }));
    await user.clear(screen.getByLabelText('Duration percentage'));
    await user.type(screen.getByLabelText('Duration percentage'), '80');
    await user.clear(screen.getByLabelText('Intensity percentage'));
    await user.type(screen.getByLabelText('Intensity percentage'), '90');
    await user.click(screen.getByRole('button', { name: /apply & sync/i }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        `/api/v1/workout-delivery/planned-workouts/${WORKOUT_ID}/edit`,
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ durationScalePct: 80, intensityScalePct: 90 }),
        }),
      );
    });
  });

  it('skips today’s session after confirming', async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole('button', { name: /^skip$/i }));
    await user.click(await screen.findByRole('button', { name: /confirm skip/i }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        `/api/v1/workout-delivery/planned-workouts/${WORKOUT_ID}/skip`,
        expect.objectContaining({ method: 'POST' }),
      );
    });
  });

  it('swaps the session to another day', async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole('button', { name: /swap day/i }));
    const hint = await screen.findByText('Move this session to:');
    const dayButtons = within(hint.parentElement as HTMLElement).getAllByRole('button');
    await user.click(dayButtons[0]); // first option = the day after subjectDate (2026-06-21)

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        `/api/v1/workout-delivery/planned-workouts/${WORKOUT_ID}/swap`,
        expect.objectContaining({ method: 'POST', body: JSON.stringify({ targetDate: '2026-06-21' }) }),
      );
    });
  });

  it('shows the coach-changed state and approves the adjustment', async () => {
    const user = userEvent.setup();
    renderPage(
      buildSnapshot((snapshot) => {
        snapshot.data.morningAnalysis!.verdict = 'amber';
        snapshot.data.morningAnalysis!.planAdjustments = ['Cut it to 75% and drop the VO2 set.'];
        snapshot.data.plannedWorkouts[0].delivery = {
          liveStatus: 'pushed',
          liveOrigin: 'as_planned',
          intervalsEventId: 'evt_1',
          changed: true,
          adjustment: { verdict: 'Amber', changed: true },
        };
      }),
    );

    expect(await screen.findByText('Cut it to 75% and drop the VO2 set.')).toBeTruthy();
    expect(screen.getByRole('button', { name: /manual edit/i })).toBeTruthy();
    await user.click(screen.getByRole('button', { name: /approve & upload/i }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        `/api/v1/workout-delivery/planned-workouts/${WORKOUT_ID}/approve-adjustment`,
        expect.objectContaining({ method: 'POST' }),
      );
    });
  });

  it('dismisses the coach suggestion with Ignore (no backend call)', async () => {
    const user = userEvent.setup();
    renderPage(
      buildSnapshot((snapshot) => {
        snapshot.data.plannedWorkouts[0].delivery = {
          liveStatus: 'pushed',
          liveOrigin: 'as_planned',
          intervalsEventId: 'evt_1',
          changed: true,
          adjustment: { verdict: 'Amber', changed: true },
        };
      }),
    );

    await user.click(await screen.findByRole('button', { name: /ignore/i }));

    // Falls back to the no-changes state; Ignore never hits the backend.
    expect(screen.queryByRole('button', { name: /approve & upload/i })).toBeNull();
    expect(screen.getByRole('button', { name: /^edit$/i })).toBeTruthy();
    expect(apiFetchMock).not.toHaveBeenCalledWith(
      expect.stringContaining('/approve-adjustment'),
      expect.anything(),
    );
  });

  it('leads with a non-bike session and offers no Zwift upload', async () => {
    renderPage(
      buildSnapshot((snapshot) => {
        snapshot.data.plannedWorkouts = [
          {
            id: '88888888-8888-4888-8888-888888888888',
            userId: '11111111-1111-4111-8111-111111111111',
            planBlockId: null,
            workoutDate: '2026-06-20',
            version: 1,
            title: 'Strength routine',
            workoutType: 'strength',
            status: 'planned',
            isActive: true,
            plannedDurationMin: 30,
            intensityTarget: null,
            structuredWorkout: {},
            source: 'seed',
            adherence: null,
          },
        ];
      }),
    );

    expect(await screen.findByText('Strength routine')).toBeTruthy();
    expect(screen.getByText('Non-bike session — nothing to upload to Zwift.')).toBeTruthy();
    expect(screen.getByRole('button', { name: /swap day/i })).toBeTruthy();
    expect(screen.getByRole('button', { name: /^skip$/i })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /^edit$/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /approve & upload/i })).toBeNull();
  });

  it('renders the post-ride flow when a ride analysis exists for today', async () => {
    renderPage(
      buildSnapshot((snapshot) => {
        snapshot.data.postWorkoutAnalyses = [
          {
            id: '66666666-6666-4666-8666-666666666666',
            activityId: '77777777-7777-4777-8777-777777777777',
            activityName: 'Tempo ride',
            activityType: 'indoor_cycling',
            generatedAtUtc: '2026-06-20T12:20:00Z',
            promptVersion: 'post-workout-v1',
            modelName: 'claude-sonnet-4-6',
            outputMarkdown: '**Recovery protocol:** refuel within 20 minutes.',
            recoveryDecision: { excluded: false, status: 'ready_for_review' },
            timeSeriesSummary: { power: { avg: 220 } },
            tomorrowImpact: 'Easy endurance tomorrow.',
            postRideCheckIn: null,
          },
        ];
      }),
    );

    expect(await screen.findByText('After your ride')).toBeTruthy();
    expect(screen.getByText('Tomorrow')).toBeTruthy();
    expect(screen.getByText('Tonight')).toBeTruthy();
    expect(screen.getByText('Bedroom')).toBeTruthy();
    expect(screen.getByText('Bedroom fan')).toBeTruthy();
    expect(screen.getByText('Auto · on at speed 5, responding to 20.1°C')).toBeTruthy();
    // Batch 31 (redesign): the overnight glance now lives in the morning brief, not here.
    expect(screen.queryByText('Last night: 19→21 °C, fan ran 3.5 h (peak speed 5)')).toBeNull();
    expect(screen.queryByText("Today's session")).toBeNull();
  });

  it('saves the post-ride check-in from the ride card', async () => {
    const user = userEvent.setup();
    renderPage(
      buildSnapshot((snapshot) => {
        snapshot.data.postWorkoutAnalyses = [
          {
            id: '66666666-6666-4666-8666-666666666666',
            activityId: '77777777-7777-4777-8777-777777777777',
            activityName: 'Tempo ride',
            activityType: 'indoor_cycling',
            generatedAtUtc: '2026-06-20T12:20:00Z',
            promptVersion: 'post-workout-v1',
            modelName: 'claude-sonnet-4-6',
            outputMarkdown: '**Recovery protocol:** refuel within 20 minutes.',
            recoveryDecision: { excluded: false, status: 'ready_for_review' },
            timeSeriesSummary: { power: { avg: 220 } },
            tomorrowImpact: 'Easy endurance tomorrow.',
            postRideCheckIn: null,
          },
        ];
      }),
    );

    await screen.findByText('How did it feel?');
    await user.type(screen.getByLabelText('RPE'), '8');
    await user.type(screen.getByLabelText('Legs'), '6');
    await user.type(screen.getByLabelText('Feel'), 'hard but fair');
    await user.type(screen.getByLabelText('Niggles or notes'), 'Left calf tight.');
    await user.click(screen.getByRole('button', { name: /save ride check-in/i }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/daily-loop/2026-06-20/activities/77777777-7777-4777-8777-777777777777/post-ride-check-in',
        expect.objectContaining({
          method: 'PUT',
          body: JSON.stringify({
            subjectiveScore: 6,
            rpe: 8,
            feel: 'hard but fair',
            notes: 'Left calf tight.',
          }),
        }),
      );
    });
  });

  it('renders a clean rest-day state when nothing is planned', async () => {
    renderPage(
      buildSnapshot((snapshot) => {
        snapshot.data.plannedWorkouts = [];
      }),
    );

    expect(await screen.findByText('Rest day')).toBeTruthy();
    expect(screen.queryByText('After your ride')).toBeNull();
  });

  it('shows the offline banner while keeping the saved phase visible', async () => {
    onlineStatus = false;
    renderPage();

    expect((await screen.findByRole('status')).textContent ?? '').toMatch(/showing your last saved brief/i);
    expect(screen.getByText("Today's session")).toBeTruthy();
    onlineStatus = true;
  });
});
