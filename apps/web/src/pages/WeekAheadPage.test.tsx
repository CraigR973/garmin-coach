import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { WeekAheadPage } from './WeekAheadPage';

const apiFetchMock = vi.fn();
const RealDate = Date;
const mockedNow = new RealDate('2026-06-23T08:00:00Z');

class MockDate extends RealDate {
  constructor(value?: string | number | Date) {
    super(value ?? mockedNow);
  }

  static now() {
    return mockedNow.valueOf();
  }
}

vi.mock('@/lib/api', () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}));

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

vi.mock('@/hooks/useDailyLoop', () => ({
  useDailyLoop: () => ({ data: null }),
}));

const schedule = {
  data: {
    startDate: '2026-06-23',
    days: 14,
    schedule: [
      {
        date: '2026-06-23',
        dayState: { categories: ['cycle', 'flexibility'], label: 'Cycle + Flexibility', isRest: false },
        workouts: [
          {
            id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
            workoutDate: '2026-06-23',
            version: 2,
            title: 'VO2 Max 30/30',
            workoutType: 'bike_vo2',
            status: 'planned',
            plannedDurationMin: 60,
            intensityTarget: '105-110% FTP',
            source: 'test',
          },
          {
            id: 'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
            workoutDate: '2026-06-23',
            version: 3,
            title: 'Flexibility',
            workoutType: 'mobility',
            status: 'planned',
            plannedDurationMin: 16,
            intensityTarget: 'easy',
            source: 'test',
          },
        ],
      },
      {
        date: '2026-06-24',
        dayState: { categories: ['rest'], label: 'Rest', isRest: true },
        workouts: [],
      },
      {
        date: '2026-06-25',
        dayState: { categories: ['cycle'], label: 'Cycle', isRest: false },
        workouts: [
          {
            id: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
            workoutDate: '2026-06-25',
            version: 1,
            title: 'Sweet Spot Builder',
            workoutType: 'bike_sweet_spot',
            status: 'planned',
            plannedDurationMin: 75,
            intensityTarget: '88-94% FTP',
            source: 'test',
          },
        ],
      },
      {
        date: '2026-06-26',
        dayState: { categories: ['rest'], label: 'Rest', isRest: true },
        workouts: [],
      },
    ],
  },
  meta: { generatedAtUtc: '2026-06-23T06:40:00Z' },
  errors: [],
};

