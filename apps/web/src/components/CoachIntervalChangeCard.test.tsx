import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { CoachIntervalChange } from '@coach/shared';
import { CoachIntervalChangeCard } from './CoachIntervalChangeCard';

const apiFetchMock = vi.fn();

vi.mock('@/lib/api', () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}));

const toastError = vi.fn();
vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: (...args: unknown[]) => toastError(...args) },
}));

const WORKOUT_ID = '1795a107-d43f-4985-a92e-f9f097842f28';

/** Mark's 2026-09-08 exchange, as the turn now carries it. */
const SEPTEMBER_EIGHTH: CoachIntervalChange = {
  status: 'proposed',
  plannedWorkoutId: WORKOUT_ID,
  plannedWorkoutVersion: 1,
  matchingSets: 2,
  current: {
    repeat: 10,
    work: { durationSec: 40, powerPct: 125, cadenceRpm: 95 },
    rest: { durationSec: 20, powerPct: 55 },
  },
  changeTo: {
    repeat: 10,
    work: { durationSec: 35, powerPct: 125, cadenceRpm: 95 },
    rest: { durationSec: 25, powerPct: 55 },
  },
  currentLabel: '10 × 40s/20s @ 125%/55%',
  changeToLabel: '10 × 35s/25s @ 125%/55%',
  heldConstant: ['Warm-up ramp 55→80%', 'Cool-down ramp'],
};

function renderCard(change: CoachIntervalChange) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <CoachIntervalChangeCard change={change} />
    </QueryClientProvider>,
  );
}

describe('CoachIntervalChangeCard', () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
    toastError.mockReset();
  });

  it('shows the numbers before the tap, not a promise about them', () => {
    renderCard(SEPTEMBER_EIGHTH);

    expect(screen.getByText('10 × 40s/20s @ 125%/55%')).toBeTruthy();
    expect(screen.getByText('10 × 35s/25s @ 125%/55%')).toBeTruthy();
    expect(screen.getByText(/2 matching sets/)).toBeTruthy();
    expect(screen.getByText(/Warm-up ramp 55→80%, Cool-down ramp/)).toBeTruthy();
  });

  it('confirms the agreed block through the interval-editor rail', async () => {
    apiFetchMock.mockResolvedValue({});
    renderCard(SEPTEMBER_EIGHTH);

    await userEvent.click(screen.getByRole('button', { name: /confirm & upload/i }));

    await waitFor(() => expect(apiFetchMock).toHaveBeenCalledTimes(1));
    const [url, init] = apiFetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(
      `/api/v1/workout-delivery/planned-workouts/${WORKOUT_ID}/interval-editor/approve`,
    );
    expect(init.method).toBe('POST');
    // The agreed 35/25 reaches the rail — the defect was that the unchanged
    // 40/20 did, twice, 88 seconds apart.
    expect(JSON.parse(String(init.body))).toEqual({
      block: {
        repeat: 10,
        work: { durationSec: 35, powerPct: 125, cadenceRpm: 95 },
        rest: { durationSec: 25, powerPct: 55 },
      },
    });
  });

  it('says what happened where he is standing, not on another screen', async () => {
    apiFetchMock.mockResolvedValue({});
    renderCard(SEPTEMBER_EIGHTH);

    await userEvent.click(screen.getByRole('button', { name: /confirm & upload/i }));

    expect(
      await screen.findByText(/today’s session is now 10 × 35s\/25s @ 125%\/55%/i),
    ).toBeTruthy();
    expect(screen.queryByRole('button', { name: /confirm & upload/i })).toBeNull();
  });

  it('keeps the card when the confirm fails, so the change is not lost', async () => {
    apiFetchMock.mockRejectedValue(new Error('Planned workout not found'));
    renderCard(SEPTEMBER_EIGHTH);

    await userEvent.click(screen.getByRole('button', { name: /confirm & upload/i }));

    await waitFor(() => expect(toastError).toHaveBeenCalledWith('Planned workout not found'));
    expect(screen.getByRole('button', { name: /confirm & upload/i })).toBeTruthy();
  });

  it('says plainly when an offer could not be carried, rather than showing a dead button', () => {
    renderCard({ status: 'unavailable', reason: 'out_of_range' });

    expect(
      screen.getByText(/outside what can be set on today’s session/i),
    ).toBeTruthy();
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('does not repeat an internal reason token to Mark', () => {
    renderCard({ status: 'unavailable', reason: 'not_editable' });

    expect(screen.queryByText(/not_editable/)).toBeNull();
    expect(screen.getByText(/no session to change today/i)).toBeTruthy();
  });
});
