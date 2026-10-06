import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ChestFollowUp } from '@coach/shared';
import {
  CHEST_FOLLOW_UP_ASK,
  CHEST_FOLLOW_UP_NOT_SEEN,
  CHEST_FOLLOW_UP_OPTIONS,
  chestFollowUpTitle,
} from '@/lib/chestFollowUp';
import { NOTES_ASK_UPDATING } from '@/lib/notesAsk';
import { SYMPTOM_NOTICES } from '@/lib/symptoms';
import { ChestFollowUpCard } from './ChestFollowUpCard';

const apiFetchMock = vi.fn();
const toastErrorMock = vi.fn();

vi.mock('@/lib/api', () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}));
vi.mock('sonner', () => ({
  toast: { error: (...args: unknown[]) => toastErrorMock(...args) },
}));

const DAY = '2026-10-14';
const OPEN: ChestFollowUp = {
  reportedOn: '2026-10-13',
  reportedWeekday: 'Tuesday',
  answer: null,
  eases: true,
};

function renderCard(followUp: ChestFollowUp | null | undefined) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ChestFollowUpCard followUp={followUp} subjectDate={DAY} />
    </QueryClientProvider>,
  );
}

// Batch 315: after a chest or heart report, ask before hard work.
describe('chest follow-up card', () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
    toastErrorMock.mockReset();
  });

  it('names the day, asks the question, and offers three answers, none chosen for him', () => {
    renderCard(OPEN);
    expect(screen.getByText('Chest or heart symptoms on Tuesday')).toBeTruthy();
    expect(screen.getByText(CHEST_FOLLOW_UP_ASK)).toBeTruthy();
    const answers = within(
      screen.getByRole('group', { name: chestFollowUpTitle('Tuesday') }),
    ).getAllByRole('button');
    expect(answers.map((button) => button.textContent)).toEqual([
      "Gone, and I've spoken to my GP or 111",
      "Gone, but I haven't spoken to anyone yet",
      'Still there',
    ]);
    expect(answers.map((button) => button.getAttribute('aria-pressed'))).toEqual([
      'false',
      'false',
      'false',
    ]);
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it('after "not yet", says hard sessions stay easy rides and keeps the answers', () => {
    renderCard({ ...OPEN, answer: 'not_seen' });
    expect(screen.getByText(CHEST_FOLLOW_UP_NOT_SEEN)).toBeTruthy();
    expect(screen.queryByText(CHEST_FOLLOW_UP_ASK)).toBeNull();
    const notSeen = screen.getByRole('button', { name: /^Gone, but/ });
    expect(notSeen.getAttribute('aria-pressed')).toBe('true');
    // He can still say later the same day that he has spoken to someone.
    for (const button of screen.getAllByRole('button')) {
      expect((button as HTMLButtonElement).disabled).toBe(false);
    }
  });

  it('shows nothing when no follow-up is open, or on a morning stored before it', () => {
    expect(renderCard(null).container.textContent).toBe('');
    expect(renderCard(undefined).container.textContent).toBe('');
  });

  it('records one tap as his answer and saves nothing else', async () => {
    apiFetchMock.mockReturnValue(new Promise(() => undefined)); // still on its way
    renderCard(OPEN);

    await userEvent.setup().click(screen.getByRole('button', { name: /^Gone, and/ }));

    expect(apiFetchMock).toHaveBeenCalledWith(`/api/v1/daily-loop/${DAY}/symptom-follow-up`, {
      method: 'POST',
      body: JSON.stringify({ answer: 'cleared' }),
    });
    expect(
      apiFetchMock.mock.calls.some(([path]) => String(path).includes('manual-entry')),
    ).toBe(false);
    expect(screen.getByText(NOTES_ASK_UPDATING)).toBeTruthy();
    for (const button of screen.getAllByRole('button')) {
      expect((button as HTMLButtonElement).disabled).toBe(true);
    }
  });

  it('shows the chest-or-heart notice at once for "Still there"', async () => {
    apiFetchMock.mockReturnValue(new Promise(() => undefined));
    renderCard(OPEN);

    await userEvent.setup().click(screen.getByRole('button', { name: 'Still there' }));

    expect(screen.getByText(SYMPTOM_NOTICES.chest_heart.notice)).toBeTruthy();
    expect(apiFetchMock).toHaveBeenCalledWith(`/api/v1/daily-loop/${DAY}/symptom-follow-up`, {
      method: 'POST',
      body: JSON.stringify({ answer: 'still_there' }),
    });
  });

  it('asks again when the answer could not be saved', async () => {
    apiFetchMock.mockRejectedValue(new Error('offline'));
    renderCard(OPEN);

    await userEvent.setup().click(screen.getByRole('button', { name: /^Gone, but/ }));

    expect(toastErrorMock).toHaveBeenCalledWith('offline');
    for (const button of await screen.findAllByRole('button')) {
      expect((button as HTMLButtonElement).disabled).toBe(false);
    }
    expect(screen.queryByText(NOTES_ASK_UPDATING)).toBeNull();
  });

  it('uses the words signed off, and no others', () => {
    const draft = readFileSync(
      resolve(__dirname, '../../../../docs/drafts/2026-10-06-batch-315-wording.md'),
      'utf8',
    )
      .replace(/\*\*/g, '')
      .replace(/\s+/g, ' ');
    expect(draft).toContain("signed off on Mark's behalf under Craig's delegation of 6 Oct 2026");
    for (const words of [
      chestFollowUpTitle('Tuesday'),
      CHEST_FOLLOW_UP_ASK,
      CHEST_FOLLOW_UP_NOT_SEEN,
      CHEST_FOLLOW_UP_OPTIONS.map((option) => option.label).join(' · '),
      NOTES_ASK_UPDATING.replace(/’/g, "'"),
    ]) {
      expect(draft, words).toContain(words);
    }
  });
});
