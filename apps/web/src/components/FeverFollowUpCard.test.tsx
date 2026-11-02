import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { FeverFollowUp } from '@coach/shared';
import { FEVER_FOLLOW_UP_ASK, FEVER_FOLLOW_UP_OPTIONS, feverFollowUpTitle } from '@/lib/feverFollowUp';
import { NOTES_ASK_UPDATING } from '@/lib/notesAsk';
import { SYMPTOM_NOTICES } from '@/lib/symptoms';
import { FeverFollowUpCard } from './FeverFollowUpCard';

const apiFetchMock = vi.fn();

vi.mock('@/lib/api', () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}));
vi.mock('sonner', () => ({ toast: { error: vi.fn() } }));

const DAY = '2026-10-09';
const OPEN: FeverFollowUp = {
  reportedOn: '2026-10-08',
  reportedWeekday: 'Thursday',
  answer: null,
  eases: true,
};

function renderCard(followUp: FeverFollowUp | null | undefined) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <FeverFollowUpCard followUp={followUp} subjectDate={DAY} />
    </QueryClientProvider>,
  );
}

// Batch 364 (HS361-02): after a fever, ask whether it has gone.
describe('fever follow-up card', () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
  });

  it('names the day, asks the question, and offers two answers, none chosen for him', () => {
    renderCard(OPEN);
    expect(screen.getByText('Fever, aches or a chest infection on Thursday')).toBeTruthy();
    expect(screen.getByText(FEVER_FOLLOW_UP_ASK)).toBeTruthy();
    const answers = within(
      screen.getByRole('group', { name: feverFollowUpTitle('Thursday') }),
    ).getAllByRole('button');
    expect(answers.map((button) => button.textContent)).toEqual([
      'Gone for a full day, without paracetamol or ibuprofen',
      'Still there',
    ]);
    expect(answers.map((button) => button.getAttribute('aria-pressed'))).toEqual(['false', 'false']);
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it('shows nothing when no follow-up is open', () => {
    expect(renderCard(null).container.textContent).toBe('');
    expect(renderCard(undefined).container.textContent).toBe('');
  });

  it('records "Gone" as the fever follow-up\'s answer and saves nothing else', async () => {
    apiFetchMock.mockReturnValue(new Promise(() => undefined));
    renderCard(OPEN);

    await userEvent.setup().click(screen.getByRole('button', { name: /^Gone for a full day/ }));

    expect(apiFetchMock).toHaveBeenCalledWith(`/api/v1/daily-loop/${DAY}/symptom-follow-up`, {
      method: 'POST',
      body: JSON.stringify({ answer: 'cleared', kind: 'fever_aches' }),
    });
    expect(screen.getByText(NOTES_ASK_UPDATING)).toBeTruthy();
  });

  it('shows the fever notice at once for "Still there"', async () => {
    apiFetchMock.mockReturnValue(new Promise(() => undefined));
    renderCard(OPEN);

    await userEvent.setup().click(screen.getByRole('button', { name: 'Still there' }));

    expect(screen.getByText(SYMPTOM_NOTICES.fever_aches.notice)).toBeTruthy();
  });

  it('uses the words in the draft for Craig\'s sign-off, and no others', () => {
    const draft = readFileSync(
      resolve(__dirname, '../../../../docs/drafts/2026-11-02-batch-364-wording.md'),
      'utf8',
    );
    for (const words of [
      feverFollowUpTitle('Thursday'),
      FEVER_FOLLOW_UP_ASK,
      ...FEVER_FOLLOW_UP_OPTIONS.map((option) => option.label),
    ]) {
      expect(draft).toContain(words);
    }
  });
});
