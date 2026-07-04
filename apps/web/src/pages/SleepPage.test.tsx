import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Navigate, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { DailyLoopEnvelope } from '@/hooks/useDailyLoop';
import { SleepPage } from './SleepPage';

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
    morningAnalysis: {
      id: '22222222-2222-4222-8222-222222222222',
      generatedAtUtc: '2026-06-20T06:35:00Z',
      verdict: 'green',
      promptVersion: 'morning-v1',
      modelName: 'claude-sonnet-4-6',
      outputMarkdown: '**Green light**',
      planAdjustments: [],
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
      ageComparison: { rows: [] },
    },
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
      fan: { autoEnabled: true, mode: 'control', isOn: true, speed: 5, respondingToC: 20.1 },
    },
    sleepProjection: {
      status: 'personalized',
      tone: 'protect',
      headline: "Protect tonight's wind-down",
      summary: 'A late hard session plus a warm room may make sleep more fragile.',
      evidence: ['Latest session started 18:05.'],
      prepActions: ['Bring the wind-down forward.'],
      protocol: {
        preCoolTemperatureC: 17,
        coherenceBreathingTime: '20:00',
        latestSnackTime: '21:30',
        sealTargetTime: '22:00',
        bedtime: '23:15',
      },
    },
    dataQualityWarnings: [],
  },
  meta: {
    generatedAtUtc: '2026-06-20T06:40:00Z',
  },
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

describe('SleepPage', () => {
  it('renders the Last night view with the metrics table and overnight chart', async () => {
    renderWithQuery(<SleepPage />);

    expect(await screen.findByText("Last night's sleep")).toBeTruthy();
    expect(screen.getByText('Overnight room & fan')).toBeTruthy();
    expect((await screen.findByTestId('overnight-room-verdict-badge')).textContent).toBe('Red');
  });

  it('switches to the Tonight view with the sleep projection and fan controls', async () => {
    const user = userEvent.setup();
    renderWithQuery(<SleepPage />);

    await screen.findByText("Last night's sleep");
    await user.click(screen.getByRole('tab', { name: 'Tonight' }));

    expect(await screen.findByText("Protect tonight's wind-down")).toBeTruthy();
    expect(screen.getByText(/late hard session/)).toBeTruthy();
    expect(screen.getByRole('switch', { name: /overnight fan autopilot/i })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Low' })).toBeTruthy();
  });

  it('drives the fan with a manual speed preset from the Tonight view', async () => {
    const user = userEvent.setup();
    renderWithQuery(<SleepPage />);

    await user.click(await screen.findByRole('tab', { name: 'Tonight' }));
    await user.click(await screen.findByRole('button', { name: 'Low' }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/fan/command',
        expect.objectContaining({ method: 'POST', body: JSON.stringify({ power: true, speed: 3 }) }),
      );
    });
  });

  it('/bedroom redirects into /sleep', async () => {
    apiFetchMock.mockImplementation((path: string) =>
      Promise.resolve(path.startsWith('/api/v1/bedroom/overnight') ? overnightSnapshot : snapshot),
    );
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/bedroom']}>
          <Routes>
            <Route path="/sleep" element={<SleepPage />} />
            <Route path="/bedroom" element={<Navigate to="/sleep" replace />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Last night's sleep")).toBeTruthy();
  });

  it('renders the shared error state when the daily loop fails to load', async () => {
    apiFetchMock.mockImplementation((path: string) =>
      path === '/api/v1/daily-loop'
        ? Promise.reject(new Error('Network down'))
        : Promise.reject(new Error(`Unexpected request: ${path}`)),
    );
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <SleepPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Sleep data couldn't load")).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeTruthy();
  });
});
