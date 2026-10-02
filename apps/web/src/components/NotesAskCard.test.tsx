import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { NOTES_ASK_TITLE, NOTES_ASK_UPDATING, notesAskLine } from '@/lib/notesAsk';
import { SYMPTOM_NOTICES, SYMPTOM_OPTIONS } from '@/lib/symptoms';
import { NotesAskCard } from './NotesAskCard';

const apiFetchMock = vi.fn();
const toastErrorMock = vi.fn();

vi.mock('@/lib/api', () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}));
vi.mock('sonner', () => ({
  toast: { error: (...args: unknown[]) => toastErrorMock(...args) },
}));

const DAY = '2026-10-09';

function renderCard(props: Partial<Parameters<typeof NotesAskCard>[0]> = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <NotesAskCard ask words="heartburn kept me awake" subjectDate={DAY} {...props} />
    </QueryClientProvider>,
  );
}

/** The reply to an answer, and to each look afterwards: the day with one stored morning. */
function day(morningId: string, notesAsk: boolean) {
  return {
    data: {
      subjectDate: DAY,
      timezone: 'Europe/London',
      morningAnalysis: {
        id: morningId,
        generatedAtUtc: '2026-10-09T06:35:00Z',
        verdict: 'amber',
        promptVersion: 'morning-v1',
        modelName: 'claude-test',
        outputMarkdown: '**Amber**',
        notesAsk,
      },
      hostedTtsConsent: false,
      holiday: { isActive: false, awayTonight: false, activeWindow: null },
      dailyMetrics: null,
      sleep: null,
      manualEntry: null,
      thermalState: {
        latestTemperatureC: 17.4,
        targetTemperatureC: 17,
        capturedAtUtc: '2026-10-09T06:25:00Z',
        overnightLowC: 11.2,
        overnightWindMaxMph: 12,
        overnightWindGustMph: 18,
        thermalReview: {},
        fans: [],
      },
      postWorkoutAnalyses: [],
      plannedWorkouts: [],
      dataQualityWarnings: [],
    },
    meta: { generatedAtUtc: '2026-10-09T06:40:00Z' },
    errors: [],
  };
}

const BEFORE = '22222222-2222-4222-8222-222222222222';
const AFTER = '33333333-3333-4333-8333-333333333333';

