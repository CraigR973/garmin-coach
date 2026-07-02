import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { DailyLoopEnvelope } from '@/hooks/useDailyLoop';
import { BedroomPage } from './BedroomPage';
import { MorningBriefPage } from './MorningBriefPage';

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
      outputMarkdown: '**Green light**\n\nRested and ready.',
      planAdjustments: ['Keep the scheduled ride.'],
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
    temperature: [
      { t: '2026-06-19T22:00:00Z', c: 20.4 },
      { t: '2026-06-20T02:00:00Z', c: 19.2 },
    ],
    fan: [
      {
        t: '2026-06-19T22:05:00Z',
        on: true,
        speed: 5,
        action: 'apply',
        reason: '20.4C -> speed 5',
        observedTempC: 20.4,
        autoEnabled: true,
      },
    ],
    sleep: {
      start: '2026-06-19T22:30:00Z',
      end: '2026-06-20T06:30:00Z',
      score: 78,
      ageAdjustedScore: 82,
      durationSec: 28800,
      awakeSec: 900,
      restlessMoments: 12,
      stages: [{ start: '2026-06-19T22:30:00Z', end: '2026-06-19T23:30:00Z', stage: 'light' }],
    },
    summary: {
      minTempC: 19.2,
      maxTempC: 20.4,
      fanRanMinutes: 15,
      peakSpeed: 5,
      warningMinutes: 15,
      criticalMinutes: 15,
      roomVerdict: 'amber',
    },
    nights: ['2026-06-19', '2026-06-18'],
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

describe('daily detail pages', () => {
  it('renders the full morning brief page', async () => {
    renderWithQuery(<MorningBriefPage />);
    expect(await screen.findByText('Coach read')).toBeTruthy();
    expect(screen.getByText('Green light')).toBeTruthy();
  });

  it('renders the bedroom detail page', async () => {
    renderWithQuery(<BedroomPage />);
    expect(await screen.findByText('Bedroom climate')).toBeTruthy();
    expect(screen.getByText('17.4°C')).toBeTruthy();
    expect(screen.getByText('12 mph')).toBeTruthy();
  });

  it('renders the overnight chart card with a night pager', async () => {
    renderWithQuery(<BedroomPage />);
    expect(await screen.findByText('Overnight room & fan')).toBeTruthy();
    expect((await screen.findByTestId('overnight-room-verdict-badge')).textContent).toBe('Amber');
    expect(await screen.findByTestId('overnight-chart')).toBeTruthy();
    // Pager: at the newest night, "Next night" is disabled; "Previous night" is live.
    expect(screen.getByRole('button', { name: 'Next night' })).toHaveProperty('disabled', true);
    expect(screen.getByRole('button', { name: 'Previous night' })).toHaveProperty('disabled', false);
  });
});

describe('bedroom fan controls', () => {
  it('shows the autopilot status and a switch reflecting the current setting', async () => {
    renderWithQuery(<BedroomPage />);
    expect(await screen.findByText('Bedroom fan')).toBeTruthy();
    expect(screen.getByText('Auto · on at speed 5, responding to 20.1°C')).toBeTruthy();
    expect(screen.getByRole('switch', { name: /overnight fan autopilot/i }).getAttribute('aria-checked')).toBe(
      'true',
    );
  });

  it('turns the overnight autopilot off', async () => {
    const user = userEvent.setup();
    renderWithQuery(<BedroomPage />);
    await user.click(await screen.findByRole('switch', { name: /overnight fan autopilot/i }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/fan/auto',
        expect.objectContaining({ method: 'PUT', body: JSON.stringify({ enabled: false }) }),
      );
    });
  });

  it('drives the fan with a manual speed preset', async () => {
    const user = userEvent.setup();
    renderWithQuery(<BedroomPage />);
    await user.click(await screen.findByRole('button', { name: 'Low' }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/fan/command',
        expect.objectContaining({ method: 'POST', body: JSON.stringify({ power: true, speed: 3 }) }),
      );
    });
  });

  it('turns the fan off with the manual control', async () => {
    const user = userEvent.setup();
    renderWithQuery(<BedroomPage />);
    await user.click(await screen.findByRole('button', { name: 'Turn off' }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/fan/command',
        expect.objectContaining({ method: 'POST', body: JSON.stringify({ power: false }) }),
      );
    });
  });
});
