import { describe, expect, it } from 'vitest';
import {
  isEveningNow,
  orderedSections,
  primarySection,
  sectionLane,
  splitPrimaryDetail,
} from './homeSections';

describe('orderedSections', () => {
  it('pre-training leads with Today, the rest collapsed in base order (no ride yet)', () => {
    expect(orderedSections('pre_training', { hasRide: false, isEvening: false })).toEqual([
      'today',
      'lastNight',
      'tonight',
      'bedroom',
    ]);
  });

  it('post-training after a ride leads with After your ride and keeps every section present', () => {
    expect(orderedSections('post_training', { hasRide: true, isEvening: false })).toEqual([
      'afterRide',
      'lastNight',
      'today',
      'tomorrow',
      'tonight',
      'bedroom',
    ]);
  });

  it('post-training on a non-ride day leads with Today (the read renders there)', () => {
    // A strength/walk/flexibility-only day advances to post_training but has no
    // afterRide section — its read lives inside the Today card.
    expect(orderedSections('post_training', { hasRide: false, isEvening: false })).toEqual([
      'today',
      'lastNight',
      'tonight',
      'bedroom',
    ]);
  });

  it('rest day leads with Last night', () => {
    expect(orderedSections('rest_day', { hasRide: false, isEvening: false })).toEqual([
      'lastNight',
      'today',
      'tonight',
      'bedroom',
    ]);
  });

  it('gates the ride-only sections on a ride existing, never on phase', () => {
    // afterRide/tomorrow are absent only because no ride was analysed — not hidden.
    expect(orderedSections('pre_training', { hasRide: false, isEvening: false })).not.toContain(
      'afterRide',
    );
    expect(orderedSections('rest_day', { hasRide: false, isEvening: false })).not.toContain(
      'tomorrow',
    );
  });

  it('the evening wind_down phase leads with Tonight and floats Bedroom up behind it', () => {
    const daytime = orderedSections('pre_training', { hasRide: false, isEvening: false });
    const evening = orderedSections('wind_down', { hasRide: false, isEvening: true });
    // Same set of sections…
    expect([...evening].sort()).toEqual([...daytime].sort());
    // …but Tonight + Bedroom now lead, ahead of the daytime sections.
    expect(evening).toEqual(['tonight', 'bedroom', 'lastNight', 'today']);
  });

  it('wind_down keeps the ride-only sections present when a ride was analysed', () => {
    expect(orderedSections('wind_down', { hasRide: true, isEvening: true })).toEqual([
      'tonight',
      'bedroom',
      'lastNight',
      'today',
      'afterRide',
      'tomorrow',
    ]);
  });

  it('leads with an explicit primary override instead of the phase primary (Batch 50)', () => {
    // post_training + hasRide would phase-lead with After-your-ride, but an
    // action override for `today` (a pending coach change) makes Today lead.
    expect(
      orderedSections('post_training', { hasRide: true, isEvening: false, primary: 'today' }),
    ).toEqual(['today', 'lastNight', 'afterRide', 'tomorrow', 'tonight', 'bedroom']);
  });

  it('falls back to the phase primary when no override is passed', () => {
    expect(orderedSections('post_training', { hasRide: true, isEvening: false })).toEqual([
      'afterRide',
      'lastNight',
      'today',
      'tomorrow',
      'tonight',
      'bedroom',
    ]);
  });

  it('an override still respects the evening float (Tonight + Bedroom behind the lead)', () => {
    expect(
      orderedSections('wind_down', { hasRide: false, isEvening: true, primary: 'today' }),
    ).toEqual(['today', 'tonight', 'bedroom', 'lastNight']);
  });
});

describe('primarySection', () => {
  it('maps each phase to its primary section', () => {
    expect(primarySection('pre_training', { hasRide: false })).toBe('today');
    expect(primarySection('rest_day', { hasRide: false })).toBe('lastNight');
    expect(primarySection('wind_down', { hasRide: false })).toBe('tonight');
  });

  it('post_training leads with After your ride only when a ride was analysed', () => {
    expect(primarySection('post_training', { hasRide: true })).toBe('afterRide');
    expect(primarySection('post_training', { hasRide: false })).toBe('today');
  });
});

describe('sectionLane (Batch 51 — desktop two-column)', () => {
  it('puts Today, After your ride, and Tomorrow in the act lane', () => {
    expect(sectionLane('today')).toBe('act');
    expect(sectionLane('afterRide')).toBe('act');
    expect(sectionLane('tomorrow')).toBe('act');
  });

  it('puts Last night, Tonight, and Bedroom in the context lane', () => {
    expect(sectionLane('lastNight')).toBe('context');
    expect(sectionLane('tonight')).toBe('context');
    expect(sectionLane('bedroom')).toBe('context');
  });
});

describe('splitPrimaryDetail (Batch 54 — "More detail" grouping)', () => {
  it('splits the lead section from the receding rest, preserving order', () => {
    const order = orderedSections('pre_training', { hasRide: false, isEvening: false });
    expect(splitPrimaryDetail(order, 'today')).toEqual({
      lead: 'today',
      detail: ['lastNight', 'tonight', 'bedroom'],
    });
  });

  it('keeps the evening float and Batch 51 lanes intact — detail is just "order minus lead"', () => {
    const order = orderedSections('wind_down', { hasRide: true, isEvening: true });
    expect(splitPrimaryDetail(order, 'tonight')).toEqual({
      lead: 'tonight',
      detail: ['bedroom', 'lastNight', 'today', 'afterRide', 'tomorrow'],
    });
  });

  it('respects an action-override primary the same as the phase primary', () => {
    const order = orderedSections('post_training', { hasRide: true, isEvening: false, primary: 'today' });
    expect(splitPrimaryDetail(order, 'today')).toEqual({
      lead: 'today',
      detail: ['lastNight', 'afterRide', 'tomorrow', 'tonight', 'bedroom'],
    });
  });

  it('treats every section as detail (no lead) if the given primary is absent from order', () => {
    const order = orderedSections('pre_training', { hasRide: false, isEvening: false });
    expect(splitPrimaryDetail(order, 'afterRide')).toEqual({ lead: null, detail: order });
  });
});

describe('isEveningNow', () => {
  it('is true at/after 20:00 local and false before', () => {
    expect(isEveningNow(new Date('2026-06-20T19:59:00'))).toBe(false);
    expect(isEveningNow(new Date('2026-06-20T20:00:00'))).toBe(true);
    expect(isEveningNow(new Date('2026-06-20T23:30:00'))).toBe(true);
    expect(isEveningNow(new Date('2026-06-20T06:00:00'))).toBe(false);
  });
});
