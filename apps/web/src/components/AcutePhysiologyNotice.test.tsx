import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { AcutePhysiology } from '@coach/shared';
import { AcutePhysiologyNotice } from './AcutePhysiologyNotice';

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
