import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { Week1SurveyModal } from '@/components/Week1SurveyModal';
import * as surveyLib from '@/lib/survey';

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock('@/lib/survey', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/survey')>();
  return { ...actual, submitSurvey: vi.fn() };
});

const mockedSubmit = vi.mocked(surveyLib.submitSurvey);

function renderModal() {
  const onClose = vi.fn();
  const onSubmitted = vi.fn();
  render(<Week1SurveyModal onClose={onClose} onSubmitted={onSubmitted} />);
  return { onClose, onSubmitted };
}

/** Answer all five required questions so Submit becomes enabled. */
function answerRequired() {
  fireEvent.click(screen.getByRole('button', { name: 'Rating 3 of 5' }));
  fireEvent.click(screen.getByRole('button', { name: /about once a day/i }));
  fireEvent.click(screen.getByRole('button', { name: /about right/i }));
  fireEvent.click(screen.getByRole('button', { name: /^No$/i }));
  fireEvent.click(screen.getByRole('button', { name: /nothing major/i }));
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('Week1SurveyModal', () => {
  it('keeps Submit disabled until the required questions are answered', () => {
    renderModal();
    expect((screen.getByRole('button', { name: /submit/i }) as HTMLButtonElement).disabled).toBe(
      true,
    );
  });

  it('shows the feedback poster image', () => {
    renderModal();
    expect(screen.getByRole('img', { name: /uncle sam|feedback/i })).toBeTruthy();
  });

  it('submits an anonymous response with the chosen answers', async () => {
    mockedSubmit.mockResolvedValue({ completed: true });
    const { onSubmitted } = renderModal();
    answerRequired();

    const submit = screen.getByRole('button', { name: /submit/i }) as HTMLButtonElement;
    expect(submit.disabled).toBe(false);
    fireEvent.click(submit);

    await waitFor(() => expect(mockedSubmit).toHaveBeenCalledOnce());
    const [key, answers, contactOk] = mockedSubmit.mock.calls[0];
    expect(key).toBe('week1_pulse');
    expect(answers.q2_overall).toBe(3);
    expect(answers.q3_frequency).toBe('daily');
    expect(answers.q4_notifications).toBe('about_right');
    expect(answers.q6_biggest_annoyance).toBe('nothing');
    expect(contactOk).toBe(false);
    await waitFor(() => expect(onSubmitted).toHaveBeenCalled());
  });

  it('attaches identity when the contact box is ticked', async () => {
    mockedSubmit.mockResolvedValue({ completed: true });
    renderModal();
    answerRequired();
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(screen.getByRole('button', { name: /submit/i }));

    await waitFor(() => expect(mockedSubmit).toHaveBeenCalled());
    expect(mockedSubmit.mock.calls[0][2]).toBe(true);
  });
});
