import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { DashboardPage } from './DashboardPage';

const apiFetchMock = vi.fn();

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

const snapshot = {
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
    postWorkoutAnalyses: [
      {
        id: '66666666-6666-4666-8666-666666666666',
        activityId: '77777777-7777-4777-8777-777777777777',
        activityName: 'Tempo ride',
        activityType: 'indoor_cycling',
        generatedAtUtc: '2026-06-20T12:20:00Z',
        promptVersion: 'post-workout-v1',
        modelName: 'claude-sonnet-4-6',
        outputMarkdown: '**Recovery protocol:** refuel within 20 minutes.\n\n**Tomorrow impact:** easy endurance.',
        recoveryDecision: { excluded: false, status: 'ready_for_review' },
        timeSeriesSummary: { power: { avg: 220 } },
        tomorrowImpact: null,
      },
    ],
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
    },
    dataQualityWarnings: [
      {
        id: 'no_lr_balance',
        summary: 'Ignore left/right power balance.',
        reason: 'Single-sided meter doubles one leg.',
        status: 'info',
        detail: null,
      },
    ],
  },
  meta: {
    generatedAtUtc: '2026-06-20T06:40:00Z',
  },
  errors: [],
};

describe('DashboardPage', () => {
  it('renders the daily loop and saves the manual check-in', async () => {
    apiFetchMock.mockImplementation((path: string, options?: { method?: string }) => {
      if (options?.method === 'PUT') {
        return Promise.resolve(snapshot);
      }
      if (path === '/api/v1/daily-loop') {
        return Promise.resolve(snapshot);
      }
      return Promise.reject(new Error(`Unexpected request: ${path}`));
    });

    const queryClient = new QueryClient();
    const user = userEvent.setup();

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <DashboardPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText('Morning verdict')).toBeTruthy();
    expect(screen.getAllByText('Tempo ride').length).toBeGreaterThan(0);
    expect(screen.getByText('Post-workout analysis')).toBeTruthy();
    expect(screen.getByText(/refuel within 20 minutes/)).toBeTruthy();

    await user.type(screen.getByLabelText('BP systolic'), '108');
    await user.click(screen.getByRole('button', { name: 'Save check-in' }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/daily-loop/2026-06-20/manual-entry',
        expect.objectContaining({ method: 'PUT' }),
      );
    });
  });
});
