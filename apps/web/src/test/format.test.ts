import { describe, it, expect } from 'vitest';
import { formatSubmitTime } from '@/lib/format';

describe('formatSubmitTime', () => {
  it('renders minutes for < 1 hour', () => {
    expect(formatSubmitTime(45)).toBe('45m before');
    expect(formatSubmitTime(1)).toBe('1m before');
  });

  it('renders hours only when no remainder', () => {
    expect(formatSubmitTime(120)).toBe('2h before');
    expect(formatSubmitTime(60)).toBe('1h before');
  });

  it('renders hours and minutes when there is a remainder', () => {
    expect(formatSubmitTime(90)).toBe('1h 30m before');
    expect(formatSubmitTime(150)).toBe('2h 30m before');
  });

  it('renders days and hours for > 24h', () => {
    expect(formatSubmitTime(25 * 60)).toBe('1d 1h before');
    expect(formatSubmitTime(48 * 60)).toBe('2d before');
    expect(formatSubmitTime(49 * 60)).toBe('2d 1h before');
  });

  it('handles 0 minutes', () => {
    expect(formatSubmitTime(0)).toBe('0m before');
  });
});
