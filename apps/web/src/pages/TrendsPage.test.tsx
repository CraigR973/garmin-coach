import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import type { DailyLoopEnvelope } from '@/hooks/useDailyLoop';
import { TrendsPage } from './TrendsPage';

const apiFetchMock = vi.fn();

vi.mock('@/lib/api', () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), message: vi.fn() },
}));

function metric(metricKey: string, label: string, current: number, prior: number, status: string) {
  const delta = status === 'ok' ? Math.round((current - prior) * 100) / 100 : null;
  return {
    metricKey,
    label,
    currentMean: current,
    priorMean: prior,
    delta,
    pctChange: status === 'ok' && prior !== 0 ? delta! / Math.abs(prior) : null,
    currentSampleCount: 6,
    priorSampleCount: status === 'ok' ? 6 : 0,
    status,
  };
}

function window_(key: string, label: string, sleep: number) {
  return {
    bucket: 'month' as const,
    key,
    label,
    start: `${key}-01`,
    end: `${key}-06`,
    sampleDays: 6,
    metrics: [
      metricSummary('sleep_score', 'Sleep score', sleep),
      metricSummary('readiness_score', 'Training readiness', 63),
      metricSummary('resting_hr_bpm', 'Resting HR (bpm)', 50),
    ],
  };
}

function metricSummary(metricKey: string, label: string, mean: number) {
  return { metricKey, label, sampleCount: 6, excludedCount: 0, mean, median: mean, min: mean, max: mean };
}

function envelope(status: 'ok' | 'insufficient_history', withNarrative: boolean) {
  return {
    data: {
      bucket: 'month',
      targetKey: '2026-07',
      subjectDate: '2026-07-01',
      yearOnYear: {
        bucket: 'month',
        status,
        currentKey: '2026-07',
        priorKey: '2025-07',
        currentLabel: 'July 2026',
        priorLabel: 'July 2025',
        metrics: [
          metric('sleep_score', 'Sleep score', 72, 60, status === 'ok' ? 'ok' : 'insufficient_history'),
        ],
        reasons: status === 'ok' ? [] : ['No prior-year window (July 2025) with ≥5 samples yet.'],
      },
      recentWindows: [window_('2026-07', 'July 2026', 72)],
      status,
      narrative: withNarrative
        ? {
            generatedAtUtc: '2026-07-15T18:00:00Z',
            modelName: 'claude-sonnet-4-6',
            promptVersion: 'trends-month-v1',
            markdown: '**Year-on-year**\n- Sleep up 12 points vs last July.',
          }
        : null,
    },
    meta: { generatedAtUtc: '2026-07-15T18:00:00Z' },
    errors: [],
  };
}

const dailyLoopEnvelope: DailyLoopEnvelope = {
  data: {
    subjectDate: '2026-07-15',
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
    hostedTtsConsent: false,
    holiday: { isActive: false, activeWindow: null },
    thermalState: {
      latestTemperatureC: null,
      targetTemperatureC: null,
      capturedAtUtc: null,
      overnightLowC: null,
      overnightWindMaxMph: null,
      overnightWindGustMph: null,
      thermalReview: {},
      fans: [],
    },
    walkingBrief: {
      asOfDate: '2026-07-15',
      trend: 'building',
      trendReason: 'Deliberate walks are becoming a steadier part of the last month.',
      window4w: {
        sessionCount: 6,
        totalDistanceM: 18500,
        totalDurationMin: 250,
        sessionsPerWeek: 1.5,
      },
      window12w: {
        sessionCount: 18,
        totalDistanceM: 54000,
        totalDurationMin: 750,
        sessionsPerWeek: 1.5,
      },
      recentSessions: [],
    },
    dataQualityWarnings: [],
  },
  meta: { generatedAtUtc: '2026-07-15T18:00:00Z' },
  errors: [],
};

describe('TrendsPage', () => {
  it('renders year-on-year deltas and generates a narrative', async () => {
    apiFetchMock.mockImplementation((path: string, options?: { method?: string }) => {
      if (options?.method === 'POST' && path === '/api/v1/trends/narrative/run?bucket=month') {
        return Promise.resolve(envelope('ok', true));
      }
      if (path === '/api/v1/trends/narrative?bucket=month') {
        return Promise.resolve(envelope('ok', false));
      }
      if (path === '/api/v1/daily-loop') {
        return Promise.resolve(dailyLoopEnvelope);
      }
      return Promise.reject(new Error(`Unexpected request: ${path}`));
    });

    const queryClient = new QueryClient();
    const user = userEvent.setup();

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <TrendsPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText('July 2026 vs July 2025')).toBeTruthy();
    expect(screen.getAllByText('Walking base')).toHaveLength(2);
    expect(screen.getByText(/6 walks · 18.5 km · 250 min/i)).toBeTruthy();
    expect(screen.getByText(/No summary written/)).toBeTruthy();

    await user.click(screen.getByRole('button', { name: 'Write summary' }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/trends/narrative/run?bucket=month',
        expect.objectContaining({ method: 'POST' }),
      );
    });

    expect(await screen.findByText(/Sleep up 12 points vs last July/)).toBeTruthy();
  });

  it('shows insufficient history and disables generation', async () => {
    apiFetchMock.mockImplementation((path: string) => {
      if (path === '/api/v1/trends/narrative?bucket=month') {
        return Promise.resolve(envelope('insufficient_history', false));
      }
      if (path === '/api/v1/daily-loop') {
        return Promise.resolve(dailyLoopEnvelope);
      }
      return Promise.reject(new Error(`Unexpected request: ${path}`));
    });

    const queryClient = new QueryClient();

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <TrendsPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText(/No prior-year window/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Write summary' })).toHaveProperty('disabled', true);
  });
});
