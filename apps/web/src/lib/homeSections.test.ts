import { describe, expect, it } from 'vitest';
import { isEveningNow, orderedSections, PRIMARY_BY_PHASE } from './homeSections';

describe('orderedSections', () => {
  it('pre-ride leads with Today, the rest collapsed in base order (no ride yet)', () => {
    expect(orderedSections('pre_ride', { hasRide: false, isEvening: false })).toEqual([
      'today',
      'lastNight',
      'tonight',
      'bedroom',
    ]);
  });

  it('post-ride leads with After your ride and keeps every section present', () => {
    expect(orderedSections('post_ride', { hasRide: true, isEvening: false })).toEqual([
      'afterRide',
      'lastNight',
      'today',
      'tomorrow',
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
    expect(orderedSections('pre_ride', { hasRide: false, isEvening: false })).not.toContain(
      'afterRide',
    );
    expect(orderedSections('rest_day', { hasRide: false, isEvening: false })).not.toContain(
      'tomorrow',
    );
  });

  it('evening floats the bedroom-prep sections up without changing which exist', () => {
    const morning = orderedSections('pre_ride', { hasRide: false, isEvening: false });
    const evening = orderedSections('pre_ride', { hasRide: false, isEvening: true });
    // Same set of sections…
    expect([...evening].sort()).toEqual([...morning].sort());
    // …but Tonight + Bedroom now sit right behind the primary, ahead of Last night.
    expect(evening).toEqual(['today', 'tonight', 'bedroom', 'lastNight']);
  });

  it('the evening nudge never displaces the primary section from the front', () => {
    const evening = orderedSections('rest_day', { hasRide: false, isEvening: true });
    expect(evening[0]).toBe('lastNight'); // primary stays first
    expect(evening).toEqual(['lastNight', 'tonight', 'bedroom', 'today']);
  });

  it('maps each state to its primary section', () => {
    expect(PRIMARY_BY_PHASE).toEqual({
      pre_ride: 'today',
      post_ride: 'afterRide',
      rest_day: 'lastNight',
    });
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
