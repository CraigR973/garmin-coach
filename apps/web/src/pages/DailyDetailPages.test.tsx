import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import type { DailyLoopEnvelope } from '@/hooks/useDailyLoop';
import { BaselinesPage } from './BaselinesPage';
import { BedroomPage } from './BedroomPage';
import { MorningBriefPage } from './MorningBriefPage';

const apiFetchMock = vi.fn();

vi.mock('@/lib/api', () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
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
    },
    dataQualityWarnings: [],
  },
  meta: {
    generatedAtUtc: '2026-06-20T06:40:00Z',
  },
  errors: [],
};

function renderWithQuery(ui: ReactNode) {
  apiFetchMock.mockResolvedValue(snapshot);
  const queryClient = new QueryClient();

  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('daily detail pages', () => {
  it('renders the full morning brief page', async () => {
    renderWithQuery(<MorningBriefPage />);
    expect(await screen.findByText('Coach read')).toBeTruthy();
    expect(screen.getByText('Green light')).toBeTruthy();
  });

  it('renders the baselines detail page', async () => {
    renderWithQuery(<BaselinesPage />);
    expect(await screen.findByText('Metrics vs your baselines')).toBeTruthy();
    expect(screen.getByText('HRV (7-day)')).toBeTruthy();
  });

  it('renders the bedroom detail page', async () => {
    renderWithQuery(<BedroomPage />);
    expect(await screen.findByText('Bedroom climate')).toBeTruthy();
    expect(screen.getByText('17.4°C')).toBeTruthy();
    expect(screen.getByText('12 mph')).toBeTruthy();
  });
});
