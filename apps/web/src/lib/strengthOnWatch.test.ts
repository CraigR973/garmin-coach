import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  STRENGTH_ON_WATCH_BUTTON,
  STRENGTH_ON_WATCH_FAILED,
  strengthOnWatchToast,
} from './strengthOnWatch';

describe('strength on his watch (Batch 340)', () => {
  it('says what reached his watch, what was there already, and what failed', () => {
    expect(strengthOnWatchToast({ placed: ['Dumbbells A · Mon 02 Nov'], alreadyThere: [], failed: [] })).toBe(
      'On your watch after its next sync: Dumbbells A · Mon 02 Nov.',
    );
    expect(strengthOnWatchToast({ placed: [], alreadyThere: ['x'], failed: [] })).toBe('Already on your watch.');
    expect(strengthOnWatchToast({ placed: [], alreadyThere: [], failed: ['Dumbbells B · Sat 07 Nov'] })).toMatch(
      /^Couldn't send Dumbbells B/,
    );
  });

  it('uses the drafted words', () => {
    const draft = readFileSync(resolve(__dirname, '../../../../docs/drafts/2026-10-29-batch-340-wording.md'), 'utf8');
    for (const words of [STRENGTH_ON_WATCH_BUTTON, STRENGTH_ON_WATCH_FAILED, 'On your watch after its next sync:', 'Already on your watch.']) {
      expect(draft).toContain(words);
    }
  });
});