describe('WeekAheadPage', () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
    vi.stubGlobal('Date', MockDate as typeof Date);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('renders a move picker with visible days and moves a workout through the swap route', async () => {
    apiFetchMock.mockImplementation((path: string, options?: { method?: string }) => {
      if (options?.method === 'POST') {
        return Promise.resolve(schedule);
      }
      if (path === '/api/v1/plan-actions/schedule?days=14') {
        return Promise.resolve(schedule);
      }
      if (path === '/api/v1/plan-actions/quick-add-options?category=cycle') {
        return Promise.resolve({
          data: {
            category: 'cycle',
            options: [
              { subtype: 'endurance', label: 'Endurance', defaultDurationMin: 45, minDurationMin: 20, maxDurationMin: 90 },
              { subtype: 'sweet_spot', label: 'Sweet Spot', defaultDurationMin: 40, minDurationMin: 25, maxDurationMin: 75 },
            ],
          },
          meta: { generatedAtUtc: '2026-06-23T06:40:00Z' },
          errors: [],
        });
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
    expect(screen.getByText('Cycle + Flexibility')).toBeTruthy();
    expect(screen.getAllByText('Rest day').length).toBeGreaterThan(0);
    expect(screen.getByText('Sweet Spot Builder')).toBeTruthy();

    const firstDay = screen.getByText('VO2 Max 30/30').closest('.rounded-xl') as HTMLElement;
    await user.click(within(firstDay).getByRole('button', { name: /^move$/i }));

    expect(screen.getByText('Choose a day in the current plan window.')).toBeTruthy();
    expect(screen.getAllByText('Today').length).toBeGreaterThan(0);
    expect(screen.getByText('Current day')).toBeTruthy();
    expect(screen.getByRole('button', { name: /Tue, Jun 23/i }).hasAttribute('disabled')).toBe(true);
    expect(screen.getByText('VO2 Max 30/30 · Flexibility')).toBeTruthy();
    expect(screen.getAllByText('Rest').length).toBeGreaterThan(0);

    await user.click(screen.getByRole('button', { name: /Thu, Jun 25/i }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/workout-delivery/planned-workouts/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/swap',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ targetDate: '2026-06-25' }),
        }),
      );
    });

    await user.click(screen.getAllByRole('button', { name: /^cycle$/i })[0]);
    expect(await screen.findByText('Sweet Spot')).toBeTruthy();
    await user.click(screen.getByText('Sweet Spot'));
    await user.click(screen.getByRole('button', { name: /^add$/i }));
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/plan-actions/days/2026-06-23/workouts',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ category: 'cycle', subtype: 'sweet_spot', durationMin: 40 }),
        }),
      );
    });
    expect(screen.queryByText('Swap a workout into this rest day')).toBeNull();
  });

  it('renders a split day (ride + strength) as two independently movable rows (Batch 65)', async () => {
    const splitSchedule = JSON.parse(JSON.stringify(schedule));
    // Model a split Saturday: a ride and a Bodyweight strength on the same day, each
    // its own row with its own Move control (version-as-slot, no schema change).
    splitSchedule.data.schedule[0] = {
      date: '2026-06-23',
      dayState: { categories: ['cycle', 'weights'], label: 'Cycle + Weights', isRest: false },
      workouts: [
        {
          id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
          workoutDate: '2026-06-23',
          version: 1,
          title: 'Z2 + Neuromuscular',
          workoutType: 'bike_endurance',
          status: 'planned',
          plannedDurationMin: 58,
          intensityTarget: 'Zone 2 ~65-72% FTP',
          source: 'plan_no2_import',
        },
        {
          id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
          workoutDate: '2026-06-23',
          version: 2,
          title: 'Bodyweight',
          workoutType: 'strength_maintenance',
          status: 'planned',
          plannedDurationMin: 15,
          intensityTarget: 'Bodyweight circuit',
          source: 'plan_no2_import',
        },
      ],
    };
    apiFetchMock.mockImplementation((path: string) =>
      path === '/api/v1/plan-actions/schedule?days=14'
        ? Promise.resolve(splitSchedule)
        : Promise.reject(new Error(`Unexpected request: ${path}`)),
    );

    const queryClient = new QueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <WeekAheadPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const ride = (await screen.findByText('Z2 + Neuromuscular')).closest('.rounded-xl') as HTMLElement;
    const strength = screen.getByText('Bodyweight').closest('.rounded-xl') as HTMLElement;
    // Two distinct rows, each with its own Move control — the ride can move without
    // dragging the strength.
    expect(ride).not.toBe(strength);
    expect(within(ride).getByRole('button', { name: /^move$/i })).toBeTruthy();
    expect(within(strength).getByRole('button', { name: /^move$/i })).toBeTruthy();
  });

  it('builds a custom ride and edits a planned ride structure (Batch 77)', async () => {
    apiFetchMock.mockImplementation((path: string, options?: { method?: string; body?: string }) => {
      if (path === '/api/v1/plan-actions/schedule?days=14') {
        return Promise.resolve(schedule);
      }
      if (options?.method === 'POST') {
        return Promise.resolve(schedule);
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
    await user.click(screen.getAllByRole('button', { name: /build ride/i })[0]);
    expect(screen.getByText('Build a ride')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: /^add workout$/i }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/plan-actions/days/2026-06-23/workouts',
        expect.objectContaining({
          method: 'POST',
          body: expect.stringContaining('"customBike"'),
        }),
      );
    });
    const addCall = apiFetchMock.mock.calls.find(
      ([path]) => path === '/api/v1/plan-actions/days/2026-06-23/workouts',
    );
    expect(JSON.parse(String(addCall?.[1]?.body))).toMatchObject({
      category: 'cycle',
      customBike: {
        delivery: 'indoor',
        warmupEnabled: true,
        warmupDurationMin: 10,
        intervalsEnabled: false,
        blockDurationMin: 30,
        blockFtpPct: 65,
        cooldownEnabled: true,
        cooldownDurationMin: 5,
      },
    });
    await waitFor(() => expect(screen.queryByText('Build a ride')).toBeNull());

    const firstDay = screen.getByText('VO2 Max 30/30').closest('.rounded-xl') as HTMLElement;
    const editButton = within(firstDay).getByRole('button', { name: /edit structure/i });
    await waitFor(() => expect(editButton.hasAttribute('disabled')).toBe(false));
    await user.click(editButton);
    expect(await screen.findByText('Edit VO2 Max 30/30')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: /^intervals$/i }));
    await user.clear(screen.getByLabelText('Int 1 %FTP'));
    await user.type(screen.getByLabelText('Int 1 %FTP'), '118');
    await user.click(screen.getByRole('button', { name: /^save structure$/i }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/plan-actions/planned-workouts/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/structured',
        expect.objectContaining({
          method: 'POST',
          body: expect.stringContaining('"intervalsEnabled":true'),
        }),
      );
    });
  });

  it('locks a completed workout from moving and marks it Done (Batch 60)', async () => {
    const completedSchedule = JSON.parse(JSON.stringify(schedule));
    // Sweet Spot Builder on 2026-06-25 is done, so the day-level skip action
    // should clearly mean "skip what remains", not rewrite the completed ride.
    completedSchedule.data.schedule[2].workouts[0].status = 'completed';
    apiFetchMock.mockImplementation((path: string) =>
      path === '/api/v1/plan-actions/schedule?days=14'
        ? Promise.resolve(completedSchedule)
        : Promise.reject(new Error(`Unexpected request: ${path}`)),
    );

    const queryClient = new QueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <WeekAheadPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const doneWorkout = (await screen.findByText('Sweet Spot Builder')).closest(
      '.rounded-xl',
    ) as HTMLElement;
    expect(within(doneWorkout).getByText('Done')).toBeTruthy();
    expect(within(doneWorkout).queryByRole('button', { name: /^move$/i })).toBeNull();
    expect(screen.getByRole('button', { name: /skip remaining/i })).toBeTruthy();
    expect(
      screen.getByText(
        'Completed sessions stay on the day. This skips only the sessions still left to do.',
      ),
    ).toBeTruthy();

    // A still-planned workout keeps its Move control.
    const plannedWorkout = screen.getByText('VO2 Max 30/30').closest('.rounded-xl') as HTMLElement;
    expect(within(plannedWorkout).getByRole('button', { name: /^move$/i })).toBeTruthy();
  });

  it('surfaces the Garmin delivery status on an outdoor ride (Batch 78)', async () => {
    const outdoorSchedule = JSON.parse(JSON.stringify(schedule));
    // A failed outdoor upload must show on the workout, never silently drop (#97).
    outdoorSchedule.data.schedule[0].workouts = [
      {
        id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
        workoutDate: '2026-06-23',
        version: 1,
        title: 'Outdoor endurance',
        workoutType: 'bike_endurance',
        status: 'planned',
        plannedDurationMin: 55,
        intensityTarget: '75% FTP',
        source: 'test',
        structuredWorkout: { format: 'bike', delivery: 'outdoor', steps: [] },
        outdoorDelivery: { status: 'failed', lastError: 'garmin upload failed' },
      },
    ];
    // A successfully delivered outdoor ride on another day shows "Sent to Garmin".
    outdoorSchedule.data.schedule[2].workouts = [
      {
        id: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
        workoutDate: '2026-06-25',
        version: 1,
        title: 'Outdoor tempo',
        workoutType: 'bike_tempo',
        status: 'planned',
        plannedDurationMin: 60,
        intensityTarget: '80% FTP',
        source: 'test',
        structuredWorkout: { format: 'bike', delivery: 'outdoor', steps: [] },
        outdoorDelivery: { status: 'pushed', lastError: null },
      },
    ];
    apiFetchMock.mockImplementation((path: string) =>
      path === '/api/v1/plan-actions/schedule?days=14'
        ? Promise.resolve(outdoorSchedule)
        : Promise.reject(new Error(`Unexpected request: ${path}`)),
    );

    const queryClient = new QueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <WeekAheadPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText(/Garmin send failed/i)).toBeTruthy();
    expect(screen.getByText('Sent to Garmin')).toBeTruthy();
  });

  it('renders the shared error state when the schedule fails to load', async () => {
    apiFetchMock.mockImplementation((path: string) =>
      path === '/api/v1/plan-actions/schedule?days=14'
        ? Promise.reject(new Error('Network down'))
        : Promise.reject(new Error(`Unexpected request: ${path}`)),
    );
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <WeekAheadPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Plan couldn't load")).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeTruthy();
  });
});
