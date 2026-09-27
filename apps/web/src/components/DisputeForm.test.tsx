import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { DisputeForm } from './DisputeForm';
import { ProvenancePanel } from './ProvenancePanel';
import { FIGURE_CONTEST_COPY } from '@/lib/disputes';

const apiFetchMock = vi.fn();
vi.mock('@/lib/api', () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}));

const BEDROOM_PEAK = {
  figure: 'environment.thermalReview.indoorPeakC',
  label: 'bedroom peak overnight',
  value: 21.4,
  units: '°C',
  rule: 'the highest reading inside the window',
  window: { kind: 'night_fallback', startUtc: null, endUtc: null, label: null },
  sources: { rowsInWindow: 17, firstReadingUtc: '2026-09-08T13:07:00', lastReadingUtc: '2026-09-09T05:00:00' },
  threshold: { name: 'thermal disruption', comparedAgainst: 20, units: '°C', source: null },
};

describe('DisputeForm (Batch 274)', () => {
  it('stays a quiet link until wanted, then records the reason and says it changes nothing', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<DisputeForm copy={FIGURE_CONTEST_COPY} onSubmit={onSubmit} />);

    expect(screen.queryByRole('textbox')).toBeNull();
    await user.click(screen.getByRole('button', { name: 'This looks wrong' }));
    await user.click(screen.getByRole('button', { name: 'Send to Craig' }));
    expect(screen.getByText('Say what looks wrong first.')).toBeTruthy();
    expect(onSubmit).not.toHaveBeenCalled();

    await user.type(screen.getByRole('textbox'), '  That is from 14:07, not my night.  ');
    await user.click(screen.getByRole('button', { name: 'Send to Craig' }));

    expect(onSubmit).toHaveBeenCalledWith('That is from 14:07, not my night.');
    expect(await screen.findByText("Sent to Craig. It doesn't change the figure; he'll look into it.")).toBeTruthy();
  });

  it('keeps the reason and says so when it could not send', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn().mockRejectedValue(new Error('This figure has no working to contest.'));
    render(<DisputeForm copy={FIGURE_CONTEST_COPY} onSubmit={onSubmit} />);

    await user.click(screen.getByRole('button', { name: 'This looks wrong' }));
    await user.type(screen.getByRole('textbox'), 'Wrong.');
    await user.click(screen.getByRole('button', { name: 'Send to Craig' }));

    expect(await screen.findByText('This figure has no working to contest.')).toBeTruthy();
    expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('Wrong.');
  });
});

describe('ProvenancePanel contest (Batch 274)', () => {
  it('sends the read, the figure and his reason, and nothing else', async () => {
    const user = userEvent.setup();
    apiFetchMock.mockResolvedValue({
      data: {
        id: '77777777-7777-4777-8777-777777777777',
        kind: 'figure',
        analysisId: '22222222-2222-4222-8222-222222222222',
        subjectDate: '2026-09-09',
        figure: 'environment.thermalReview.indoorPeakC',
        label: 'bedroom peak overnight',
        verdict: null,
        reason: 'Not my night.',
        createdAtUtc: '2026-09-09T08:00:00Z',
      },
      meta: { generatedAtUtc: '2026-09-09T08:00:00Z' },
      errors: [],
    });
    render(
      <ProvenancePanel
        sources={[[BEDROOM_PEAK]]}
        timeZone="Europe/London"
        analysisId="22222222-2222-4222-8222-222222222222"
      />,
    );

    await user.click(screen.getByText('How these numbers were worked out'));
    await user.click(screen.getByText('Bedroom peak overnight — 21.4 °C'));
    await user.click(screen.getByRole('button', { name: 'This looks wrong' }));
    await user.type(screen.getByRole('textbox'), 'Not my night.');
    await user.click(screen.getByRole('button', { name: 'Send to Craig' }));

    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/disputes/figures', {
      method: 'POST',
      body: JSON.stringify({
        analysisId: '22222222-2222-4222-8222-222222222222',
        figure: 'environment.thermalReview.indoorPeakC',
        reason: 'Not my night.',
      }),
    });
  });

  it('only explains when it has no read to attach a contest to', () => {
    render(<ProvenancePanel sources={[[BEDROOM_PEAK]]} timeZone="Europe/London" />);
    expect(screen.queryByRole('button', { name: 'This looks wrong' })).toBeNull();
  });
});
