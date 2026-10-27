import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  CHOOSE_ONE_LINE,
  CHOOSE_ONE_TITLE,
  NOT_THIS_DAY_LINE,
  RESTORE_PLAN_RIDE_LABEL,
  SWAP_OR_EASE_LINE,
  liveRideLine,
  restoredToast,
  showsLiveRide,
} from '@/lib/liveRide';
import type { ZwiftRail } from '@/lib/zwiftRail';

const rail = (state: string): ZwiftRail => ({
  state,
  pauseDate: null,
  showLoginReminder: false,
  checkedAtUtc: '2026-10-27T17:05:00Z',
});

const carried = {
  state: 'not_this_day',
  title: 'Recovery substitution: Sweet Spot (1 × 30 min @ 89%)',
  durationMin: 29,
  topPowerPct: 60,
};

describe('Batch 335 — what the app says about the ride on Zwift', () => {
  it('holds every line to the signed-off draft', () => {
    const draft = readFileSync(
      resolve(__dirname, '../../../../docs/drafts/2026-10-27-batch-335-wording.md'),
      'utf8',
    );
    for (const line of [
      liveRideLine(carried, rail('ok')),
      NOT_THIS_DAY_LINE,
      RESTORE_PLAN_RIDE_LABEL,
      restoredToast(rail('ok')),
      restoredToast(rail('paused')),
      CHOOSE_ONE_TITLE,
      CHOOSE_ONE_LINE,
      SWAP_OR_EASE_LINE,
    ]) {
      expect(draft).toContain(line);
    }
    expect(draft).toContain('"Sent to intervals.icu:"');
  });

  it('names the ride as Zwift shows it, and where it went', () => {
    expect(liveRideLine(carried, rail('ok'))).toBe(
      'On Zwift: “Recovery substitution: Sweet Spot (1 × 30 min @ 89%)”, 29 min, up to 60% FTP.',
    );
    expect(liveRideLine(carried, rail('paused'))).toBe(
      'Sent to intervals.icu: “Recovery substitution: Sweet Spot (1 × 30 min @ 89%)”, 29 min, up to 60% FTP.',
    );
    // An older server's day carries no rail and keeps today's words.
    expect(liveRideLine({ state: 'changed', title: 'Z2' }, undefined)).toBe('On Zwift: “Z2”.');
  });

  it('shows a live ride only when it is not the plan row’s', () => {
    expect(showsLiveRide(null)).toBe(false);
    expect(showsLiveRide({ state: 'as_planned', title: 'Z2' })).toBe(false);
    expect(showsLiveRide({ state: 'changed', title: 'Z2' })).toBe(true);
    expect(showsLiveRide(carried)).toBe(true);
  });
});
