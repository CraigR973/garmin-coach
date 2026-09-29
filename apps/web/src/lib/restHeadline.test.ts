import { describe, expect, it } from 'vitest';
import { restHeadline } from './restHeadline';

describe('restHeadline (Batch 294)', () => {
  it('names a no-training morning before a bike-rest one', () => {
    expect(
      restHeadline({
        requiresBikeRest: true,
        requiresTrainingRest: true,
        triggeredSignals: ['symptoms'],
        escalations: [],
      }),
    ).toEqual({
      label: 'No training today',
      line: "The symptoms you've reported rule out training today.",
    });
    expect(
      restHeadline({ requiresBikeRest: true, triggeredSignals: [], escalations: [] }),
    ).toEqual({
      label: 'Take today off the bike',
      line: 'An acute recovery signal rules out riding today.',
    });
  });

  it('says nothing on an ordinary morning or an older read', () => {
    expect(restHeadline({ requiresBikeRest: false, triggeredSignals: [], escalations: [] })).toBe(
      null,
    );
    expect(restHeadline(undefined)).toBe(null);
  });
});
