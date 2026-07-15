import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { CoachStatePage } from './CoachStatePage';

const apiFetchMock = vi.fn();
const useAuthMock = vi.fn();

vi.mock('@/lib/api', () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => useAuthMock(),
}));

const coachMemoryResponse = {
  data: {
    knowledgeBaseSections: [
      {
        id: '11111111-1111-4111-8111-111111111111',
        userId: '11111111-1111-4111-8111-111111111111',
        section: 'profile',
        version: 1,
        isActive: true,
        source: 'seed',
        updatedByProfileId: null,
        content: {
          athleteName: 'Mark',
          age: 57,
          ftpWatts: 280,
          vo2max: 54,
          hrvBandMs: { low: 43, high: 57 },
          restingHeartRateBpm: 45,
          bloodPressure: { systolic: 108, diastolic: 68 },
          fitnessAge: 48,
        },
      },
      {
        id: '22222222-2222-4222-8222-222222222222',
        userId: '11111111-1111-4111-8111-111111111111',
        section: 'data_quality_rules',
        version: 1,
        isActive: true,
        source: 'seed',
        updatedByProfileId: null,
        content: {
          rules: [
            {
              id: 'no_lr_balance',
              summary: 'Ignore left/right power balance.',
              reason: 'Single-sided meter doubles one leg and makes balance unusable.',
            },
          ],
        },
      },
      {
        id: '33333333-3333-4333-8333-333333333333',
        userId: '11111111-1111-4111-8111-111111111111',
        section: 'sleep_protocol',
        version: 1,
        isActive: true,
        source: 'seed',
        updatedByProfileId: null,
        content: {
          preCoolTemperatureC: 17,
          sealTargetTime: '22:00',
          thermalDisruptionThresholdC: { low: 19.5, high: 20.0 },
          coherenceBreathingTime: '20:00',
          bedtime: '23:15',
          latestSnackTime: '21:30',
        },
      },
      {
        id: '44444444-4444-4444-8444-444444444444',
        userId: '11111111-1111-4111-8111-111111111111',
        section: 'training_plan',
        version: 1,
        isActive: true,
        source: 'seed',
        updatedByProfileId: null,
        content: {
          framework: '13-week 2121',
          cycleStructure: ['Weeks 1-2 build', 'Week 3 recovery'],
          weeklyRhythm: ['Tuesday VO2 focus', 'Saturday long endurance ride'],
          constraints: ['Red days substitute recovery or rest and never keep VO2.'],
        },
      },
      {
        id: '55555555-5555-4555-8555-555555555555',
        userId: '11111111-1111-4111-8111-111111111111',
        section: 'training_schedule',
        version: 1,
        isActive: true,
        source: 'seed',
        updatedByProfileId: null,
        content: {
          restDays: ['Monday', 'Friday'],
          regularTrainingDays: {
            Tuesday: 'VO2 or higher-intensity bike focus',
            Saturday: 'Long endurance ride',
          },
        },
      },
      {
        id: '66666666-6666-4666-8666-666666666666',
        userId: '11111111-1111-4111-8111-111111111111',
        section: 'active_hypotheses',
        version: 1,
        isActive: true,
        source: 'seed',
        updatedByProfileId: null,
        content: {
          hypotheses: [
            {
              title: '04:00 waking',
              status: 'active',
              rule: 'Track thermal and routine drivers behind the 04:00 wake-up pattern.',
            },
          ],
        },
      },
      {
        id: '77777777-7777-4777-8777-777777777777',
        userId: '11111111-1111-4111-8111-111111111111',
        section: 'coaching_protocol',
        version: 1,
        isActive: true,
        source: 'seed',
        updatedByProfileId: null,
        content: {
          lowReadinessResponse: {
            rule: "When readiness is low, rearrange the week first rather than softening the prescription.",
          },
        },
      },
    ],
    planBlocks: [],
    plannedWorkouts: [
      {
        id: '88888888-8888-4888-8888-888888888888',
        userId: '11111111-1111-4111-8111-111111111111',
        planBlockId: null,
        workoutDate: '2026-07-15',
        version: 1,
        title: 'VO2 Builder',
        workoutType: 'bike_vo2',
        status: 'planned',
        isActive: true,
        plannedDurationMin: 60,
        intensityTarget: '115-120% FTP',
        structuredWorkout: { format: 'bike', steps: [] },
        source: 'seed',
      },
    ],
  },
  meta: { generatedAtUtc: '2026-07-15T09:30:00Z', seeded: true },
  errors: [],
};

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <CoachStatePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  apiFetchMock.mockReset();
});

describe('CoachStatePage', () => {
  it('shows a Mark-facing coach memory read for non-admin players', async () => {
    useAuthMock.mockReturnValue({
      player: {
        id: '11111111-1111-4111-8111-111111111111',
        displayName: 'Mark',
        role: 'player',
        timezone: 'Europe/London',
      },
    });
    apiFetchMock.mockResolvedValue(coachMemoryResponse);

    renderPage();

    expect(await screen.findByText('Coach memory')).toBeTruthy();
    expect(screen.getByText('What your coach knows about you')).toBeTruthy();
    expect(await screen.findByText('Profile facts')).toBeTruthy();
    expect(screen.getByText('FTP: 280 W')).toBeTruthy();
    expect(screen.getByText('Ignore left/right power balance.')).toBeTruthy();
    expect(screen.getByText('Normal recovery days: Monday and Friday.')).toBeTruthy();
    expect(screen.getByText('Low-readiness rule')).toBeTruthy();
    expect(screen.queryByText('Admin editor')).toBeNull();
    expect(screen.queryByRole('button', { name: /open editor/i })).toBeNull();
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/coach-memory');
  });

  it('keeps the raw editor behind an admin toggle', async () => {
    const user = userEvent.setup();
    useAuthMock.mockReturnValue({
      player: {
        id: '11111111-1111-4111-8111-111111111111',
        displayName: 'Craig',
        role: 'admin',
        timezone: 'Europe/London',
      },
    });
    apiFetchMock.mockImplementation((path: string) => {
      if (path === '/api/v1/coach-memory') return Promise.resolve(coachMemoryResponse);
      if (path === '/api/v1/admin/coaching-state') return Promise.resolve(coachMemoryResponse);
      throw new Error(`Unexpected path ${path}`);
    });

    renderPage();

    expect(await screen.findByRole('button', { name: /open editor/i })).toBeTruthy();
    expect(screen.queryByText('Admin editor')).toBeNull();

    await user.click(screen.getByRole('button', { name: /open editor/i }));

    expect(await screen.findByText('Admin editor')).toBeTruthy();
    expect(await screen.findByLabelText('Profile JSON editor')).toBeTruthy();
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/admin/coaching-state');
    });
  });
});
