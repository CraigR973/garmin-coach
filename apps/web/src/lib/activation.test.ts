import { describe, expect, it } from 'vitest';
import { extractActivationCode } from './activation';

describe('extractActivationCode', () => {
  it('reads the code from a full activation URL', () => {
    expect(
      extractActivationCode('https://garmin-coach-one.vercel.app/activate?code=AbC-1_2'),
    ).toBe('AbC-1_2');
  });

  it('reads the code from a hash-fragment URL', () => {
    expect(extractActivationCode('https://example.test/activate#code=xyz789')).toBe('xyz789');
  });

  it('reads the code from a bare query fragment', () => {
    expect(extractActivationCode('?code=frag-code')).toBe('frag-code');
  });

  it('accepts a bare code, trimming surrounding whitespace', () => {
    expect(extractActivationCode('  AbC-1_2  ')).toBe('AbC-1_2');
  });

  it('percent-decodes a code carried in a fragment', () => {
    expect(extractActivationCode('#code=a%2Bb')).toBe('a+b');
  });

  it('returns null for blank input', () => {
    expect(extractActivationCode('   ')).toBeNull();
  });
});
