import { describe, expect, it } from 'vitest';
import { SYMPTOM_NOTICES, SYMPTOM_OPTIONS, symptomNotice } from './symptoms';

describe('symptom notices (Batch 301)', () => {
  it('words a notice for every answer that sets a floor, and none for None', () => {
    // The question's order, less None. The text itself is pinned to the server's
    // SYMPTOM_FLOORS by apps/api/tests/test_batch_301_symptom_notice_parity.py.
    expect(Object.keys(SYMPTOM_NOTICES)).toEqual(
      SYMPTOM_OPTIONS.map((option) => option.value).filter((value) => value !== 'none'),
    );
    expect(symptomNotice('none')).toBeNull();
  });

  it('reads no answer as no notice, never as None or as a symptom', () => {
    expect(symptomNotice(null)).toBeNull();
    expect(symptomNotice(undefined)).toBeNull();
  });

  it('takes the rest heading for chest and fever, and the capped heading for a cold', () => {
    expect(symptomNotice('chest_heart')?.level).toBe('rest');
    expect(symptomNotice('fever_aches')?.level).toBe('rest');
    expect(symptomNotice('head_cold')?.level).toBe('ease');
    expect(symptomNotice('chest_heart')?.notice).toMatch(/call 999\.$/);
  });
});
