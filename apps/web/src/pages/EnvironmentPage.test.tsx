import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { DailyLoopEnvelope } from '@/hooks/useDailyLoop';
import { EnvironmentPage } from './EnvironmentPage';

const apiFetchMock = vi.fn();

vi.mock('@/lib/api', () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const snapshot: DailyLoopEnvelope = {
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
      latestTemperatureC: 17.4,
      targetTemperatureC: 17,
      capturedAtUtc: '2026-06-20T06:25:00Z',
      overnightLowC: 11.2,
      overnightWindMaxMph: 12,
      overnightWindGustMph: 18,
      thermalReview: {},
      fans: [
        {
          id: 'fan-bedroom',
          label: 'Bedroom fan',
          model: 'DR-HPF008S',
          autoEnabled: true,
          autoTarget: true,
          mode: 'control',
          isOn: true,
          speed: 5,
          oscillating: true,
          presetMode: 'normal',
          respondingToC: 20.1,
        },
      ],
    },
    dataQualityWarnings: [],
  },
  meta: { generatedAtUtc: '2026-06-20T06:40:00Z' },
  errors: [],
};

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
    summary: {
      minTempC: 19,
      maxTempC: 21,
      fanRanMinutes: 210,
      peakSpeed: 5,
      warningMinutes: 210,
      criticalMinutes: 60,
      roomVerdict: 'red',
    },
    nights: ['2026-06-19'],
  },
  meta: { generatedAtUtc: '2026-06-20T08:05:00Z' },
  errors: [],
};

function renderWithQuery(ui: ReactNode) {
  apiFetchMock.mockImplementation((path: string) =>
    Promise.resolve(path.startsWith('/api/v1/bedroom/overnight') ? overnightSnapshot : snapshot),
  );

  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  apiFetchMock.mockClear();
});

describe('EnvironmentPage', () => {
  it('renders the climate controls and links last night back to Sleep', async () => {
    renderWithQuery(
      <Routes>
        <Route path="/" element={<EnvironmentPage />} />
        <Route path="/sleep" element={<div>Sleep page</div>} />
      </Routes>,
    );

    expect(await screen.findByText('Bedroom climate')).toBeTruthy();
    expect(screen.getByRole('switch', { name: /overnight fan autopilot/i })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Low' })).toBeTruthy();
    expect(screen.queryByText('Overnight room & fan')).toBeNull();
    expect(screen.getByRole('link', { name: /review last night in sleep/i })).toBeTruthy();
  });

  it('drives the fan with a manual speed preset', async () => {
    const user = userEvent.setup();
    renderWithQuery(<EnvironmentPage />);

    await user.click(await screen.findByRole('button', { name: 'Low' }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/fan/command',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ fanId: 'fan-bedroom', power: true, speed: 3 }),
        }),
      );
    });
  });
});
