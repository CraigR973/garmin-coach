import { describe, expect, it } from 'vitest';
import {
  GRADED_AMBER_LINE,
  HELD_LABEL,
  HELD_LINE,
  LIGHT_WEEK_AMBER_LABEL,
  REST_DAY_LINE,
  gradedVerdictCopy,
  lightWeekHoldLine,
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

// Batch 298: one story on Home and the brief. Wording signed off by Craig on Mark's
// behalf, 1 Oct 2026 (docs/drafts/2026-10-01-batch-298-wording.md).
describe('one story on Home and the brief (Batch 298)', () => {
  const morning = new Date(2026, 9, 8, 7, 30);

  it('says the same Amber on Home as on the brief page', () => {
    const home = personalStatusLine('amber', 'Mark', morning, false, false, { engine: 'graded' });
    expect(home).toBe(
      'Good morning, Mark. Ease the hard work this morning; easy riding stays as planned.',
    );
    expect(home).not.toContain('Take it a bit easier');
    expect(gradedVerdictCopy('amber', false, 'graded').line).toBe(GRADED_AMBER_LINE);
    // The rollback keeps the ladder's words on Home exactly.
    expect(personalStatusLine('amber', 'Mark', morning)).toBe(
      'Good morning, Mark. Take it a bit easier this morning.',
    );
    expect(personalStatusLine('amber', 'Mark', morning, false, false, { engine: 'ladder' })).toBe(
      'Good morning, Mark. Take it a bit easier this morning.',
    );
  });

  it('says the session stands in a light week that holds it, naming the week', () => {
    const line = lightWeekHoldLine('consolidation');
    expect(line).toBe(
      "It's your consolidation week, so today's session stays as planned: hold your targets.",
    );
    expect(gradedVerdictCopy('amber', false, 'graded', 'consolidation')).toEqual({
      label: LIGHT_WEEK_AMBER_LABEL,
      line,
    });
    expect(LIGHT_WEEK_AMBER_LABEL).toBe('Ride as planned — hold your targets');
    expect(gradedVerdictCopy('green', true, 'graded', 'taper')).toEqual({
      label: HELD_LABEL,
      line: lightWeekHoldLine('taper'),
    });
    // Home's line after the greeting is the brief page's line, word for word.
    expect(
      personalStatusLine('amber', 'Mark', morning, false, false, {
        engine: 'graded',
        lightWeekHold: 'consolidation',
      }),
    ).toBe(`Good morning, Mark. ${line}`);
  });

  it('ignores a light-week hold the graded verdict did not make', () => {
    expect(gradedVerdictCopy('amber', false, 'ladder', 'consolidation')).toEqual({});
    expect(gradedVerdictCopy('green', false, 'graded', 'taper')).toEqual({});
    expect(gradedVerdictCopy('red', false, 'graded', 'taper')).toEqual({});
    expect(gradedVerdictCopy('amber', false, 'graded', null)).toEqual({ line: GRADED_AMBER_LINE });
  });

  it('keeps a rest or holiday day a rest day, whatever the colour', () => {
    expect(REST_DAY_LINE).toBe("Today's a rest day — recovery is the plan, not training.");
    expect(
      personalStatusLine('amber', 'Mark', morning, true, false, {
        engine: 'graded',
        lightWeekHold: 'consolidation',
      }),
    ).toBe(`Good morning, Mark. ${REST_DAY_LINE}`);
  });
});
