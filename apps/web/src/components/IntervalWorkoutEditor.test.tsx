import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { IntervalWorkoutEditor } from './IntervalWorkoutEditor';

const apiFetchMock = vi.fn();

vi.mock('@/lib/api', () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const WORKOUT_ID = '55555555-5555-4555-8555-555555555555';
const editorEnvelope = {
  data: {
    plannedWorkoutId: WORKOUT_ID,
    current: {
      repeat: 5,
      work: { durationSec: 120, powerPct: 120, cadenceRpm: 95 },
      rest: { durationSec: 120, powerPct: 60, cadenceRpm: null },
    },
    changeTo: {
      repeat: 5,
      work: { durationSec: 90, powerPct: 108, cadenceRpm: 95 },
      rest: { durationSec: 90, powerPct: 54, cadenceRpm: null },
    },
    presets: {
      keep: {
        repeat: 5,
        work: { durationSec: 120, powerPct: 120, cadenceRpm: 95 },
        rest: { durationSec: 120, powerPct: 60, cadenceRpm: null },
      },
      scale: {
        repeat: 5,
        work: { durationSec: 90, powerPct: 108, cadenceRpm: 95 },
        rest: { durationSec: 90, powerPct: 54, cadenceRpm: null },
      },
      sweetSpot: {
        repeat: 3,
        work: { durationSec: 600, powerPct: 90, cadenceRpm: 95 },
        rest: { durationSec: 300, powerPct: 55, cadenceRpm: 75 },
      },
      zoneTwo: {
        repeat: 1,
        work: { durationSec: 2700, powerPct: 65, cadenceRpm: 95 },
        rest: { durationSec: 0, powerPct: 55, cadenceRpm: null },
      },
    },
    fixedSteps: [
      { index: 0, label: 'Warm-up ramp', role: 'warmup' },
      { index: 1, label: 'Primer', role: 'primer' },
      { index: 5, label: 'Cool-down ramp', role: 'cooldown' },
    ],
  },
  meta: { generatedAtUtc: '2026-07-24T13:00:00Z' },
  errors: [],
};

function renderEditor() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <IntervalWorkoutEditor workoutId={WORKOUT_ID} onApproved={vi.fn()} />
    </QueryClientProvider>,
  );
}

describe('IntervalWorkoutEditor', () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
    apiFetchMock.mockResolvedValue(editorEnvelope);
  });

  it('renders interval settings without the old mobile horizontal table', async () => {
    const { container } = renderEditor();

    expect(await screen.findByRole('region', { name: 'Per-interval workout editor' })).toBeTruthy();
    expect(screen.getByLabelText('Change to number of intervals')).toBeTruthy();
    expect(screen.getByLabelText('Change to rest seconds')).toBeTruthy();
    expect(container.querySelector('.overflow-x-auto')).toBeNull();
    expect(container.textContent).toContain('Current');
    expect(container.textContent).toContain('Change to');
  });

  it('keeps every editable field reachable when the Z2 preset has zero rest', async () => {
    const user = userEvent.setup();
    renderEditor();

    await user.click(await screen.findByRole('button', { name: /z2/i }));

    await waitFor(() => {
      expect((screen.getByLabelText('Change to rest minutes') as HTMLInputElement).value).toBe('0');
      expect((screen.getByLabelText('Change to rest seconds') as HTMLInputElement).value).toBe('00');
    });

    await user.clear(screen.getByLabelText('Change to rest seconds'));
    await user.type(screen.getByLabelText('Change to rest seconds'), '15');
    await user.click(screen.getByRole('button', { name: /approve & upload/i }));

    await waitFor(() => {
      const call = apiFetchMock.mock.calls.find(
        ([path, options]) =>
          path === `/api/v1/workout-delivery/planned-workouts/${WORKOUT_ID}/interval-editor/approve` &&
          options?.method === 'POST',
      );
      expect(call).toBeTruthy();
      expect(JSON.parse(call![1].body).block.rest.durationSec).toBe(15);
    });
  });

  // Batch 215: on 2026-08-08 the brief told Mark to cut to 22 minutes and this
  // editor opened pre-filled at 37, because the default preset was always the
  // Amber "Scale down". The verdict's own adjustment is now the default.
  const redEnvelope = {
    ...editorEnvelope,
    data: {
      ...editorEnvelope.data,
      adjustmentVerdict: 'Red',
      changeTo: {
        repeat: 1,
        work: { durationSec: 1695, powerPct: 62, cadenceRpm: 85 },
        rest: { durationSec: 0, powerPct: 55, cadenceRpm: null },
      },
      presets: {
        ...editorEnvelope.data.presets,
        todaysAdjustment: {
          repeat: 1,
          work: { durationSec: 1695, powerPct: 62, cadenceRpm: 85 },
          rest: { durationSec: 0, powerPct: 55, cadenceRpm: null },
        },
      },
    },
  };

  it("defaults to today's adjustment and names the verdict it came from", async () => {
    apiFetchMock.mockResolvedValue(redEnvelope);
    const { container } = renderEditor();

    const todays = await screen.findByRole('button', { name: /today’s adjustment/i });
    expect(todays.getAttribute('aria-pressed')).toBe('true');
    expect(
      screen.getByRole('button', { name: /scale down/i }).getAttribute('aria-pressed'),
    ).toBe('false');
    expect(container.textContent).toContain('Red adjustment');
    // Pre-filled with the transform's block, not the generic Amber scale-down.
    expect((screen.getByLabelText('Change to work minutes') as HTMLInputElement).value).toBe('28');
    expect(
      (screen.getByLabelText('Change to work percent FTP') as HTMLInputElement).value,
    ).toBe('62');
  });

  it('falls back to Scale down when the morning made no adjustment', async () => {
    const { container } = renderEditor();

    const scale = await screen.findByRole('button', { name: /scale down/i });
    expect(scale.getAttribute('aria-pressed')).toBe('true');
    expect(screen.queryByRole('button', { name: /today’s adjustment/i })).toBeNull();
    expect(container.textContent).not.toContain('adjustment — the same change');
  });
});
