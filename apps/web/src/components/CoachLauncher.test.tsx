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
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[route]}>
        <CoachLauncher userId="00000000-0000-4000-8000-000000000185" timeZone={timeZone} />
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
    localStorage.clear();
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

  it('shows an unread marker for a coach-initiated weekly review until opened', async () => {
    const user = userEvent.setup();
    apiFetchMock.mockResolvedValue({
      data: [
        {
          id: '00000000-0000-4000-8000-000000000001',
          analysisId: '00000000-0000-4000-8000-000000000002',
          originKind: 'weekly_review',
          originDate: '2026-08-02',
          role: 'assistant',
          content: '**Bottom line:** Recovery held steady while load rose.',
          proposedPlannedWorkoutId: null,
          createdAtUtc: '2026-08-02T17:00:00Z',
        },
      ],
    });

    renderLauncher('/');

    const unreadLauncher = await screen.findByLabelText(/new coach message/i);
    await user.click(unreadLauncher);

    expect(await screen.findByText(/Recovery held steady while load rose/)).toBeTruthy();
    await waitFor(() => {
      expect(screen.getByLabelText('Ask about today')).toBeTruthy();
    });
    expect(
      localStorage.getItem(
        'coach:last-seen-assistant:v1:00000000-0000-4000-8000-000000000185',
      ),
    ).toBe('00000000-0000-4000-8000-000000000001');
  });

  it('opens from the weekly push deep-link and anchors the reply to the review', async () => {
    const user = userEvent.setup();
    const reviewMessage = {
      id: '00000000-0000-4000-8000-000000000011',
      analysisId: '00000000-0000-4000-8000-000000000012',
      originKind: 'weekly_review',
      originDate: '2026-08-02',
      role: 'assistant',
      content: '**Bottom line:** Sleep consistency was the week\'s biggest win.',
      proposedPlannedWorkoutId: null,
      createdAtUtc: '2026-08-02T17:00:00Z',
    };
    apiFetchMock.mockResolvedValue({ data: [reviewMessage] });

    renderLauncher('/?coach=open');

    const textarea = await screen.findByLabelText('Ask your coach a question');
    await user.type(textarea, 'What should I protect next week?');
    await user.click(screen.getByRole('button', { name: /^ask$/i }));

    await waitFor(() => {
      const post = apiFetchMock.mock.calls.find((call) => call[1]?.method === 'POST');
      expect(JSON.parse(post?.[1].body as string)).toEqual({
        question: 'What should I protect next week?',
        analysisId: '00000000-0000-4000-8000-000000000012',
        originKind: 'weekly_review',
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

  it('shows an unread marker for a coach-initiated state-change turn, not only a weekly review', async () => {
    // UX192-04 / CR189-01: the predicate used to hard-code `weekly_review`, so
    // Batch 187's state-change coach could write a turn that lit nothing.
    apiFetchMock.mockResolvedValue({
      data: [
        {
          id: '00000000-0000-4000-8000-000000000021',
          analysisId: null,
          originKind: 'state_change',
          originDate: '2026-08-06',
          role: 'assistant',
          content: 'Your chronic deload escalation has cleared.',
          proposedPlannedWorkoutId: null,
          createdAtUtc: '2026-08-06T07:00:00Z',
        },
      ],
    });

    renderLauncher('/');

    expect(await screen.findByLabelText(/new coach message/i)).toBeTruthy();
  });

  it('presents loading, error-with-retry, and empty states distinctly', async () => {
    apiFetchMock.mockRejectedValue(new Error('network down'));
    renderLauncher('/');

    const user = userEvent.setup();
    await user.click(screen.getByLabelText('Ask about today'));

    expect(
      await screen.findByText(/could not load your conversation/i),
    ).toBeTruthy();
    const retryButton = screen.getByRole('button', { name: /try again/i });

    apiFetchMock.mockResolvedValue({ data: [] });
    await user.click(retryButton);

    expect(await screen.findByText(/nothing here yet/i)).toBeTruthy();
  });

  it('shows the question immediately and a thinking indicator while the reply is pending', async () => {
    const user = userEvent.setup();
    let resolvePost: (value: unknown) => void = () => {};
    apiFetchMock.mockImplementation((_path: string, options?: { method?: string }) => {
      if (options?.method === 'POST') {
        return new Promise((resolve) => {
          resolvePost = resolve;
        });
      }
      return Promise.resolve({ data: [] });
    });

    renderLauncher('/');
    await user.click(screen.getByLabelText('Ask about today'));

    const textarea = await screen.findByLabelText('Ask your coach a question');
    await user.type(textarea, 'How is my week looking?');
    await user.click(screen.getByRole('button', { name: /^ask$/i }));

    expect(await screen.findByText('How is my week looking?')).toBeTruthy();
    expect(screen.getByLabelText('Your coach is thinking')).toBeTruthy();

    resolvePost({
      data: {
        userMessage: {
          id: 'u1',
          analysisId: null,
          originKind: 'home',
          role: 'user',
          content: 'How is my week looking?',
          proposedPlannedWorkoutId: null,
          createdAtUtc: '2026-08-06T07:00:00Z',
        },
        assistantMessage: {
          id: 'a1',
          analysisId: null,
          originKind: 'home',
          role: 'assistant',
          content: 'On track.',
          proposedPlannedWorkoutId: null,
          createdAtUtc: '2026-08-06T07:00:05Z',
        },
      },
    });

    await waitFor(() => {
      expect(screen.queryByLabelText('Your coach is thinking')).toBeNull();
    });
  });

  it('scrolls the thread pane to the newest turn on open, not scrollTop 0', async () => {
    // UX192-02: jsdom does no real layout, so `scrollHeight` is stubbed on the
    // prototype before mount — the assertion is that the effect actively sets
    // `scrollTop` to whatever the pane reports, not that jsdom computed a
    // real 28,380px pane.
    const scrollHeightSpy = vi
      .spyOn(Element.prototype, 'scrollHeight', 'get')
      .mockReturnValue(28_380);
    apiFetchMock.mockResolvedValue({
      data: [
        {
          id: 'm1',
          analysisId: null,
          originKind: 'home',
          role: 'assistant',
          content: 'Old turn',
          proposedPlannedWorkoutId: null,
          createdAtUtc: '2026-07-01T07:00:00Z',
        },
      ],
    });
    const user = userEvent.setup();
    renderLauncher('/');
    await user.click(screen.getByLabelText('Ask about today'));

    const pane = await screen.findByRole('list', { name: 'Coach conversation' });
    await waitFor(() => {
      expect(pane.scrollTop).toBe(28_380);
    });

    scrollHeightSpy.mockRestore();
  });
});
