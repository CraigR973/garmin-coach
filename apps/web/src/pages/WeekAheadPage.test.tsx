import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { WeekAheadPage } from './WeekAheadPage';

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

const weekAhead = {
  data: {
    startDate: '2026-06-23',
    days: 7,
    workouts: [
      {
        plannedWorkoutId: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
        workoutDate: '2026-06-23',
        version: 2,
        title: 'VO2 Max 30/30',
        workoutType: 'bike_vo2',
        status: 'planned',
        plannedDurationMin: 60,
        intensityTarget: '105-110% FTP',
        deliverable: true,
        proposal: {
          id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
          userId: '11111111-1111-4111-8111-111111111111',
          plannedWorkoutId: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
          plannedWorkoutVersion: 2,
          workoutDate: '2026-06-23',
          provider: 'intervals_icu',
          status: 'proposed',
          proposedAtUtc: '2026-06-23T06:31:00Z',
          approvedAtUtc: null,
          approvedByProfileId: null,
          pushedAtUtc: null,
          intervalsEventId: null,
          structuredWorkoutIr: {
            origin: 'amber_regeneration',
            adjustment: {
              changed: true,
              verdict: 'Amber',
              durationScalePct: 75,
              zoneDropPct: 13,
              removedHit: true,
            },
          },
          intervalsPayload: {},
          zwoXml: '<workout_file/>',
          lastError: null,
        },
      },
      {
        plannedWorkoutId: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
        workoutDate: '2026-06-25',
        version: 1,
        title: 'Sweet Spot Builder',
        workoutType: 'bike_sweet_spot',
        status: 'planned',
        plannedDurationMin: 75,
        intensityTarget: '88-94% FTP',
        deliverable: true,
        proposal: null,
      },
    ],
  },
  meta: { generatedAtUtc: '2026-06-23T06:40:00Z' },
  errors: [],
};

describe('WeekAheadPage', () => {
  it('renders the week ahead and approves a proposed workout', async () => {
    apiFetchMock.mockImplementation((path: string, options?: { method?: string }) => {
      if (options?.method === 'POST') {
        return Promise.resolve(weekAhead);
      }
      if (path === '/api/v1/workout-delivery/week-ahead') {
        return Promise.resolve(weekAhead);
      }
      return Promise.reject(new Error(`Unexpected request: ${path}`));
    });

    const queryClient = new QueryClient();
    const user = userEvent.setup();

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <WeekAheadPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText('VO2 Max 30/30')).toBeTruthy();
    // The Amber-adjusted proposal is flagged and its adjustment summarised.
    expect(screen.getByText('Amber-adjusted')).toBeTruthy();
    expect(screen.getByText(/HIT removed/)).toBeTruthy();
    // The un-proposed bike workout offers a Propose action.
    expect(screen.getByText('Sweet Spot Builder')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Propose' })).toBeTruthy();

    await user.click(screen.getByRole('button', { name: 'Approve' }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/workout-delivery/proposals/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb/approve',
        expect.objectContaining({ method: 'POST' }),
      );
    });
  });
});