// Batch 297: his note may name a symptom, so Home asks rather than guesses.
// Batch 303: he answers on Home, in one tap.
describe('notes ask card', () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
    toastErrorMock.mockReset();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('quotes his note and offers the check-in\u2019s four answers, none chosen for him', () => {
    renderCard();
    expect(screen.getByText('Any symptoms today?')).toBeTruthy();
    expect(
      screen.getByText(
        'Your note mentions “heartburn kept me awake”. If that’s a symptom, tell me, so today’s plan fits.',
      ),
    ).toBeTruthy();

    const answers = within(screen.getByRole('group', { name: NOTES_ASK_TITLE })).getAllByRole(
      'button',
    );
    expect(answers.map((button) => button.textContent)).toEqual([
      'None',
      'Head coldRunny or blocked nose, sneezing, sore throat',
      'Fever or achesA temperature, aching muscles, or a chesty cough',
      'Chest or heartChest pain or tightness, a racing or irregular heartbeat, feeling faint, or unusual breathlessness',
    ]);
    // On the check-in None is preselected, and saving it was "his answer". Here nothing is.
    expect(answers.map((button) => button.getAttribute('aria-pressed'))).toEqual([
      'false',
      'false',
      'false',
      'false',
    ]);
    // The button that opened the check-in is gone.
    expect(screen.queryByRole('link')).toBeNull();
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it('says the hard session is an easy ride until he answers, when it is', () => {
    renderCard({ eases: true, words: 'heartburn' });
    expect(
      screen.getByText(
        'Your note mentions “heartburn”. Until you answer, today’s hard session is an easy ride.',
      ),
    ).toBeTruthy();
    expect(notesAskLine(null, true)).toBe(
      'Something in your note might be a symptom. Until you answer, today’s hard session is an easy ride.',
    );
  });

  it('shows nothing when the note asks nothing, or on a read stored before the reader', () => {
    const { container } = renderCard({ ask: false, words: 'anything' });
    expect(container.textContent).toBe('');
    expect(renderCard({ ask: undefined, words: undefined }).container.textContent).toBe('');
  });

  it('has a line for a note with no quotable words', () => {
    expect(notesAskLine(null)).toBe(
      'Something in your note might be a symptom. If it is, tell me, so today’s plan fits.',
    );
  });

  it('records one tap as his answer, saves nothing else, and waits for the regraded morning', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    apiFetchMock.mockImplementation((_path: string, init?: RequestInit) => {
      if (init?.method === 'POST') return Promise.resolve(day(BEFORE, true));
      // The first look still finds the morning as it was; the second finds the regrade.
      const looks = apiFetchMock.mock.calls.filter(([, options]) => options === undefined).length;
      return Promise.resolve(looks < 2 ? day(BEFORE, true) : day(AFTER, false));
    });
    renderCard();

    await user.click(screen.getByRole('button', { name: /^None/ }));

    expect(apiFetchMock).toHaveBeenCalledWith(`/api/v1/daily-loop/${DAY}/symptom-answer`, {
      method: 'POST',
      body: JSON.stringify({ answer: 'none' }),
    });
    // Not a save of the check-in.
    expect(
      apiFetchMock.mock.calls.some(([path]) => String(path).includes('manual-entry')),
    ).toBe(false);
    expect(screen.getByText(NOTES_ASK_UPDATING)).toBeTruthy();
    // One answer, not four: the others cannot be tapped while it is on its way.
    for (const button of screen.getAllByRole('button')) {
      expect((button as HTMLButtonElement).disabled).toBe(true);
    }
    expect(screen.getByRole('button', { name: /^None/ }).getAttribute('aria-pressed')).toBe('true');

    // It looks for the regraded morning every three seconds, and stops when it lands.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    const looks = apiFetchMock.mock.calls.filter(([, options]) => options === undefined);
    expect(looks.map(([path]) => path)).toEqual(['/api/v1/daily-loop', '/api/v1/daily-loop']);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(9000);
    });
    expect(apiFetchMock.mock.calls.filter(([, options]) => options === undefined)).toHaveLength(2);
  });

  it('shows a floor answer\u2019s notice at once, before the morning is regraded', async () => {
    apiFetchMock.mockReturnValue(new Promise(() => undefined)); // the answer is still on its way
    renderCard();

    await userEvent.setup().click(screen.getByRole('button', { name: /^Chest or heart/ }));

    expect(screen.getByText(SYMPTOM_NOTICES.chest_heart.notice)).toBeTruthy();
    expect(screen.getByText(/call 999\.$/)).toBeTruthy();
    expect(apiFetchMock).toHaveBeenCalledWith(`/api/v1/daily-loop/${DAY}/symptom-answer`, {
      method: 'POST',
      body: JSON.stringify({ answer: 'chest_heart' }),
    });
  });

  it('asks again when the answer could not be saved', async () => {
    apiFetchMock.mockRejectedValue(new Error('offline'));
    renderCard();

    await userEvent.setup().click(screen.getByRole('button', { name: /^Head cold/ }));

    expect(toastErrorMock).toHaveBeenCalledWith('offline');
    for (const button of await screen.findAllByRole('button')) {
      expect((button as HTMLButtonElement).disabled).toBe(false);
    }
    expect(screen.queryByText(NOTES_ASK_UPDATING)).toBeNull();
  });

  it('uses the words Craig signed off, and no others', () => {
    // The draft is the record of the sign-off, so a reworded line fails here until the
    // draft, and so the sign-off, follows. The draft is typed with straight quotes.
    const straight = (text: string) => text.replace(/[\u2018\u2019]/g, "'");
    const draft = readFileSync(
      resolve(__dirname, '../../../../docs/drafts/2026-10-02-batch-303-wording.md'),
      'utf8',
    )
      .replace(/\n>\s?/g, ' ')
      .replace(/\*\*/g, '')
      .replace(/\s+/g, ' ');

    expect(draft).toContain("signed off by Craig on Mark's behalf, 2 Oct 2026");
    const chest = SYMPTOM_OPTIONS.find((option) => option.value === 'chest_heart');
    for (const words of [
      chest?.detail ?? '',
      SYMPTOM_NOTICES.chest_heart.notice,
      "Until you answer, today's hard session is an easy ride.",
      NOTES_ASK_UPDATING,
      SYMPTOM_OPTIONS.map((option) => option.label).join(' · '),
    ]) {
      expect(draft, words).toContain(straight(words));
    }
  });
});
