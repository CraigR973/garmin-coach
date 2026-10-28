import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MEMORY_ASK_NO, MEMORY_ASK_SEE_ALL, MEMORY_ASK_TITLE, MEMORY_ASK_YES } from '@/lib/coachMemory';
import { CoachMemoryAskCard } from './CoachMemoryAskCard';

const apiFetchMock = vi.fn();

vi.mock('@/lib/api', () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

function proposal(index: number, overrides: Record<string, unknown> = {}) {
  return {
    id: `9999999${index}-9999-4999-8999-999999999999`,
    kind: 'fact',
    destination: 'learned_context',
    statement: `Mark does his bodyweight session every Saturday ${index}.`,
    evidence: [
      {
        sourceId: `chat:${index}`,
        sourceType: 'chat',
        sourceDate: '2026-06-10',
        analysisId: null,
        analysisType: null,
        quote: 'I do my bodyweight session every Saturday',
      },
    ],
    status: 'pending',
    reviewedStatement: null,
    reviewedAtUtc: null,
    createdAtUtc: '2026-10-28T01:30:00Z',
    ...overrides,
  };
}

function envelope(proposals: ReturnType<typeof proposal>[]) {
  return {
    data: { createdCount: 0, proposals },
    meta: { generatedAtUtc: '2026-10-28T07:00:00Z' },
    errors: [],
  };
}

function renderCard() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <CoachMemoryAskCard />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  apiFetchMock.mockReset();
});

// Batch 346: what the coach proposed overnight, answered in one tap on Home.
describe('coach memory ask on Home', () => {
  it('asks about each waiting memory, with what he said and when', async () => {
    apiFetchMock.mockResolvedValue(envelope([proposal(1)]));
    renderCard();

    expect(await screen.findByText(MEMORY_ASK_TITLE)).toBeTruthy();
    expect(screen.getByText('Mark does his bodyweight session every Saturday 1.')).toBeTruthy();
    expect(screen.getByText('You said on 10 Jun: “I do my bodyweight session every Saturday”')).toBeTruthy();
    expect(screen.getByRole('link', { name: MEMORY_ASK_SEE_ALL }).getAttribute('href')).toBe('/coach-state');
  });

  it('remembers it in one tap', async () => {
    const user = userEvent.setup();
    apiFetchMock.mockImplementation((_path: string, options?: RequestInit) =>
      Promise.resolve(
        options?.method === 'PATCH'
          ? envelope([proposal(1, { status: 'accepted' })])
          : envelope([proposal(1)]),
      ),
    );
    renderCard();

    await user.click(await screen.findByRole('button', { name: MEMORY_ASK_YES }));

    await waitFor(() =>
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/coach-memory/learning/99999991-9999-4999-8999-999999999999',
        { method: 'PATCH', body: JSON.stringify({ decision: 'accept' }) },
      ),
    );
    await waitFor(() => expect(screen.queryByText(MEMORY_ASK_TITLE)).toBeNull());
  });

  it('leaves it out in one tap', async () => {
    const user = userEvent.setup();
    apiFetchMock.mockResolvedValue(envelope([proposal(1)]));
    renderCard();

    await user.click(await screen.findByRole('button', { name: MEMORY_ASK_NO }));

    await waitFor(() =>
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/coach-memory/learning/99999991-9999-4999-8999-999999999999',
        { method: 'PATCH', body: JSON.stringify({ decision: 'reject' }) },
      ),
    );
  });

  it('shows three at a time and says how many more wait', async () => {
    apiFetchMock.mockResolvedValue(envelope([1, 2, 3, 4, 5].map((index) => proposal(index))));
    renderCard();

    expect(await screen.findAllByRole('button', { name: MEMORY_ASK_YES })).toHaveLength(3);
    expect(screen.getByText('2 more are waiting on Coach memory.')).toBeTruthy();
  });

  it('shows nothing when nothing waits, for an experiment, or when the list fails', async () => {
    apiFetchMock.mockResolvedValue(
      envelope([
        proposal(1, { status: 'accepted' }),
        proposal(2, { kind: 'experiment', destination: 'experiments' }),
      ]),
    );
    const quiet = renderCard();
    await waitFor(() => expect(apiFetchMock).toHaveBeenCalled());
    expect(quiet.container.textContent).toBe('');
    quiet.unmount();

    apiFetchMock.mockReset();
    apiFetchMock.mockRejectedValue(new Error('offline'));
    const failed = renderCard();
    await waitFor(() => expect(apiFetchMock).toHaveBeenCalled());
    expect(failed.container.textContent).toBe('');
  });
});
