import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { ReviewsPage } from './ReviewsPage';

const apiFetchMock = vi.fn();

vi.mock('@/lib/api', () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

function envelope(period: 'weekly' | 'monthly', withReview: boolean) {
  return {
    data: {
      period,
      periodStart: '2026-06-22',
      periodEnd: '2026-06-28',
      dayCount: 7,
      rollup: {
        sleep: {
          nights: 7,
          avgScore: 72.5,
          avgAgeAdjustedScore: 76.5,
          avgDurationMin: 450,
          avgDeepMin: 60,
          avgRemMin: 80,
          trend: 'increasing',
        },
        recovery: {
          days: 7,
          avgHrvMs: 52.1,
          avgReadiness: 63.4,
          avgRestingHrBpm: 48,
          avgBodyBatteryCharged: 70,
          trend: 'stable',
        },
        trainingLoad: {
          activityCount: 4,
          totalLoad: 320,
          totalDurationMin: 260,
          byType: { cycling: 300, strength_training: 20 },
        },
        adherence: { plannedCount: 5, capturedCount: 3, statusCounts: { completed: 3 } },
        verdicts: { green: 4, amber: 2, red: 1, total: 7 },
        thermal: { nights: 7, avgIndoorPeakC: 19.2, avgOvernightLowC: 9.1, disruptionNights: 1 },
      },
      strength: { trend: 'stable', sessions4w: 6, sessionsPerWeek4w: 1.5, sessions12w: 18 },
      insights: {
        ftpDriftStatus: 'rising',
        earlyWarningStatus: 'watch',
        earlyWarningFired: false,
      },
      review: withReview
        ? {
            generatedAtUtc: '2026-06-28T18:00:00Z',
            modelName: 'claude-sonnet-4-6',
            promptVersion: 'reviews-v1',
            markdown: '**Trends**\n- Sleep improving across the week.',
          }
        : null,
    },
    meta: { generatedAtUtc: '2026-06-28T18:00:00Z' },
    errors: [],
  };
}

describe('ReviewsPage', () => {
  it('renders the deterministic rollup and generates a narrative', async () => {
    apiFetchMock.mockImplementation((path: string, options?: { method?: string }) => {
      if (options?.method === 'POST' && path === '/api/v1/reviews/weekly/run') {
        return Promise.resolve(envelope('weekly', true));
      }
      if (path === '/api/v1/reviews/weekly') {
        return Promise.resolve(envelope('weekly', false));
      }
      return Promise.reject(new Error(`Unexpected request: ${path}`));
    });

    const queryClient = new QueryClient();
    const user = userEvent.setup();

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <ReviewsPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    // Deterministic rollup summary is shown first, with no narrative yet.
    expect(await screen.findByText('Sleep')).toBeTruthy();
    expect(screen.getByText('Recovery')).toBeTruthy();
    expect(screen.getByText(/No review has been generated/)).toBeTruthy();

    await user.click(screen.getByRole('button', { name: 'Generate review' }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/reviews/weekly/run',
        expect.objectContaining({ method: 'POST' }),
      );
    });

    expect(await screen.findByText(/Sleep improving across the week/)).toBeTruthy();
  });

  it('switches to the monthly period', async () => {
    apiFetchMock.mockImplementation((path: string) => {
      if (path === '/api/v1/reviews/weekly') return Promise.resolve(envelope('weekly', false));
      if (path === '/api/v1/reviews/monthly') return Promise.resolve(envelope('monthly', false));
      return Promise.reject(new Error(`Unexpected request: ${path}`));
    });

    const queryClient = new QueryClient();
    const user = userEvent.setup();

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <ReviewsPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await screen.findByText('Sleep');
    await user.click(screen.getByRole('tab', { name: 'Monthly' }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/reviews/monthly');
    });
  });
});
