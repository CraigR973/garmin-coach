import { describe, expect, it } from 'vitest';
import { ApiRequestError } from './api';
import { friendlyError } from './friendlyError';

describe('friendlyError', () => {
  it('never shows parser JSON or an upstream failure on a read', () => {
    expect(friendlyError(new Error('[{"code":"invalid_type"}]'))).toBe(
      "We couldn't load this right now. Your saved data is safe. Try again.",
    );
    expect(friendlyError(new Error('Internal Server Error'))).not.toContain('Internal Server Error');
  });

  it('does not claim a failed write was rolled back', () => {
    expect(friendlyError(new Error('Failed to fetch'), 'save')).toBe(
      "We couldn't confirm that change. Refresh before trying again.",
    );
  });

  it('keeps fixed plan safety refusals but hides untrusted API details', () => {
    const refusal = new ApiRequestError(422, 'This ride would have 72 min above 106% FTP.', true);
    expect(friendlyError(refusal, 'save', true)).toBe(refusal.message);
    expect(friendlyError(refusal, 'save')).not.toContain('72 min');
    expect(friendlyError(new ApiRequestError(422, 'body -> workSec: invalid', false), 'save', true))
      .not.toContain('workSec');
  });
});
