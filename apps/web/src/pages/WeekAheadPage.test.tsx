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
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/plan-actions/days/2026-06-23/workouts',
        expect.objectContaining({ method: 'POST', body: JSON.stringify({ category: 'cycle' }) }),
      );
    });
    expect(screen.queryByText('Swap a workout into this rest day')).toBeNull();
  });
});
