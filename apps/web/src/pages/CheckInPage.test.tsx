import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { CheckInPage } from './CheckInPage';

const apiFetchMock = vi.fn();

vi.mock('@/lib/api', () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const snapshot = {
  data: {
    subjectDate: '2026-06-20',
    timezone: 'Europe/London',
    morningAnalysis: null,
    dailyMetrics: null,
    sleep: null,
    manualEntry: null,
    postWorkoutAnalyses: [],
    postFlexibilityAnalyses: [],
    postStrengthAnalyses: [],
    postWalkAnalyses: [],
    plannedWorkouts: [],
    thermalState: {
      thermalReview: {},
      fan: { autoEnabled: true, mode: 'idle', isOn: false, speed: null, respondingToC: null },
    },
    dataQualityWarnings: [],
    walkingBrief: {
      asOfDate: '2026-06-20',
      window4w: { sessionCount: 0, totalDistanceM: 0, totalDurationMin: 0, sessionsPerWeek: 0 },
      window12w: { sessionCount: 0, totalDistanceM: 0, totalDurationMin: 0, sessionsPerWeek: 0 },
      recentSessions: [],
      trend: 'insufficient_data',
      trendReason: 'Only 0 walk(s) in the last 28 days.',
    },
  },
  meta: { generatedAtUtc: '2026-06-20T06:40:00Z' },
  errors: [],
};

describe('CheckInPage', () => {
  it('saves the manual check-in via the single unified save action', async () => {
    apiFetchMock.mockImplementation((path: string, options?: { method?: string }) => {
      if (options?.method === 'PUT') return Promise.resolve(snapshot);
      if (path === '/api/v1/daily-loop') return Promise.resolve(snapshot);
      return Promise.reject(new Error(`Unexpected request: ${path}`));
    });

    const queryClient = new QueryClient();
    const user = userEvent.setup();

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <CheckInPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await user.type(await screen.findByLabelText('Systolic'), '108');
    // Batch 55: one "Save check-in" button covers the whole page — no more
    // separate per-card/per-workout save buttons.
    expect(screen.queryByRole('button', { name: 'Save session' })).toBeNull();
    await user.click(screen.getByRole('button', { name: 'Save check-in' }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/daily-loop/2026-06-20/manual-entry',
        expect.objectContaining({ method: 'PUT' }),
      );
    });
  });

  it('also saves each planned workout\'s adherence in the same unified save', async () => {
    const withWorkout = {
      ...snapshot,
      data: {
        ...snapshot.data,
        plannedWorkouts: [
          {
            id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
            userId: '11111111-1111-4111-8111-111111111111',
            planBlockId: null,
            workoutDate: '2026-06-20',
            version: 1,
            title: 'Sweet Spot Builder',
            workoutType: 'bike_sweet_spot',
            status: 'planned',
            isActive: true,
            plannedDurationMin: 60,
            intensityTarget: '88-94% FTP',
            structuredWorkout: {},
            source: 'test',
            adherence: null,
          },
        ],
      },
    };
    apiFetchMock.mockImplementation((path: string, options?: { method?: string }) => {
      if (options?.method === 'PUT') return Promise.resolve(withWorkout);
      if (path === '/api/v1/daily-loop') return Promise.resolve(withWorkout);
      return Promise.reject(new Error(`Unexpected request: ${path}`));
    });

    const queryClient = new QueryClient();
    const user = userEvent.setup();

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <CheckInPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await screen.findByText('Sweet Spot Builder');
    await user.click(screen.getByRole('button', { name: 'Save check-in' }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/daily-loop/2026-06-20/planned-workouts/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/adherence',
        expect.objectContaining({ method: 'PUT' }),
      );
    });
  });

  it('shows the shared error state when the daily loop fails to load, without blocking manual entry', async () => {
    apiFetchMock.mockImplementation((path: string) => {
      if (path === '/api/v1/daily-loop') return Promise.reject(new Error('Network down'));
      return Promise.reject(new Error(`Unexpected request: ${path}`));
    });

    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <CheckInPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Couldn't load today's plan")).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeTruthy();
    expect(screen.getByLabelText('Systolic')).toBeTruthy();
  });
});
