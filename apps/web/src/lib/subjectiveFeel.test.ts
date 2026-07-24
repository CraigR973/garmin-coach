import { describe, expect, it } from 'vitest';

import { subjectiveFeelLabel } from './subjectiveFeel';

describe('subjectiveFeelLabel', () => {
  it('maps the full 0-10 score to word anchors', () => {
    expect(subjectiveFeelLabel(0)).toBe('Rough');
    expect(subjectiveFeelLabel(2)).toBe('Rough');
    expect(subjectiveFeelLabel(5)).toBe('Meh');
    expect(subjectiveFeelLabel(7)).toBe('OK');
    expect(subjectiveFeelLabel(10)).toBe('Great');
    expect(subjectiveFeelLabel(null)).toBeNull();
  });
});
