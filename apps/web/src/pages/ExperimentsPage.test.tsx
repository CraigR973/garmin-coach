import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { ExperimentsPage } from './ExperimentsPage';

const apiFetchMock = vi.fn();

vi.mock('@/lib/api', () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), message: vi.fn() },
}));

const EXPERIMENT_ID = '11111111-1111-4111-8111-111111111111';

function listEnvelope() {
  return {
    data: [
      {
        id: EXPERIMENT_ID,
        title: 'Collagen reintroduction',
        hypothesis: 'Reintroducing collagen disrupts sleep.',
        status: 'active',
        startDate: null,
        endDate: null,
        successCriteria: { slug: 'collagen' },
        observations: { entries: [] },
      },
    ],
    meta: { generatedAtUtc: '2026-06-30T18:00:00Z' },
    errors: [],
  };
}

function evaluationEnvelope() {
  return {
    data: {
      experimentId: EXPERIMENT_ID,
      title: 'Collagen reintroduction',
      status: 'active',
      slug: 'collagen',
      kind: 'gate',
      evaluationStatus: 'ok',
      recommendation: 'supported',
      sampleCount: 10,
      windowStart: '2026-06-21',
      windowEnd: '2026-06-30',
      evidence: { currentStreak: 10, gateMet: true },
      reasons: ['10 consecutive nights at or above the age-adjusted floor of 74 — the gate is met.'],
      canConclude: true,
      stored: null,
    },
    meta: { generatedAtUtc: '2026-06-30T18:00:00Z' },
    errors: [],
  };
}

describe('ExperimentsPage', () => {
  it('evaluates an experiment and concludes on the recommendation', async () => {
    apiFetchMock.mockImplementation((path: string, options?: { method?: string }) => {
      if (path === '/api/v1/experiments' && !options?.method) {
        return Promise.resolve(listEnvelope());
      }
      if (path === `/api/v1/experiments/${EXPERIMENT_ID}/evaluate`) {
        return Promise.resolve(evaluationEnvelope());
      }
      if (path === `/api/v1/experiments/${EXPERIMENT_ID}/status` && options?.method === 'POST') {
        return Promise.resolve({ data: {}, meta: {}, errors: [] });
      }
      return Promise.reject(new Error(`Unexpected request: ${path}`));
    });

    const queryClient = new QueryClient();
    const user = userEvent.setup();

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <ExperimentsPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText('Collagen reintroduction')).toBeTruthy();

    await user.click(screen.getByRole('button', { name: /Evaluate evidence/ }));

    expect(await screen.findByText('supported')).toBeTruthy();
    expect(screen.getByText(/the gate is met/)).toBeTruthy();

    await user.click(screen.getByRole('button', { name: 'Conclude as supported' }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        `/api/v1/experiments/${EXPERIMENT_ID}/status`,
        expect.objectContaining({ method: 'POST' }),
      );
    });
  });
});
