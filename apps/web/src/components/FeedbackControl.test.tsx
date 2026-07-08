import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { FeedbackControl } from './FeedbackControl';

const apiFetchMock = vi.fn();

vi.mock('@/lib/api', () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

function renderControl(props: Parameters<typeof FeedbackControl>[0]) {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <FeedbackControl {...props} />
    </QueryClientProvider>,
  );
}

describe('FeedbackControl', () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
    apiFetchMock.mockResolvedValue(undefined);
  });

  it('renders the accuracy axis for a summary', () => {
    renderControl({ analysisId: 'a1', kind: 'summary' });
    expect(screen.getByRole('button', { name: 'Spot on' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'A bit off' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Way off' })).toBeTruthy();
  });

  it('renders the agreement axis for a suggestion', () => {
    renderControl({ analysisId: 'a1', kind: 'suggestion' });
    expect(screen.getByRole('button', { name: 'Agree' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Not for me' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Already doing' })).toBeTruthy();
  });

  it('saves a rating in one tap via PUT and shows no correction box for a positive tap', async () => {
    const user = userEvent.setup();
    renderControl({ analysisId: 'abc', kind: 'summary' });

    // No correction box until a negative tap.
    expect(screen.queryByLabelText('What did we get wrong?')).toBeNull();

    await user.click(screen.getByRole('button', { name: 'Spot on' }));

    await waitFor(() => expect(apiFetchMock).toHaveBeenCalledTimes(1));
    const [path, options] = apiFetchMock.mock.calls[0];
    expect(path).toBe('/api/v1/analyses/abc/feedback');
    expect(options.method).toBe('PUT');
    expect(JSON.parse(options.body)).toEqual({
      kind: 'summary',
      rating: 'spot_on',
      correctionText: null,
    });
    // A positive rating does not reveal the correction box.
    expect(screen.queryByLabelText('What did we get wrong?')).toBeNull();
  });

  it('reveals the correction box on a negative tap and sends the note', async () => {
    const user = userEvent.setup();
    renderControl({ analysisId: 'xyz', kind: 'summary' });

    await user.click(screen.getByRole('button', { name: 'Way off' }));
    const box = await screen.findByLabelText('What did we get wrong?');
    expect(box).toBeTruthy();

    await user.type(box, 'my watch missed my 03:00 wake');
    await user.click(screen.getByRole('button', { name: 'Save note' }));

    await waitFor(() => {
      const last = apiFetchMock.mock.calls.at(-1);
      expect(last).toBeTruthy();
      expect(JSON.parse(last![1].body)).toEqual({
        kind: 'summary',
        rating: 'way_off',
        correctionText: 'my watch missed my 03:00 wake',
      });
    });
  });

  it('pre-selects an existing rating and shows the saved correction', () => {
    renderControl({
      analysisId: 'a1',
      kind: 'summary',
      feedback: {
        id: 'f1',
        analysisId: 'a1',
        kind: 'summary',
        rating: 'a_bit_off',
        correctionText: 'slept better than it says',
        createdAtUtc: '2026-07-08T06:40:00Z',
      },
    });
    expect(screen.getByRole('button', { name: 'A bit off' }).getAttribute('aria-pressed')).toBe(
      'true',
    );
    expect((screen.getByLabelText('What did we get wrong?') as HTMLTextAreaElement).value).toBe(
      'slept better than it says',
    );
  });
});
