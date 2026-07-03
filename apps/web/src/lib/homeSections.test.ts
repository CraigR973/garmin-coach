import { describe, expect, it } from 'vitest';
import { isEveningNow, orderedSections, primarySection } from './homeSections';

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

describe('isEveningNow', () => {
  it('is true at/after 20:00 local and false before', () => {
    expect(isEveningNow(new Date('2026-06-20T19:59:00'))).toBe(false);
    expect(isEveningNow(new Date('2026-06-20T20:00:00'))).toBe(true);
    expect(isEveningNow(new Date('2026-06-20T23:30:00'))).toBe(true);
    expect(isEveningNow(new Date('2026-06-20T06:00:00'))).toBe(false);
  });
});
