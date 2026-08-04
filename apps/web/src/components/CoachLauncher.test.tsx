import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { CoachLauncher } from './CoachLauncher';
import { originForPath } from '@/lib/coachOrigin';

const apiFetchMock = vi.fn();

vi.mock('@/lib/api', () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

function renderLauncher(route = '/', timeZone = 'Europe/London') {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[route]}>
        <CoachLauncher timeZone={timeZone} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('originForPath', () => {
  it('maps each surface to its origin, defaulting to general', () => {
    expect(originForPath('/')).toBe('home');
    expect(originForPath('/sleep')).toBe('sleep');
    expect(originForPath('/brief')).toBe('morning_brief');
    expect(originForPath('/delivery')).toBe('week');
    expect(originForPath('/settings')).toBe('general');
  });
});

describe('CoachLauncher', () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
    apiFetchMock.mockResolvedValue({ data: [] });
  });

  it('is reachable from a page with no analysis row of its own', async () => {
    const user = userEvent.setup();
    renderLauncher('/sleep');

    // Batch 179.1: Sleep borrows the morning read and has no `Analysis` of its
    // own, so before this there was nothing here to hang a conversation on.
    await user.click(screen.getByLabelText('Ask about your sleep'));

    expect(await screen.findByLabelText('Ask your coach a question')).toBeTruthy();
  });

  it('sends the origin with the question and never a read id', async () => {
    const user = userEvent.setup();
    apiFetchMock.mockResolvedValue({ data: [] });
    renderLauncher('/sleep');

    await user.click(screen.getByLabelText('Ask about your sleep'));
    const textarea = await screen.findByLabelText('Ask your coach a question');
    await user.type(textarea, 'Why was my deep sleep short?');
    await user.click(screen.getByRole('button', { name: /^ask$/i }));

    await waitFor(() => {
      const post = apiFetchMock.mock.calls.find((call) => call[1]?.method === 'POST');
      expect(post).toBeTruthy();
      expect(post?.[0]).toBe('/api/v1/coach/messages');
      expect(JSON.parse(post?.[1].body as string)).toEqual({
        question: 'Why was my deep sleep short?',
        originKind: 'sleep',
      });
    });
  });

  it('shows the rolling thread in order with profile-local day separators and times', async () => {
    const user = userEvent.setup();
    apiFetchMock.mockResolvedValue({
      data: [
        {
          id: 'm1',
          analysisId: 'brief-1',
          originKind: 'morning_brief',
          originDate: null,
          role: 'user',
          content: 'Why is today Amber?',
          proposedPlannedWorkoutId: null,
          createdAtUtc: '2026-07-31T22:50:00Z',
        },
        {
          id: 'm2',
          analysisId: null,
          originKind: 'sleep',
          originDate: '2026-07-30',
          role: 'assistant',
          content: 'Your HRV dropped overnight.',
          proposedPlannedWorkoutId: null,
          createdAtUtc: '2026-07-31T22:55:00Z',
        },
        {
          id: 'm3',
          analysisId: null,
          originKind: 'trends',
          originDate: '2026-08-01',
          role: 'user',
          content: 'How has that changed this month?',
          proposedPlannedWorkoutId: null,
          createdAtUtc: '2026-07-31T23:10:00Z',
        },
      ],
    });

    renderLauncher('/trends');
    await user.click(screen.getByLabelText('Ask about your trends'));

    // The conversation survives the read it started on (179.4).
    expect(await screen.findByText('Why is today Amber?')).toBeTruthy();
    expect(await screen.findByText('Your HRV dropped overnight.')).toBeTruthy();
    expect(screen.getByText('How has that changed this month?')).toBeTruthy();

    // Europe/London is one hour ahead of UTC in July. The final message crosses
    // local midnight even though all three UTC timestamps are still 31 July.
    expect(screen.getAllByRole('separator')).toHaveLength(2);
    expect(screen.getByRole('separator', { name: 'Friday, 31 July 2026' })).toBeTruthy();
    expect(screen.getByRole('separator', { name: 'Saturday, 1 August 2026' })).toBeTruthy();
    expect(screen.getByLabelText('Sent Friday, 31 July 2026 at 23:50')).toBeTruthy();
    expect(screen.getByLabelText('Sent Friday, 31 July 2026 at 23:55')).toBeTruthy();
    expect(screen.getByLabelText('Sent Saturday, 1 August 2026 at 00:10')).toBeTruthy();

    const conversation = screen.getByRole('list', { name: 'Coach conversation' });
    expect(within(conversation).getAllByRole('listitem').map((item) => item.textContent)).toEqual([
      'Why is today Amber?23:50',
      'Your HRV dropped overnight.23:55',
      'How has that changed this month?00:10',
    ]);
  });

  it('stays out of the way on the pre-auth routes', () => {
    renderLauncher('/access');
    expect(screen.queryByLabelText(/ask/i)).toBeNull();
  });
});
