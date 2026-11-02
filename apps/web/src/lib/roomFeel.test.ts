import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { bedroomOvernightSchema } from '@coach/shared';
import { ROOM_FEEL_LABEL, chartLinesLegend, roomFeelVariant } from './roomFeel';

describe('the bedroom on Batch 366 lines (Batch 376)', () => {
  it('never says critical or a colour word', () => {
    const words = [...Object.values(ROOM_FEEL_LABEL), chartLinesLegend(18, 24)].join(' ');
    expect(words).not.toMatch(/critical|red|amber|green/i);
    expect(roomFeelVariant('comfortable')).toBe('success');
    expect(roomFeelVariant('cold')).toBe('warning');
  });

  it('an older API without the new fields still parses, with 18 and 24 lines', () => {
    const parsed = bedroomOvernightSchema.shape.thresholds.parse({ onC: 19.5, criticalC: 20 });
    expect([parsed.coldC, parsed.warmC]).toEqual([18, 24]);
  });

  it('every label is in the signed-off draft', () => {
    const draft = readFileSync(
      resolve(__dirname, '../../../../docs/drafts/2026-11-03-batch-376-wording.md'),
      'utf8',
    );
    for (const line of [...Object.values(ROOM_FEEL_LABEL), chartLinesLegend(18, 24)]) {
      expect(draft).toContain(line);
    }
  });
});
