import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { StructuredWorkoutSheet } from './StructuredWorkoutSheet';

function renderSheet(overrides: Partial<Parameters<typeof StructuredWorkoutSheet>[0]> = {}) {
  const onConfirm = vi.fn();
  render(
    <StructuredWorkoutSheet
      open
      mode="add"
      busy={false}
      onClose={vi.fn()}
      onConfirm={onConfirm}
      {...overrides}
    />,
  );
  return { onConfirm };
}

describe('StructuredWorkoutSheet (Batch 88 free-form editor)', () => {
  it('confirms the default warm-up → steady → cool-down segment list', async () => {
    const user = userEvent.setup();
    const { onConfirm } = renderSheet();

    // Preview reflects the running total (10 + 20 + 5) and no ramp warning.
    expect(screen.getByText('Total 35 min')).toBeTruthy();
    expect(screen.queryByText(/no warm-up/i)).toBeNull();

    await user.click(screen.getByRole('button', { name: /^add workout$/i }));
    expect(onConfirm).toHaveBeenCalledWith({
      delivery: 'indoor',
      segments: [
        { kind: 'ramp', durationMin: 10, startFtpPct: 45, endFtpPct: 75 },
        { kind: 'steady', durationMin: 20, ftpPct: 65 },
        { kind: 'ramp', durationMin: 5, startFtpPct: 75, endFtpPct: 45 },
      ],
    });
  });

  it('adds an interval segment in order', async () => {
    const user = userEvent.setup();
    const { onConfirm } = renderSheet();

    await user.click(screen.getByRole('button', { name: /^intervals$/i }));
    await user.click(screen.getByRole('button', { name: /^add workout$/i }));

    const payload = onConfirm.mock.calls[0][0];
    expect(payload.segments).toHaveLength(4);
    expect(payload.segments[3]).toEqual({
      kind: 'interval',
      repeats: 4,
      workMin: 4,
      workFtpPct: 110,
      recoverMin: 4,
      recoverFtpPct: 55,
    });
  });

  it('removes and reorders segments', async () => {
    const user = userEvent.setup();
    const { onConfirm } = renderSheet();

    // Remove the steady middle segment → warm-up then cool-down remain.
    await user.click(screen.getAllByRole('button', { name: 'Remove segment' })[1]);
    // Move the cool-down (now index 1) up so the order flips (index 0's Move up is disabled).
    await user.click(screen.getAllByRole('button', { name: 'Move up' })[1]);
    await user.click(screen.getByRole('button', { name: /^add workout$/i }));

    const payload = onConfirm.mock.calls[0][0];
    expect(payload.segments.map((s: { startFtpPct: number }) => s.startFtpPct)).toEqual([75, 45]);
  });

  it('warns but still allows submit when power is outside the 45–150% band', async () => {
    const user = userEvent.setup();
    const { onConfirm } = renderSheet();

    const steadyPower = screen.getByLabelText('%FTP');
    await user.clear(steadyPower);
    await user.type(steadyPower, '200');

    expect(screen.getByText(/power 200% FTP is outside the usual 45–150% band/i)).toBeTruthy();
    const submit = screen.getByRole('button', { name: /^add workout$/i });
    expect(submit.hasAttribute('disabled')).toBe(false);
    await user.click(submit);
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onConfirm.mock.calls[0][0].segments[1]).toMatchObject({ kind: 'steady', ftpPct: 200 });
  });

  it('warns about a missing warm-up ramp when the first segment is not a ramp', async () => {
    const user = userEvent.setup();
    renderSheet();

    // Flip the first segment's kind to steady → it no longer opens with a ramp.
    await user.click(screen.getAllByRole('button', { name: 'steady' })[0]);
    expect(screen.getByText(/no warm-up ramp/i)).toBeTruthy();
    expect(screen.getByRole('button', { name: /^add workout$/i }).hasAttribute('disabled')).toBe(
      false,
    );
  });

  it('blocks submit when a required field is cleared', async () => {
    const user = userEvent.setup();
    renderSheet();

    const steadyPower = screen.getByLabelText('%FTP');
    await user.clear(steadyPower);
    expect(screen.getByRole('button', { name: /^add workout$/i }).hasAttribute('disabled')).toBe(
      true,
    );
  });
});
