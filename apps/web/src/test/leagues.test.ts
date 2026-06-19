import { describe, it, expect } from 'vitest';
import { privacyLabel, PRIVACY_LABELS } from '@/lib/leagues';

describe('privacyLabel helper', () => {
  it('returns "Public" for public_open', () => {
    expect(privacyLabel('public_open')).toBe('Public');
  });

  it('returns "Public · request to join" for public_request', () => {
    expect(privacyLabel('public_request')).toBe('Public · request to join');
  });

  it('returns "Private" for private', () => {
    expect(privacyLabel('private')).toBe('Private');
  });

  it('returns empty string for unknown / stale values (open, request)', () => {
    expect(privacyLabel('open')).toBe('');
    expect(privacyLabel('request')).toBe('');
    expect(privacyLabel('')).toBe('');
  });

  it('PRIVACY_LABELS covers all three real enum values', () => {
    const keys = Object.keys(PRIVACY_LABELS);
    expect(keys).toContain('public_open');
    expect(keys).toContain('public_request');
    expect(keys).toContain('private');
    expect(keys).toHaveLength(3);
  });
});
