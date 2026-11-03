import { describe, expect, it } from 'vitest';

import { remContext, remContextShort, sleepQualifierLabel } from './dailyFlow';

/**
 * Batch 253 (UX241-08). Home's collapsed "Last night's sleep" line read
 * `7h 42m asleep · FAIR · REM below your 65–9…` — three problems in eleven words.
 * It is the first thing Mark sees about last night, before he expands anything.
 */
describe("Home's sleep summary", () => {
  it('says the grade in the app’s voice, not Garmin’s raw enum', () => {
    expect(sleepQualifierLabel('FAIR')).toBe('Fair');
    expect(sleepQualifierLabel('EXCELLENT')).toBe('Excellent');
    expect(sleepQualifierLabel('good')).toBe('Good');
    expect(sleepQualifierLabel('POOR')).toBe('Poor');
  });

  it('sentence-cases a grade it has never seen rather than shouting it', () => {
    expect(sleepQualifierLabel('SOMETHING_NEW')).toBe('Something new');
  });

  it('has nothing to say when Garmin sent no grade', () => {
    expect(sleepQualifierLabel(null)).toBeNull();
    expect(sleepQualifierLabel('')).toBeNull();
    expect(sleepQualifierLabel('   ')).toBeNull();
  });

  it('gives his minutes and their share of the night, never a range that is not his', () => {
    // Batch 369.3: "65–90" was not his range; his own usual is on the Sleep page.
    const night = 7 * 3600;
    expect(remContextShort(46 * 60, night)).toBe('REM 46m (11%)');
    expect(remContextShort(46 * 60)).toBe('REM 46m');
    expect(remContext(46 * 60, night)).toBe('46 min, 11% of the night');
    expect(`${remContextShort(120 * 60, night)} ${remContext(120 * 60, night)}`).not.toMatch(
      /65–90|below|above|range/,
    );
  });

  it('is materially shorter than the sentence it replaces on the summary line', () => {
    const short = remContextShort(34 * 60, 7 * 3600) ?? '';
    const long = `REM ${remContext(34 * 60, 7 * 3600)}`;
    expect(short.length).toBeLessThan(long.length);
    expect(`7h 42m asleep · Fair · ${short}`.length).toBeLessThan(45);
  });

  it('says nothing when REM did not sync', () => {
    expect(remContextShort(null)).toBeNull();
    expect(remContextShort(undefined)).toBeNull();
  });
});
