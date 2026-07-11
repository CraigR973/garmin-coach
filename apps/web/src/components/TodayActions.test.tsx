import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { DailyLoopData } from '@/hooks/useDailyLoop';
import { TodayActions } from './TodayActions';

type TodayAction = NonNullable<DailyLoopData['morningAnalysis']>['todayActions'][number];
type TodayWorkout = DailyLoopData['plannedWorkouts'][number];

const apiFetchMock = vi.fn();

vi.mock('@/lib/api', () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

function ride(overrides: Partial<TodayWorkout> = {}): TodayWorkout {
  return {
    id: 'w1',
    workoutType: 'bike_sweet_spot',
    delivery: { changed: true },
    ...overrides,
  } as unknown as TodayWorkout;
}

function renderActions(actions: TodayAction[], workouts: TodayWorkout[] = []) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <TodayActions actions={actions} workouts={workouts} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  apiFetchMock.mockReset();
});

describe('TodayActions (Batch 86)', () => {
  it('renders swap, ride, sleep, and thermal actions with the right affordances', () => {
    const actions: TodayAction[] = [
      {
        kind: 'apply_swap',
        title: 'Move VO2 5x4 to Saturday',
        detail: 'Pull Zone 2 forward to today.',
        plannedWorkoutId: 'h1',
        targetDate: '2026-07-18',
      },
      {
        kind: 'approve_ride',
        title: "Approve today's eased ride",
        detail: 'Cut 20-30%, drop a zone, no HIT/VO2.',
        plannedWorkoutId: 'w1',
      },
      { kind: 'sleep', title: 'Wind-down breathwork tonight', href: '/sleep' },
      { kind: 'thermal', title: 'Pre-cool the bedroom tonight', href: '/sleep' },
    ];

    renderActions(actions, [ride()]);

    expect(screen.getByTestId('today-actions')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Approve' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Apply' })).toBeTruthy();
    expect(screen.getByText('Wind-down breathwork tonight')).toBeTruthy();
    expect(screen.getByText('Pre-cool the bedroom tonight')).toBeTruthy();
    // Informational nudges deep-link to their hub.
    const links = screen.getAllByRole('link');
    expect(links.map((link) => link.getAttribute('href'))).toEqual(['/sleep', '/sleep']);
  });

  it('approves the eased ride through the existing rail', async () => {
    apiFetchMock.mockResolvedValue({});
    const actions: TodayAction[] = [
      { kind: 'approve_ride', title: "Approve today's eased ride", plannedWorkoutId: 'w1' },
    ];

    renderActions(actions, [ride()]);
    await userEvent.click(screen.getByRole('button', { name: 'Approve' }));

    await waitFor(() =>
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/workout-delivery/planned-workouts/w1/approve-adjustment',
        { method: 'POST' },
      ),
    );
  });

  it('applies a swap through the existing swap endpoint', async () => {
    apiFetchMock.mockResolvedValue({});
    const actions: TodayAction[] = [
      {
        kind: 'apply_swap',
        title: 'Move VO2 to Saturday',
        plannedWorkoutId: 'h1',
        targetDate: '2026-07-18',
      },
    ];

    renderActions(actions, []);
    await userEvent.click(screen.getByRole('button', { name: 'Apply' }));

    await waitFor(() =>
      expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/workout-delivery/planned-workouts/h1/swap', {
        method: 'POST',
        body: JSON.stringify({ targetDate: '2026-07-18' }),
      }),
    );
  });

  it('drops an eased-ride action once the ride is no longer pending', () => {
    const actions: TodayAction[] = [
      { kind: 'approve_ride', title: "Approve today's eased ride", plannedWorkoutId: 'w1' },
    ];

    // delivery.changed=false → already approved/pushed, so no stale "Approve".
    renderActions(actions, [ride({ delivery: { changed: false } } as Partial<TodayWorkout>)]);

    expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull();
    // The only action dropped out, so the whole block is absent.
    expect(screen.queryByTestId('today-actions')).toBeNull();
  });

  it('renders nothing when there are no actions', () => {
    renderActions([], []);
    expect(screen.queryByTestId('today-actions')).toBeNull();
  });
});
