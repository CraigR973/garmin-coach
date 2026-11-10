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

function evaluationEnvelope(overrides: Record<string, unknown> = {}) {
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
      reasons: [
        '10 consecutive nights at or above the age-adjusted floor of 74 (gate: 7) — the gate is met.',
        'Recent age-adjusted sleep trend is rising (0.40/night).',
      ],
      canConclude: true,
      plain: {
        outcomeLabel: 'supported',
        summary:
          'Your age-adjusted sleep score has stayed at or above 74 for 10 nights in a row, which meets the 7-night target.',
        details: [
          { label: 'Nights in a row at or above 74', value: '10' },
          { label: 'Target', value: '7 nights in a row' },
        ],
      },
      stored: null,
      ...overrides,
    },
    meta: { generatedAtUtc: '2026-06-30T18:00:00Z' },
    errors: [],
  };
}

async function renderAndEvaluate(envelope: ReturnType<typeof evaluationEnvelope>) {
  apiFetchMock.mockImplementation((path: string, options?: { method?: string }) => {
    if (path === '/api/v1/experiments' && !options?.method) {
      return Promise.resolve(listEnvelope());
    }
    if (path === `/api/v1/experiments/${EXPERIMENT_ID}/evaluate`) {
      return Promise.resolve(envelope);
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
  return user;
}

describe('ExperimentsPage', () => {
  it('evaluates an experiment, reads it in plain words and concludes on the recommendation', async () => {
    const user = await renderAndEvaluate(evaluationEnvelope());

    expect(await screen.findByText('supported')).toBeTruthy();
    expect(screen.getByText(/which meets the 7-night target/)).toBeTruthy();
    // The coach's technical reasons are never rendered (Batch 385).
    expect(screen.queryByText(/age-adjusted floor/)).toBeNull();
    expect(screen.queryByText(/\(0\.40\/night\)/)).toBeNull();
    expect(screen.getByText(/Based on 10 nights/)).toBeTruthy();

    await user.click(screen.getByRole('button', { name: 'Conclude as supported' }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        `/api/v1/experiments/${EXPERIMENT_ID}/status`,
        expect.objectContaining({ method: 'POST' }),
      );
    });
  });

  it('keeps the figures behind a disclosure, in plain labels', async () => {
    await renderAndEvaluate(evaluationEnvelope());

    expect(await screen.findByText('Show the figures')).toBeTruthy();
    expect(screen.getByText('Nights in a row at or above 74')).toBeTruthy();
    expect(screen.getByText('7 nights in a row')).toBeTruthy();
  });

  it('shows no sentence and no technical line when a figure is missing', async () => {
    await renderAndEvaluate(
      evaluationEnvelope({
        recommendation: 'inconclusive',
        plain: { outcomeLabel: 'inconclusive', summary: null, details: [] },
      }),
    );

    expect(await screen.findByText('inconclusive')).toBeTruthy();
    expect(screen.queryByText(/the gate is met/)).toBeNull();
    expect(screen.queryByText(/age-adjusted floor/)).toBeNull();
    expect(screen.queryByText('Show the figures')).toBeNull();
  });

  it('says "too early to tell" rather than the status key', async () => {
    await renderAndEvaluate(
      evaluationEnvelope({
        evaluationStatus: 'insufficient_history',
        recommendation: null,
        sampleCount: 3,
        canConclude: false,
        reasons: ['Only 3 scored nights; need ≥5 to judge the gate.'],
        plain: {
          outcomeLabel: 'too early to tell',
          summary: 'I have only 3 nights I can compare so far, which is too few to judge.',
          details: [],
        },
      }),
    );

    expect(await screen.findByText('too early to tell')).toBeTruthy();
    expect(screen.queryByText(/insufficient_history/)).toBeNull();
    expect(screen.queryByText(/need ≥5/)).toBeNull();
    expect(screen.getByText(/too few to judge/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Conclude/ })).toBeNull();
  });

  it('shows nothing from an older API that has no plain block', async () => {
    const envelope = evaluationEnvelope();
    delete (envelope.data as { plain?: unknown }).plain;
    await renderAndEvaluate(envelope);

    expect(await screen.findByText('supported')).toBeTruthy();
    expect(screen.queryByText(/age-adjusted floor/)).toBeNull();
  });
});
