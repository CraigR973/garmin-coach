import { describe, expect, it } from 'vitest';
import {
  GRADED_AMBER_LINE,
  HELD_LABEL,
  HELD_LINE,
  gradedVerdictCopy,
  personalStatusLine,
  verdictCopy,
} from './copy';

// Batch 296: the headline when the colour came from the graded verdict. Wording signed
// off by Craig on Mark's behalf, 29 Sep 2026.
describe('graded verdict copy (Batch 296)', () => {
  it('gives Green with the targets held its own headline and line', () => {
    expect(gradedVerdictCopy('green', true, 'graded')).toEqual({
      label: 'Good to go — hold your targets',
      line: 'One thing is a little off: ride as planned, and hold your targets rather than pushing past them.',
    });
    expect(HELD_LABEL).toBe('Good to go — hold your targets');
    expect(HELD_LINE).toContain('hold your targets');
  });

  it('eases only the hard work on a graded Amber', () => {
    expect(gradedVerdictCopy('amber', false, 'graded')).toEqual({ line: GRADED_AMBER_LINE });
    expect(GRADED_AMBER_LINE).toBe('Ease the hard work; easy riding stays as planned.');
  });

  it('leaves a read the ladder decided on the defaults', () => {
    // A read stored before the switch has no engine and is never held.
    expect(gradedVerdictCopy('amber', undefined, undefined)).toEqual({});
    expect(gradedVerdictCopy('amber', false, 'ladder')).toEqual({});
    expect(gradedVerdictCopy('green', false, 'graded')).toEqual({});
    expect(gradedVerdictCopy('red', false, 'graded')).toEqual({});
    expect(verdictCopy.amber.line).toBe('Ease back — shorter, and drop the hard stuff.');
  });

  it("says ride as planned and hold the targets on Home's greeting line", () => {
    const morning = new Date(2026, 9, 7, 7, 30);
    expect(personalStatusLine('green', 'Mark', morning, false, true)).toBe(
      'Good morning, Mark. Ride as planned this morning, and hold your targets.',
    );
    expect(personalStatusLine('green', 'Mark', morning)).toBe(
      "Good morning, Mark. You're good to go this morning.",
    );
    // A rest day still reads as a rest day, held or not.
    expect(personalStatusLine('green', 'Mark', morning, true, true)).toContain('rest day');
  });
});
