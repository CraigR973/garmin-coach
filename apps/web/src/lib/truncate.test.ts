import { describe, expect, it } from 'vitest';
import { truncateWords } from './truncate';

describe('truncateWords', () => {
  it('returns the input unchanged when it already fits', () => {
    expect(truncateWords('Tempo ride', 20)).toBe('Tempo ride');
  });

  it('cuts at the last word boundary, not mid-word', () => {
    expect(truncateWords('REM in your 65-90 minute range last night', 20)).toBe('REM in your 65-90…');
  });

  it('falls back to a hard cut when there is no earlier space', () => {
    expect(truncateWords('Supercalifragilisticexpialidocious', 10)).toBe('Supercalif…');
  });

  it('is exact at the boundary (no truncation needed)', () => {
    expect(truncateWords('12345', 5)).toBe('12345');
  });
});
