import { describe, expect, it } from 'vitest';
import { TOMORROW_CALL_LINE, greetingForNow } from './copy';

// Batch 313: the morning's headline and line are today's call, stored on the server, so
// the only morning words left here are the tomorrow cue's fallback (signed off by Craig
// on Mark's behalf, 4 Oct 2026).
describe('today’s call copy (Batch 313)', () => {
  it('says where tomorrow’s call comes from, without a colour', () => {
    expect(TOMORROW_CALL_LINE).toBe("Tomorrow's call comes from tomorrow morning's readings.");
    expect(TOMORROW_CALL_LINE).not.toMatch(/\b(green|amber|red|verdict)\b/i);
  });

  it('greets by the time of day, as Home puts it in front of the call', () => {
    expect(greetingForNow(new Date(2026, 9, 7, 7, 30))).toBe('Good morning');
    expect(greetingForNow(new Date(2026, 9, 7, 13, 0))).toBe('Good afternoon');
    expect(greetingForNow(new Date(2026, 9, 7, 19, 0))).toBe('Good evening');
  });
});
