import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { BriefFollowUpChat } from './BriefFollowUpChat';

const apiFetchMock = vi.fn();

vi.mock('@/lib/api', () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

function renderChat(analysisId = 'brief-1', timeZone = 'Europe/London') {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <BriefFollowUpChat analysisId={analysisId} timeZone={timeZone} />
    </QueryClientProvider>,
  );
}

describe('BriefFollowUpChat', () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
    apiFetchMock.mockResolvedValue({ data: [] });
  });

  it('keeps the per-read history ordered and renders profile-local dates and times', async () => {
    apiFetchMock.mockResolvedValueOnce({
      data: [
        {
          id: 'm1',
          analysisId: 'brief-1',
          role: 'user',
          content: 'Why is today Green?',
          proposedPlannedWorkoutId: null,
          createdAtUtc: '2026-07-14T22:50:00Z',
        },
        {
          id: 'm2',
          analysisId: 'brief-1',
          role: 'assistant',
          content: 'Your HRV was strong overnight.',
          proposedPlannedWorkoutId: null,
          createdAtUtc: '2026-07-14T22:55:00Z',
        },
        {
          id: 'm3',
          analysisId: 'brief-1',
          role: 'user',
          content: 'And what about tomorrow?',
          proposedPlannedWorkoutId: null,
          createdAtUtc: '2026-07-14T23:10:00Z',
        },
      ],
    });

    renderChat();

    expect(await screen.findByText('Why is today Green?')).toBeTruthy();
    expect(await screen.findByText('Your HRV was strong overnight.')).toBeTruthy();
    expect(screen.getByText('And what about tomorrow?')).toBeTruthy();
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/briefs/brief-1/messages');
    expect(apiFetchMock).not.toHaveBeenCalledWith('/api/v1/coach/messages');

    expect(screen.getAllByRole('separator')).toHaveLength(2);
    expect(screen.getByRole('separator', { name: 'Tuesday, 14 July 2026' })).toBeTruthy();
    expect(screen.getByRole('separator', { name: 'Wednesday, 15 July 2026' })).toBeTruthy();
    expect(screen.getByLabelText('Sent Tuesday, 14 July 2026 at 23:50')).toBeTruthy();
    expect(screen.getByLabelText('Sent Tuesday, 14 July 2026 at 23:55')).toBeTruthy();
    expect(screen.getByLabelText('Sent Wednesday, 15 July 2026 at 00:10')).toBeTruthy();

    const conversation = screen.getByRole('list', { name: 'Coach conversation' });
    expect(within(conversation).getAllByRole('listitem').map((item) => item.textContent)).toEqual([
      'Why is today Green?23:50',
      'Your HRV was strong overnight.23:55',
      'And what about tomorrow?00:10',
    ]);
  });

  it('asks a follow-up question and clears the input on success', async () => {
    const user = userEvent.setup();
    apiFetchMock.mockImplementation((path: string) => {
      if (path.endsWith('/messages') || path.includes('/messages')) {
        if (path === '/api/v1/briefs/brief-1/messages') {
          return Promise.resolve({ data: [] });
        }
      }
      return Promise.resolve({
        data: {
          userMessage: {
            id: 'u1',
            analysisId: 'brief-1',
            role: 'user',
            content: 'What if I skip today?',
            proposedPlannedWorkoutId: null,
            createdAtUtc: '2026-07-14T07:00:00Z',
          },
          assistantMessage: {
            id: 'a1',
            analysisId: 'brief-1',
            role: 'assistant',
            content: "That's fine — it's a recovery day either way.",
            proposedPlannedWorkoutId: null,
            createdAtUtc: '2026-07-14T07:00:05Z',
          },
        },
      });
    });

    renderChat();

    const textarea = await screen.findByLabelText('Ask a follow-up question');
    await user.type(textarea, 'What if I skip today?');
    await user.click(screen.getByRole('button', { name: /ask/i }));

    await waitFor(() => {
      const postCall = apiFetchMock.mock.calls.find(
        (call) => call[0] === '/api/v1/briefs/brief-1/messages' && call[1]?.method === 'POST',
      );
      expect(postCall).toBeTruthy();
      expect(JSON.parse(postCall![1].body)).toEqual({ question: 'What if I skip today?' });
    });

    await waitFor(() => expect((textarea as HTMLTextAreaElement).value).toBe(''));
  });

  it('offers a propose button only when the assistant turn carries a proposed workout', async () => {
    apiFetchMock.mockResolvedValueOnce({
      data: [
        {
          id: 'm1',
          analysisId: 'brief-1',
          role: 'user',
          content: 'Can you ease today’s ride?',
          proposedPlannedWorkoutId: null,
          createdAtUtc: '2026-07-14T06:40:00Z',
        },
        {
          id: 'm2',
          analysisId: 'brief-1',
          role: 'assistant',
          content: 'Sure, want me to ease it?',
          proposedPlannedWorkoutId: 'workout-9',
          createdAtUtc: '2026-07-14T06:40:05Z',
        },
      ],
    });

    renderChat();

    expect(await screen.findByRole('button', { name: 'Propose this adjustment' })).toBeTruthy();
  });
});
