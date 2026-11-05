import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import * as words from './homeCheckInWords';
import { memoryForYou } from './coachMemory';

it('pins every new app phrase to the wording sent to Craig', () => {
  const draft = readFileSync(resolve(process.cwd(), '../../docs/drafts/2026-11-05-batch-372-wording.md'), 'utf8');
  for (const phrase of Object.values(words)) expect(draft).toContain(phrase);
});

describe('confirmed memory addresses its owner without rewriting stored facts', () => {
  it.each([
    ['Mark prefers morning rides.', 'You prefer morning rides.'],
    ['Mark is away.', 'You are away.'],
    ['Mark has a routine.', 'You have a routine.'],
    ["Mark's routine is steady.", 'Your routine is steady.'],
    ['Mark does a circuit.', 'You do a circuit.'],
    ['Mark does his circuit.', 'You do your circuit.'],
    ['Mark says “his ride was hard”.', 'You say “his ride was hard”.'],
    ['Mark watches the time.', 'You watch the time.'],
    ['Mark cycles on Tuesdays.', 'You cycle on Tuesdays.'],
    ['John prefers morning rides.', 'John prefers morning rides.'],
    ['You prefer morning rides.', 'You prefer morning rides.'],
  ])('presents %s', (statement, shown) => expect(memoryForYou(statement, 'Mark')).toBe(shown));
});
