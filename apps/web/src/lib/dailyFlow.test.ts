import { describe, expect, it } from 'vitest';
import { localTodayIso } from './dailyFlow';

// Batch 138 — `localTodayIso` must return the *local* calendar date in the
// profile's timezone, not the UTC date `new Date().toISOString()` produces. The
// bug lived at the day boundary: during BST the UK local date rolls over an hour
// before the UTC date does, so a late-evening open named the wrong day.

describe('localTodayIso', () => {
  it('returns the local date in Europe/London during BST at the UTC-vs-local boundary', () => {
    // 2026-07-17 23:30 UTC is 2026-07-18 00:30 BST (UTC+1) — already the next day
    // locally. The old `toISOString().slice(0,10)` would wrongly give 2026-07-17.
    const at = new Date('2026-07-17T23:30:00Z');
    expect(localTodayIso('Europe/London', at)).toBe('2026-07-18');
  });

  it('agrees with UTC in Europe/London during GMT (winter)', () => {
    // 2026-01-17 23:30 UTC is 2026-01-17 23:30 GMT (UTC+0) — same day.
    const at = new Date('2026-01-17T23:30:00Z');
    expect(localTodayIso('Europe/London', at)).toBe('2026-01-17');
  });

  it('rolls back a day for a timezone behind UTC', () => {
    // 2026-07-17 02:00 UTC is 2026-07-16 22:00 in America/New_York (EDT, UTC-4).
    const at = new Date('2026-07-17T02:00:00Z');
    expect(localTodayIso('America/New_York', at)).toBe('2026-07-16');
  });

  it('zero-pads month and day', () => {
    const at = new Date('2026-03-05T12:00:00Z');
    expect(localTodayIso('Europe/London', at)).toBe('2026-03-05');
  });

  it('falls back to the browser timezone when none is supplied', () => {
    // No timezone → uses the runtime zone; assert it still yields a valid ISO date
    // rather than throwing (the exact value depends on the test runner's TZ).
    expect(localTodayIso(undefined, new Date('2026-07-17T12:00:00Z'))).toMatch(
      /^\d{4}-\d{2}-\d{2}$/,
    );
  });
});
