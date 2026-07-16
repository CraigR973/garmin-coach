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

const useAuthMock = vi.fn(() => ({
  player: { id: 'admin-1', displayName: 'Craig', role: 'admin', timezone: 'Europe/London' },
}));

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => useAuthMock(),
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

async function openEditWeek(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('tab', { name: 'Edit week' }));
}

function workoutRow(title: string): HTMLElement {
  return screen.getAllByText(title, { selector: 'p' })[0]!.closest('div.rounded-xl.border') as HTMLElement;
}

describe('WeekAheadPage', () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
    useAuthMock.mockReturnValue({
      player: { id: 'admin-1', displayName: 'Craig', role: 'admin', timezone: 'Europe/London' },
    });
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

    expect(await screen.findByRole('heading', { name: 'Week' })).toBeTruthy();
    expect(await screen.findByText('VO2 Max 30/30')).toBeTruthy();
    expect(screen.getByRole('tab', { name: 'This week' }).getAttribute('aria-selected')).toBe('true');
    expect(screen.getByText('3 sessions')).toBeTruthy();
    expect(screen.getByText('0 done')).toBeTruthy();
    expect(screen.getByText('3 to do')).toBeTruthy();
    expect(screen.getByRole('tab', { name: 'Edit week' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /move$/i })).toBeNull();

    await openEditWeek(user);
    expect(within(workoutRow('VO2 Max 30/30')).getByRole('button', { name: /^move$/i })).toBeTruthy();
    expect(screen.getByText('Cycle + Flexibility')).toBeTruthy();
    expect(screen.getAllByText('Rest day').length).toBeGreaterThan(0);
    expect(screen.getByText('Sweet Spot Builder')).toBeTruthy();

    const firstDay = workoutRow('VO2 Max 30/30');
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

  it('keeps Mark on a read-only week glance and hides organiser controls (Batch 126)', async () => {
    useAuthMock.mockReturnValue({
      player: { id: 'mark-1', displayName: 'Mark', role: 'player', timezone: 'Europe/London' },
    });
    apiFetchMock.mockImplementation((path: string) =>
      path === '/api/v1/plan-actions/schedule?days=14'
        ? Promise.resolve(schedule)
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

    expect(await screen.findByText('This week')).toBeTruthy();
    expect(screen.queryByRole('tab', { name: 'Edit week' })).toBeNull();
    expect(screen.queryByRole('button', { name: /^move$/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /^cycle$/i })).toBeNull();
    expect(screen.queryByText('Holiday')).toBeNull();
    expect(screen.getAllByText('To do').length).toBeGreaterThan(0);
  });

  it('shows an unplanned walk chip on a rest day in the read-first week glance (Batch 133)', async () => {
    const walkedWeek = JSON.parse(JSON.stringify(schedule));
    walkedWeek.data.schedule[1].activities = [
      {
        activityKind: 'walk',
        name: 'Evening Walk',
        durationMin: 70,
        startUtc: '2026-06-24T18:00:00Z',
      },
    ];
    apiFetchMock.mockImplementation((path: string) =>
      path === '/api/v1/plan-actions/schedule?days=14'
        ? Promise.resolve(walkedWeek)
        : Promise.reject(new Error(`Unexpected request: ${path}`)),
    );

    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <WeekAheadPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText('VO2 Max 30/30')).toBeTruthy();
    expect(screen.getByText((content) => content.includes('Walk') && content.includes('70 min'))).toBeTruthy();
  });

  it('does not double-count a completed planned ride as an extra activity chip (Batch 133)', async () => {
    const completedRideWeek = JSON.parse(JSON.stringify(schedule));
    completedRideWeek.data.schedule[0].workouts = [
      {
        id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
        workoutDate: '2026-06-23',
        version: 2,
        title: 'VO2 Max 30/30',
        workoutType: 'bike_vo2',
        status: 'completed',
        plannedDurationMin: 60,
        intensityTarget: '105-110% FTP',
        source: 'test',
      },
    ];
    completedRideWeek.data.schedule[0].activities = [
      // Backend suppresses same-kind activity chips when the planned session already
      // completed, so the UI contract here is simply "no activity chip present".
    ];
    apiFetchMock.mockImplementation((path: string) =>
      path === '/api/v1/plan-actions/schedule?days=14'
        ? Promise.resolve(completedRideWeek)
        : Promise.reject(new Error(`Unexpected request: ${path}`)),
    );

    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <WeekAheadPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText('VO2 Max 30/30')).toBeTruthy();
    expect(screen.queryByText((content) => content.includes('Ride') && content.includes('60 min'))).toBeNull();
    expect(screen.getByText('1 done')).toBeTruthy();
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
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <WeekAheadPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await screen.findByText('Z2 + Neuromuscular');
    await openEditWeek(user);
    const ride = workoutRow('Z2 + Neuromuscular');
    const strength = workoutRow('Bodyweight');
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
    await openEditWeek(user);
    await user.click(screen.getAllByRole('button', { name: /build ride/i })[0]);
    expect(screen.getByText('Build a ride')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: /^add workout$/i }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/plan-actions/days/2026-06-23/workouts',
        expect.objectContaining({
          method: 'POST',
          body: expect.stringContaining('"segments"'),
        }),
      );
    });
    const addCall = apiFetchMock.mock.calls.find(
      ([path]) => path === '/api/v1/plan-actions/days/2026-06-23/workouts',
    );
    // Free-form default (Batch 88): warm-up ramp → steady → cool-down ramp.
    expect(JSON.parse(String(addCall?.[1]?.body))).toMatchObject({
      category: 'cycle',
      customBike: {
        delivery: 'indoor',
        segments: [
          { kind: 'ramp', durationMin: 10, startFtpPct: 45, endFtpPct: 75 },
          { kind: 'steady', durationMin: 20, ftpPct: 65 },
          { kind: 'ramp', durationMin: 5, startFtpPct: 75, endFtpPct: 45 },
        ],
      },
    });
    await waitFor(() => expect(screen.queryByText('Build a ride')).toBeNull());

    const firstDay = workoutRow('VO2 Max 30/30');
    const editButton = within(firstDay).getByRole('button', { name: /edit structure/i });
    await waitFor(() => expect(editButton.hasAttribute('disabled')).toBe(false));
    await user.click(editButton);
    expect(await screen.findByText('Edit VO2 Max 30/30')).toBeTruthy();
    // Append an interval segment and save — proves the free-form editor posts the
    // ordered segment list to the same structured-edit endpoint.
    await user.click(screen.getByRole('button', { name: /^intervals$/i }));
    await user.click(screen.getByRole('button', { name: /^save structure$/i }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/plan-actions/planned-workouts/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/structured',
        expect.objectContaining({
          method: 'POST',
          body: expect.stringContaining('"kind":"interval"'),
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
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <WeekAheadPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await screen.findByText('Sweet Spot Builder');
    await openEditWeek(user);
    const doneWorkout = workoutRow('Sweet Spot Builder');
    expect(within(doneWorkout).getByText('Done')).toBeTruthy();
    expect(within(doneWorkout).queryByRole('button', { name: /^move$/i })).toBeNull();
    expect(screen.getByRole('button', { name: /skip remaining/i })).toBeTruthy();
    expect(
      screen.getByText(
        'Completed sessions stay on the day. This skips only the sessions still left to do.',
      ),
    ).toBeTruthy();

    // A still-planned workout keeps its Move control.
    const plannedWorkout = workoutRow('VO2 Max 30/30');
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
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <WeekAheadPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await screen.findByText('Outdoor endurance');
    await openEditWeek(user);
    expect(await screen.findByText(/Garmin send failed/i)).toBeTruthy();
    expect(screen.getByText('Sent to Garmin')).toBeTruthy();
  });

  it('skips just one workout without touching the rest of the day (Batch 79)', async () => {
    apiFetchMock.mockImplementation((path: string, options?: { method?: string }) => {
      if (options?.method === 'POST') {
        return Promise.resolve(schedule);
      }
      if (path === '/api/v1/plan-actions/schedule?days=14') {
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

    await screen.findByText('VO2 Max 30/30');
    await openEditWeek(user);
    const vo2Row = workoutRow('VO2 Max 30/30');
    await user.click(within(vo2Row).getByRole('button', { name: /^skip$/i }));
    expect(within(vo2Row).getByText(/Skip just this session/i)).toBeTruthy();
    await user.click(within(vo2Row).getByRole('button', { name: /confirm skip/i }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/workout-delivery/planned-workouts/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/skip',
        expect.objectContaining({ method: 'POST' }),
      );
    });
    // The day's other workout (Flexibility) is a distinct row untouched by this action.
    expect(screen.getByText('Flexibility', { selector: 'p' })).toBeTruthy();
    expect(apiFetchMock).not.toHaveBeenCalledWith(
      '/api/v1/plan-actions/days/2026-06-23/skip',
      expect.anything(),
    );
  });

  it('removes only a user-added workout, leaving coach-planned sessions their Skip control (Batch 79)', async () => {
    const mixedSchedule = JSON.parse(JSON.stringify(schedule));
    mixedSchedule.data.schedule[0].workouts[1].source = 'plan_action_add';
    apiFetchMock.mockImplementation((path: string, options?: { method?: string }) => {
      if (options?.method === 'POST') {
        return Promise.resolve(mixedSchedule);
      }
      if (path === '/api/v1/plan-actions/schedule?days=14') {
        return Promise.resolve(mixedSchedule);
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

    await screen.findByText('VO2 Max 30/30');
    await openEditWeek(user);
    const vo2Row = workoutRow('VO2 Max 30/30');
    // The coach-planned VO2 session (source !== 'plan_action_add') has no Remove control.
    expect(within(vo2Row).queryByRole('button', { name: /^remove$/i })).toBeNull();

    const flexRow = workoutRow('Flexibility');
    await user.click(within(flexRow).getByRole('button', { name: /^remove$/i }));
    expect(within(flexRow).getByText(/Remove this added workout/i)).toBeTruthy();
    await user.click(within(flexRow).getByRole('button', { name: /confirm remove/i }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/workout-delivery/planned-workouts/dddddddd-dddd-4ddd-8ddd-dddddddddddd/remove',
        expect.objectContaining({ method: 'POST' }),
      );
    });
    // Removing the added Flexibility session leaves VO2 Max in place — same
    // endpoints Home uses (DashboardPage), so Home ↔ Week parity holds.
    expect(screen.getByText('VO2 Max 30/30')).toBeTruthy();
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

  it('links to Holiday and New training block from the organiser (Batch 81)', async () => {
    apiFetchMock.mockImplementation((path: string) =>
      path === '/api/v1/plan-actions/schedule?days=14'
        ? Promise.resolve(schedule)
        : Promise.reject(new Error(`Unexpected request: ${path}`)),
    );
    const queryClient = new QueryClient();
    const user = userEvent.setup();

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <WeekAheadPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await screen.findByText('VO2 Max 30/30');
    await openEditWeek(user);
    expect(screen.getByRole('link', { name: /holiday/i }).getAttribute('href')).toBe('/holiday');
    expect(screen.getByRole('link', { name: /new training block/i }).getAttribute('href')).toBe(
      '/builder',
    );
  });

  it('shows each week\'s block character, with a holiday overriding it (Batch 81)', async () => {
    const blockSchedule = JSON.parse(JSON.stringify(schedule));
    blockSchedule.data.schedule[0].weekCharacter = {
      label: 'Build 4/13',
      sequenceIndex: 4,
      blockType: 'build',
      isHoliday: false,
    };
    blockSchedule.data.schedule[1].weekCharacter = {
      label: 'Build 4/13',
      sequenceIndex: 4,
      blockType: 'build',
      isHoliday: false,
    };
    blockSchedule.data.schedule[2].weekCharacter = {
      label: 'Holiday',
      sequenceIndex: 5,
      blockType: 'build',
      isHoliday: true,
    };
    blockSchedule.data.schedule[3].weekCharacter = {
      label: 'Holiday',
      sequenceIndex: 5,
      blockType: 'build',
      isHoliday: true,
    };
    apiFetchMock.mockImplementation((path: string) =>
      path === '/api/v1/plan-actions/schedule?days=14'
        ? Promise.resolve(blockSchedule)
        : Promise.reject(new Error(`Unexpected request: ${path}`)),
    );
    const queryClient = new QueryClient();
    const user = userEvent.setup();

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <WeekAheadPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await screen.findByText('VO2 Max 30/30');
    await openEditWeek(user);
    await screen.findByText('Build 4/13');
    // The character banner appears once per contiguous run, not once per day.
    // (The "Holiday" nav link also matches the text, so scope to the badge div.)
    expect(screen.getAllByText('Build 4/13')).toHaveLength(1);
    expect(screen.getAllByText('Holiday', { selector: 'div' })).toHaveLength(1);
  });

  it('marks and restores a light reset week from the week banner (Batch 82)', async () => {
    const resetSchedule = JSON.parse(JSON.stringify(schedule));
    resetSchedule.data.schedule[0].weekCharacter = {
      label: 'Build 4/13',
      sequenceIndex: 4,
      blockType: 'build',
      isHoliday: false,
      isReset: false,
    };
    const activeResetSchedule = JSON.parse(JSON.stringify(resetSchedule));
    activeResetSchedule.data.schedule[0].weekCharacter = {
      label: 'Light reset',
      sequenceIndex: 4,
      blockType: 'build',
      isHoliday: false,
      isReset: true,
    };
    apiFetchMock.mockImplementation((path: string, options?: { method?: string }) => {
      if (path === '/api/v1/plan-actions/schedule?days=14') {
        return Promise.resolve(resetSchedule);
      }
      if (path === '/api/v1/plan-actions/weeks/2026-06-23/reset' && options?.method === 'POST') {
        return Promise.resolve(activeResetSchedule);
      }
      if (path === '/api/v1/plan-actions/weeks/2026-06-23/reset' && options?.method === 'DELETE') {
        return Promise.resolve(resetSchedule);
      }
      return Promise.reject(new Error(`Unexpected request: ${path}`));
    });
    const queryClient = new QueryClient();
    const user = userEvent.setup();

    const view = render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <WeekAheadPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await screen.findByText('VO2 Max 30/30');
    await openEditWeek(user);
    await screen.findByText('Build 4/13');
    await user.click(screen.getByRole('button', { name: /light reset/i }));
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/plan-actions/weeks/2026-06-23/reset',
        expect.objectContaining({ method: 'POST' }),
      );
    });

    view.unmount();
    apiFetchMock.mockImplementation((path: string, options?: { method?: string }) => {
      if (path === '/api/v1/plan-actions/schedule?days=14') {
        return Promise.resolve(activeResetSchedule);
      }
      if (path === '/api/v1/plan-actions/weeks/2026-06-23/reset' && options?.method === 'DELETE') {
        return Promise.resolve(resetSchedule);
      }
      return Promise.reject(new Error(`Unexpected request: ${path}`));
    });
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <WeekAheadPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await screen.findByText('VO2 Max 30/30');
    await openEditWeek(user);
    await screen.findByText('Light reset');
    await user.click(screen.getByRole('button', { name: /restore week/i }));
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/plan-actions/weeks/2026-06-23/reset',
        expect.objectContaining({ method: 'DELETE' }),
      );
    });
  });

  it('previews and applies a whole-week restructure from the organiser (Batch 83)', async () => {
    const restructureSchedule = JSON.parse(JSON.stringify(schedule));
    restructureSchedule.data.schedule[0].weekCharacter = {
      label: 'Build 4/13',
      sequenceIndex: 4,
      blockType: 'build',
      isHoliday: false,
      isReset: false,
    };
    const restructurePreview = {
      data: {
        weekStart: '2026-06-22',
        fatigued: true,
        changed: true,
        signal: {
          fatigued: true,
          readinessScore: 34,
          hrvStatus: 'low',
          recentVerdicts: ['amber', 'amber'],
          reasons: ['Training Readiness is low.'],
        },
        changes: [
          {
            workoutDate: '2026-06-23',
            fromWorkoutId: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
            toWorkoutId: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
            reason: 'defer_fatigue',
          },
          {
            workoutDate: '2026-06-25',
            fromWorkoutId: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
            toWorkoutId: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
            reason: 'defer_fatigue',
          },
        ],
        conflictsBefore: [['2026-06-23', '2026-06-25']],
        conflictsAfter: [],
        notes: ['Fatigue detected — hard sessions deferred later in the week.'],
        proposalsCreated: 0,
      },
      meta: { generatedAtUtc: '2026-06-23T06:40:00Z' },
      errors: [],
    };
    apiFetchMock.mockImplementation((path: string, options?: { method?: string }) => {
      if (path === '/api/v1/plan-actions/schedule?days=14') {
        return Promise.resolve(restructureSchedule);
      }
      if (path === '/api/v1/restructure/week-ahead?week_start=2026-06-22') {
        return Promise.resolve(restructurePreview);
      }
      if (path === '/api/v1/restructure/apply?week_start=2026-06-22' && options?.method === 'POST') {
        return Promise.resolve(restructurePreview);
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

    await screen.findByText('VO2 Max 30/30');
    await openEditWeek(user);
    await screen.findByText('Build 4/13');
    await user.click(screen.getByRole('button', { name: /rearrange week/i }));

    expect(await screen.findByText('Training Readiness is low.')).toBeTruthy();
    expect(
      screen.getByText((content) => content.includes('Sweet Spot Builder') && content.includes('23')),
    ).toBeTruthy();
    expect(screen.getByText('Replaces VO2 Max 30/30 on this day.')).toBeTruthy();
    expect(screen.getByText((content) => content.includes('VO2 Max 30/30') && content.includes('25'))).toBeTruthy();

    await user.click(screen.getByRole('button', { name: /apply reshuffle/i }));
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/restructure/apply?week_start=2026-06-22',
        expect.objectContaining({ method: 'POST' }),
      );
    });
  });
});
