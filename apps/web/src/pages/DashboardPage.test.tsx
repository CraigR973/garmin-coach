import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
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

function renderPage(snapshot = baseSnapshot) {
  apiFetchMock.mockImplementation((path: string) => {
    if (path === '/api/v1/daily-loop') {
      return Promise.resolve(snapshot);
    }
    if (path.includes('/api/v1/workout-delivery/planned-workouts/')) {
      return Promise.resolve({ data: { proposals: [] }, meta: { generatedAtUtc: '2026-06-20T06:45:00Z' }, errors: [] });
    }
    if (path.includes('/post-ride-check-in')) {
      return Promise.resolve(snapshot);
    }
    return Promise.reject(new Error(`Unexpected request: ${path}`));
  });

  const queryClient = new QueryClient();

  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('DashboardPage', () => {
  it('renders the pre-ride flow with sleep snapshot, ride card, and detail links', async () => {
    onlineStatus = true;
    renderPage();

    expect((await screen.findAllByText('Good to go')).length).toBeGreaterThan(0);
    expect(screen.getByText("Today's ride")).toBeTruthy();
    expect(screen.getByText('Tempo ride')).toBeTruthy();
    expect(screen.getByRole('link', { name: /full morning brief/i }).getAttribute('href')).toBe('/brief');
    expect(screen.getByRole('link', { name: /baselines/i }).getAttribute('href')).toBe('/baselines');
    expect(screen.queryByText('After your ride')).toBeNull();
    // Age comparison surfaces fitness age + the population read.
    expect(screen.getByText('How you compare for your age')).toBeTruthy();
    expect(screen.getByText(/9 years younger than your actual age/i)).toBeTruthy();
  });

  it('sends today’s ride to Zwift from Home', async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole('button', { name: /send to zwift/i }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/workout-delivery/planned-workouts/55555555-5555-4555-8555-555555555555/send-today',
        expect.objectContaining({ method: 'POST', body: '{}' }),
      );
    });
  });

  it('sends a manual override with duration and intensity dials', async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole('button', { name: /override/i }));
    await user.clear(screen.getByLabelText('Duration percentage'));
    await user.type(screen.getByLabelText('Duration percentage'), '80');
    await user.clear(screen.getByLabelText('Intensity percentage'));
    await user.type(screen.getByLabelText('Intensity percentage'), '90');
    await user.click(screen.getByRole('button', { name: /send override/i }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/workout-delivery/planned-workouts/55555555-5555-4555-8555-555555555555/send-today',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ durationScalePct: 80, intensityScalePct: 90 }),
        }),
      );
    });
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
    expect(screen.queryByText("Today's ride")).toBeNull();
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

  it('renders a clean rest-day state when no bike ride is planned', async () => {
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

    expect(await screen.findByText('Nothing to ride today')).toBeTruthy();
    expect(screen.getByText('Strength routine')).toBeTruthy();
    expect(screen.queryByText('After your ride')).toBeNull();
  });

  it('shows the offline banner while keeping the saved phase visible', async () => {
    onlineStatus = false;
    renderPage();

    expect((await screen.findByRole('status')).textContent ?? '').toMatch(/showing your last saved brief/i);
    expect(screen.getByText("Today's ride")).toBeTruthy();
    onlineStatus = true;
  });
});
