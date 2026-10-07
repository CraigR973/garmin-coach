import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { acceptedLine } from '@/lib/nextPlan';
import {
  ZWIFT_PAUSED_LINE,
  ZWIFT_READY_LINE,
  ZWIFT_UNKNOWN_LINE,
  ZWIFT_UNLINKED_LINE,
  acceptedRidesDestination,
  adjustmentSentToast,
  appliedChangeTail,
  intervalChangeSentToast,
  reachesZwift,
  zwiftLoginReminder,
  zwiftProblemLine,
  zwiftStatusLine,
  type ZwiftRail,
} from '@/lib/zwiftRail';

const rail = (state: string, extra: Partial<ZwiftRail> = {}): ZwiftRail => ({
  state,
  pauseDate: null,
  showLoginReminder: false,
  checkedAtUtc: '2026-10-07T17:05:00Z',
  ...extra,
});

// The draft writes straight apostrophes; the app's lines keep the ones they had.
const straight = (line: string) => line.replace(/’/g, "'");

describe('Batch 326 — what the app may say about Zwift', () => {
  it('holds every line to the signed-off draft', () => {
    const draft = straight(
      readFileSync(
        resolve(__dirname, '../../../../docs/drafts/2026-10-07-batch-326-wording.md'),
        'utf8',
      ),
    );
    const paused = rail('paused');
    const lines = [
      ZWIFT_READY_LINE,
      ZWIFT_PAUSED_LINE,
      ZWIFT_UNLINKED_LINE,
      ZWIFT_UNKNOWN_LINE,
      zwiftLoginReminder(rail('login_due', { pauseDate: '2027-01-05', showLoginReminder: true })),
      adjustmentSentToast(rail('ok')),
      adjustmentSentToast(paused),
      intervalChangeSentToast(rail('ok')),
      intervalChangeSentToast(paused),
      `Done — today’s session is now {change}, ${appliedChangeTail(rail('ok'))}`,
      `Done — today’s session is now {change}, ${appliedChangeTail(paused)}`,
      acceptedLine('{Plan}', acceptedRidesDestination(rail('ok'))),
      acceptedLine('{Plan}', acceptedRidesDestination(paused)),
    ];

    for (const line of lines) {
      expect(line).not.toBeNull();
      expect(draft).toContain(straight(line as string));
    }
  });

  it('reaches Zwift only while the account does', () => {
    expect(reachesZwift(rail('ok'))).toBe(true);
    expect(reachesZwift(rail('login_due'))).toBe(true);
    expect(reachesZwift(rail('paused'))).toBe(false);
    expect(reachesZwift(rail('unlinked'))).toBe(false);
    expect(reachesZwift(rail('unknown'))).toBe(false);
    // A state a newer server adds is "can't check", never "in Zwift".
    expect(reachesZwift(rail('suspended'))).toBe(false);
    // An older server sends no rail, and the words stay as they were.
    expect(reachesZwift(undefined)).toBe(true);
    expect(reachesZwift(null)).toBe(true);
  });

  it('gives each state its line', () => {
    expect(zwiftStatusLine(rail('ok'))).toBe(ZWIFT_READY_LINE);
    expect(zwiftStatusLine(rail('login_due'))).toBe(ZWIFT_READY_LINE);
    expect(zwiftStatusLine(rail('paused'))).toBe(ZWIFT_PAUSED_LINE);
    expect(zwiftStatusLine(rail('unlinked'))).toBe(ZWIFT_UNLINKED_LINE);
    expect(zwiftStatusLine(rail('unknown'))).toBe(ZWIFT_UNKNOWN_LINE);
    expect(zwiftStatusLine(rail('suspended'))).toBe(ZWIFT_UNKNOWN_LINE);
    expect(zwiftStatusLine(undefined)).toBe(ZWIFT_READY_LINE);
  });

  it('names a problem only when it knows one', () => {
    expect(zwiftProblemLine(rail('paused'))).toBe(ZWIFT_PAUSED_LINE);
    expect(zwiftProblemLine(rail('unlinked'))).toBe(ZWIFT_UNLINKED_LINE);
    expect(zwiftProblemLine(rail('unknown'))).toBeNull();
    expect(zwiftProblemLine(rail('ok'))).toBeNull();
    expect(zwiftProblemLine(undefined)).toBeNull();
  });

  it('reminds only when the day says to, naming the pause date', () => {
    expect(
      zwiftLoginReminder(rail('login_due', { pauseDate: '2027-01-05', showLoginReminder: true })),
    ).toBe('Log in at intervals.icu before Tue 5 Jan to keep your rides reaching Zwift.');
    expect(zwiftLoginReminder(rail('login_due', { pauseDate: '2027-01-05' }))).toBeNull();
    expect(zwiftLoginReminder(rail('ok'))).toBeNull();
    expect(zwiftLoginReminder(undefined)).toBeNull();
  });

  it('keeps the accepted plan line as it was by default', () => {
    expect(acceptedLine('Plan No. 3')).toBe(
      'Plan No. 3 is in your plan, and its rides are on their way to Zwift.',
    );
  });
});
