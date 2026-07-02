import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { CheckInPage } from './CheckInPage';

const apiFetchMock = vi.fn();

vi.mock('@/lib/api', () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const snapshot = {
  data: {
    subjectDate: '2026-06-20',
    timezone: 'Europe/London',
    morningAnalysis: null,
    dailyMetrics: null,
    sleep: null,
    manualEntry: null,
    postWorkoutAnalyses: [],
    postFlexibilityAnalyses: [],
    plannedWorkouts: [],
    thermalState: {
      thermalReview: {},
      fan: { autoEnabled: true, mode: 'idle', isOn: false, speed: null, respondingToC: null },
    },
    dataQualityWarnings: [],
  },
  meta: { generatedAtUtc: '2026-06-20T06:40:00Z' },
  errors: [],
};

describe('CheckInPage', () => {
  it('saves the manual check-in', async () => {
    apiFetchMock.mockImplementation((path: string, options?: { method?: string }) => {
      if (options?.method === 'PUT') return Promise.resolve(snapshot);
      if (path === '/api/v1/daily-loop') return Promise.resolve(snapshot);
      return Promise.reject(new Error(`Unexpected request: ${path}`));
    });

    const queryClient = new QueryClient();
    const user = userEvent.setup();

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <CheckInPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await user.type(await screen.findByLabelText('Systolic'), '108');
    await user.click(screen.getByRole('button', { name: 'Save check-in' }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/daily-loop/2026-06-20/manual-entry',
        expect.objectContaining({ method: 'PUT' }),
      );
    });
  });
});
