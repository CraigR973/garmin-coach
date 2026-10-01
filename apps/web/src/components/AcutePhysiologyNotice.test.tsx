import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { AcutePhysiology } from '@coach/shared';
import { SYMPTOM_NOTICES } from '@/lib/symptoms';
import { AcutePhysiologyNotice, GRADED_EASE_HEADING, SymptomNotice } from './AcutePhysiologyNotice';

const SMALL_RISE =
  'Your resting heart rate is 47 this morning against a usual 44 — a little above your usual range, as it was yesterday.';
const BIG_JUMP =
  'Your resting heart rate is 52 this morning against a usual 44 — a rise of 8 bpm. Take today off the bike.';

function boundary(overrides: Partial<AcutePhysiology>): AcutePhysiology {
  return {
    status: 'triggered',
    requiresBikeRest: false,
    triggeredSignals: ['resting_heart_rate'],
    escalations: [],
    ...overrides,
  };
}

describe('AcutePhysiologyNotice (Batch 293)', () => {
  it('heads a small rise "Why today is capped", as information rather than an alert', () => {
    render(
      <AcutePhysiologyNotice
        boundary={boundary({
          escalations: [{ kind: 'resting_heart_rate', level: 'ease', message: SMALL_RISE }],
        })}
      />,
    );

    const notice = screen.getByRole('status');
    expect(within(notice).getByText('Why today is capped')).toBeTruthy();
    expect(within(notice).getByText(SMALL_RISE)).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.queryByText('Why this needs rest')).toBeNull();
  });

  it('takes the most serious heading when a rest signal sits beside a small one', () => {
    render(
      <AcutePhysiologyNotice
        boundary={boundary({
          requiresBikeRest: true,
          triggeredSignals: ['resting_heart_rate', 'overnight_hrv'],
          escalations: [
            { kind: 'overnight_hrv', level: 'rest', message: BIG_JUMP },
            { kind: 'resting_heart_rate', level: 'ease', message: SMALL_RISE },
          ],
        })}
      />,
    );

    const alert = screen.getByRole('alert');
    expect(within(alert).getByText('Why this needs rest')).toBeTruthy();
    expect(within(alert).getByText(SMALL_RISE)).toBeTruthy();
  });

  it('reads a packet stored before levels existed exactly as before', () => {
    const { unmount } = render(
      <AcutePhysiologyNotice
        boundary={boundary({
          requiresBikeRest: true,
          escalations: [{ kind: 'resting_heart_rate', message: BIG_JUMP }],
        })}
      />,
    );
    expect(within(screen.getByRole('alert')).getByText('Why this needs rest')).toBeTruthy();
    unmount();

    render(
      <AcutePhysiologyNotice
        boundary={boundary({
          triggeredSignals: ['oxygen_respiration'],
          escalations: [{ kind: 'oxygen_respiration', message: 'Mention this to your GP.' }],
        })}
      />,
    );
    expect(within(screen.getByRole('alert')).getByText('A pattern worth checking')).toBeTruthy();
  });

  it('shows a head cold beside an HRV rest under the rest heading, and the two agree (Batch 294)', () => {
    const cold =
      "You've told me you have a head cold — symptoms above the neck. Easy riding at most today.";
    const hrv = 'Your overnight HRV is 39 ms this morning against a usual 47 ms. Take today off the bike.';
    render(
      <AcutePhysiologyNotice
        boundary={boundary({
          requiresBikeRest: true,
          triggeredSignals: ['symptoms', 'overnight_hrv'],
          escalations: [
            { kind: 'symptoms', level: 'ease', message: cold },
            { kind: 'overnight_hrv', level: 'rest', message: hrv },
          ],
        })}
      />,
    );

    const alert = screen.getByRole('alert');
    expect(within(alert).getByText('Why this needs rest')).toBeTruthy();
    expect(within(alert).getByText(cold)).toBeTruthy();
    expect(within(alert).getByText(hrv)).toBeTruthy();
  });

  it('shows nothing when no signal escalated', () => {
    const { container } = render(<AcutePhysiologyNotice boundary={boundary({})} />);
    expect(container.innerHTML).toBe('');
  });
});

describe('SymptomNotice (Batch 301)', () => {
  it('shows a chest answer as an alert, under the rest heading, in the server\'s words', () => {
    render(<SymptomNotice answer="chest_heart" />);

    const alert = screen.getByRole('alert');
    expect(within(alert).getByText('Why this needs rest')).toBeTruthy();
    expect(within(alert).getByText(SYMPTOM_NOTICES.chest_heart.notice)).toBeTruthy();
    expect(SYMPTOM_NOTICES.chest_heart.notice).toContain('call 999');
  });

  it('shows a fever as an alert and a head cold as information, as Home does', () => {
    const { unmount } = render(<SymptomNotice answer="fever_aches" />);
    expect(
      within(screen.getByRole('alert')).getByText(SYMPTOM_NOTICES.fever_aches.notice),
    ).toBeTruthy();
    unmount();

    render(<SymptomNotice answer="head_cold" />);
    const status = screen.getByRole('status');
    expect(within(status).getByText('Why today is capped')).toBeTruthy();
    expect(within(status).getByText(SYMPTOM_NOTICES.head_cold.notice)).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('shows nothing for None or for no answer', () => {
    for (const answer of ['none', null, undefined] as const) {
      const { container, unmount } = render(<SymptomNotice answer={answer} />);
      expect(container.innerHTML).toBe('');
      unmount();
    }
  });
});

describe('the graded wording (Batch 298)', () => {
  const LOW_NIGHT =
    "Your overnight HRV is 38 ms this morning against a usual 47 ms — lower than most nights for you. Dips like this usually come from a short night, a drink, a busy week or a hard day before. On its own it is one thing a little off, and today's call already counts it: not a day off the bike.";

  it('heads a single mild sign "Counted in today\'s call" when the graded verdict wrote it', () => {
    render(
      <AcutePhysiologyNotice
        boundary={boundary({
          gradedWording: true,
          triggeredSignals: ['overnight_hrv'],
          escalations: [{ kind: 'overnight_hrv', level: 'ease', message: LOW_NIGHT }],
        })}
      />,
    );

    const notice = screen.getByRole('status');
    expect(within(notice).getByText(GRADED_EASE_HEADING)).toBeTruthy();
    expect(GRADED_EASE_HEADING).toBe("Counted in today's call");
    expect(screen.queryByText('Why today is capped')).toBeNull();
  });

  it('keeps "Why today is capped" for a head cold, which does cap the day', () => {
    render(
      <AcutePhysiologyNotice
        boundary={boundary({
          gradedWording: true,
          triggeredSignals: ['symptoms', 'resting_heart_rate'],
          escalations: [
            { kind: 'symptoms', level: 'ease', message: 'A head cold.' },
            { kind: 'resting_heart_rate', level: 'ease', message: 'A small rise.' },
          ],
        })}
      />,
    );
    expect(within(screen.getByRole('status')).getByText('Why today is capped')).toBeTruthy();
  });

  it('keeps the old heading on a ladder morning and on one stored before Batch 298', () => {
    render(
      <AcutePhysiologyNotice
        boundary={boundary({
          triggeredSignals: ['overnight_hrv'],
          escalations: [{ kind: 'overnight_hrv', level: 'ease', message: 'Caps today at Amber.' }],
        })}
      />,
    );
    expect(within(screen.getByRole('status')).getByText('Why today is capped')).toBeTruthy();
  });
});
