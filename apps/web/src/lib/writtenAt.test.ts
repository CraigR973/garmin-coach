import { describe, expect, it } from 'vitest';

import { writtenAt } from './dailyFlow';

/**
 * Batch 254 (UX241-14). `/brief` read `Generated 01/09/2026, 09:25:19` — a raw
 * locale date-time to the second. The seconds mean nothing to Mark and the
 * numeric date duplicates the eyebrow directly above it, so the one line on the
 * page read like debug output that had escaped an otherwise careful app.
 */
describe('writtenAt', () => {
  const timeZone = 'Europe/London';
  const now = new Date('2026-09-01T14:00:00Z');

  it('says which part of today, not the date', () => {
    expect(writtenAt('2026-09-01T08:25:00Z', { now, timeZone })).toBe(
      'Written at 09:25 this morning',
    );
    expect(writtenAt('2026-09-01T12:10:00Z', { now, timeZone })).toBe(
      'Written at 13:10 this afternoon',
    );
  });

  it('names yesterday rather than repeating the date', () => {
    expect(writtenAt('2026-08-31T08:25:00Z', { now, timeZone })).toBe(
      'Written yesterday at 09:25',
    );
  });

  it('falls back to a spoken date further back', () => {
    const older = writtenAt('2026-08-25T08:25:00Z', { now, timeZone });
    expect(older).toContain('Written on');
    expect(older).toContain('09:25');
    expect(older).not.toMatch(/\d{2}\/\d{2}\/\d{4}/);
  });

  it('never shows seconds', () => {
    expect(writtenAt('2026-09-01T08:25:19Z', { now, timeZone })).not.toContain('19');
  });

  it('has nothing to say about a missing or impossible timestamp', () => {
    expect(writtenAt(null)).toBeNull();
    expect(writtenAt('')).toBeNull();
    expect(writtenAt('not a date', { now })).toBeNull();
    // More than a day in the future is a sync error, not a read.
    expect(writtenAt('2026-09-04T08:00:00Z', { now, timeZone })).toBeNull();
  });
});
