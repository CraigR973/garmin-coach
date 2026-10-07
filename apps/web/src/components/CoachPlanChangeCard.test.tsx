import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { CoachPlanChange } from '@coach/shared';
import { APPLIED, APPLY, OFFER_HEADING, SEE_PLAN } from '@/lib/planChanges';
import { CoachPlanChangeCard } from './CoachPlanChangeCard';

const apiFetchMock = vi.fn();

vi.mock('@/lib/api', () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}));

const MESSAGE_ID = '00000000-0000-4000-8000-000000000324';
const SUMMARY = 'Sat 31 Oct, Z2 + Neuromuscular: removed.';
const STALE =
  "The plan has changed since the coach suggested this, so it hasn't been applied. Ask the coach again.";

const proposed: CoachPlanChange = {
  status: 'proposed',
  change: { kind: 'remove', session: 's012' },
  summary: SUMMARY,
  planName: 'Plan No. 3',
  generatedAtUtc: '2026-10-07T07:00:00',
  revision: 0,
};

function renderCard(change: CoachPlanChange) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <CoachPlanChangeCard messageId={MESSAGE_ID} change={change} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('CoachPlanChangeCard', () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
  });

  it('shows the change in words and applies it with one tap', async () => {
    const user = userEvent.setup();
    apiFetchMock.mockResolvedValue({
      data: {
        id: MESSAGE_ID,
        analysisId: null,
        role: 'assistant',
        content: 'Drop the ride?',
        proposedPlanChange: {
          ...proposed,
          status: 'applied',
          appliedAtUtc: '2026-10-10T09:00:00',
          appliedRevision: 1,
        },
        createdAtUtc: '2026-10-10T09:00:00Z',
      },
      meta: { generatedAtUtc: '2026-10-10T09:00:00Z' },
      errors: [],
    });
    renderCard(proposed);

    expect(screen.getByText(OFFER_HEADING)).toBeTruthy();
    expect(screen.getByText(SUMMARY)).toBeTruthy();
    await user.click(screen.getByRole('button', { name: APPLY }));

    expect(await screen.findByText(APPLIED, { exact: false })).toBeTruthy();
    expect(apiFetchMock).toHaveBeenCalledWith(
      `/api/v1/coach/messages/${MESSAGE_ID}/apply-plan-change`,
      expect.objectContaining({ method: 'POST' }),
    );
    expect(screen.getByRole('link', { name: SEE_PLAN }).getAttribute('href')).toBe('/builder');
  });

  it('shows the server’s words when the plan has moved on', async () => {
    const user = userEvent.setup();
    apiFetchMock.mockRejectedValue(new Error(STALE));
    renderCard(proposed);

    await user.click(screen.getByRole('button', { name: APPLY }));

    expect(await screen.findByText(STALE)).toBeTruthy();
    expect(screen.queryByRole('button', { name: APPLY })).toBeNull();
  });

  it('says plainly when an offer was stale or could not be made', () => {
    const { unmount } = renderCard({ status: 'stale', words: STALE });
    expect(screen.getByText(STALE)).toBeTruthy();
    expect(screen.queryByRole('button', { name: APPLY })).toBeNull();
    unmount();

    renderCard({
      status: 'unavailable',
      reason: 'not_found',
      words: "That session isn't in the plan any more.",
    });
    expect(screen.getByText("That session isn't in the plan any more.")).toBeTruthy();
  });

  it('shows an applied offer as done', () => {
    renderCard({
      ...proposed,
      status: 'applied',
      appliedAtUtc: '2026-10-10T09:00:00',
      appliedRevision: 1,
    });
    expect(screen.getByText(APPLIED, { exact: false })).toBeTruthy();
    expect(screen.queryByRole('button', { name: APPLY })).toBeNull();
  });
});
