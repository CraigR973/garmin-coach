import { describe, expect, it } from 'vitest';
import { describeProvenance, provenanceEntries } from './provenance';

// Shapes as `services/provenance.py` writes them: naive UTC timestamps, the
// packet's own third-person rule text (which the panel does not show).
const clockNight = {
  figure: 'environment.thermalReview.indoorPeakC',
  label: 'bedroom peak overnight',
  value: 21.4,
  units: '°C',
  rule: 'the highest reading inside the window — no sleep times were recorded, so the window is the clock fallback and may include hours he was awake',
  window: { kind: 'night_fallback', startUtc: null, endUtc: null, label: 'a clock window, not his sleep' },
  sources: {
    table: 'temperature_readings',
    rowsInWindow: 17,
    rowsAvailable: 41,
    firstReadingUtc: '2026-09-08T13:07:00',
    lastReadingUtc: '2026-09-09T05:00:00',
  },
  threshold: { name: 'thermal disruption', comparedAgainst: 20, units: '°C', source: 'knowledge_base' },
};

const sleptNight = {
  ...clockNight,
  value: 19.1,
  rule: 'the highest reading inside the window, from readings taken between sleep onset and wake',
  window: {
    kind: 'sleep',
    startUtc: '2026-09-14T21:00:00',
    endUtc: '2026-09-15T05:00:00',
    label: 'the night he actually slept',
  },
  sources: { ...clockNight.sources, rowsInWindow: 16, firstReadingUtc: '2026-09-14T21:05:00' },
};

const hrvFloor = {
  figure: 'verdict.acutePhysiology.hrvAcuteFloorMs',
  label: 'acute personal HRV floor',
  value: 39.63,
  units: 'ms',
  rule: "his own median over the window, minus 1.5 standard deviations of it — a personal floor, not a population band, and not Garmin's",
  window: { kind: 'rolling_days', startUtc: '2026-06-30', endUtc: '2026-09-21', label: 'the 84 days before this morning' },
  sources: {
    table: 'daily_metrics.hrv_last_night_avg_ms',
    windowDays: 84,
    stddevsBelowMedian: 1.5,
    nightsUsed: 47,
    minimumNightsRequired: 21,
    medianMs: 46,
    stddevMs: 4.25,
    enoughHistory: true,
  },
  threshold: { name: "this morning's reading against the floor", comparedAgainst: 36, units: 'ms', source: 'daily_metrics' },
};

const grading = {
  figure: 'execution.onTargetCount',
  label: 'work intervals on target',
  value: 11,
  units: 'intervals',
  rule: 'a sustained effort is graded on the average power it held across its window, not its peak',
  window: { kind: 'planned_durations', startUtc: null, endUtc: null, label: 'No reliable executed boundaries were available' },
  sources: { workIntervals: 16, onTarget: 11, over: 2, under: 3, ungraded: 0 },
  threshold: null,
};

const reviewAverage = {
  figure: 'review.thermal.avgIndoorPeakC',
  label: 'average bedroom peak this period',
  value: 18.8,
  units: '°C',
  rule: "the mean of each night's highest reading; a night with no readings is absent rather than counted as cold",
  window: { kind: 'sleep', startUtc: '2026-09-07', endUtc: '2026-09-13', label: '7 night(s) measured over his real sleep window' },
  sources: { nightsInPeriod: 7, nightsWithAPeak: 7, nightsFromSleepWindow: 7, nightsFromClockFallback: 0 },
  threshold: null,
};

const reviewDisruption = {
  ...reviewAverage,
  figure: 'review.thermal.disruptionNights',
  label: 'nights the bedroom was warm enough to disrupt sleep',
  value: 0,
  units: 'nights',
  threshold: { name: 'thermal disruption', comparedAgainst: 20, units: '°C', source: 'reviews' },
};

function row(entry: unknown, timeZone = 'Europe/London') {
  const [parsed] = provenanceEntries([entry]);
  return describeProvenance(parsed, timeZone);
}

describe('describeProvenance (Batch 273.2, the signed-off wording)', () => {
  it('names the 8–9 Sep clock window and the afternoon sample that caused the argument', () => {
    const described = row(clockNight);
    expect(described?.title).toBe('Bedroom peak overnight — 21.4 °C');
    expect(described?.lines).toEqual([
      { label: 'Readings used', text: '17 from your bedroom sensor' },
      { label: 'Window', text: '14:07 on 8 Sep → 06:00 on 9 Sep — a clock window, not your sleep' },
      {
        label: 'Rule',
        text: 'the highest reading inside the window. No sleep times were recorded for this night, so the window falls back to the clock and may include hours you were awake.',
      },
      { label: 'Compared against', text: '20.0 °C, your disruption threshold' },
    ]);
    expect(described?.warning).toBe(
      'The first reading in this window is from 14:07 — an afternoon sample, not part of your night.',
    );
  });

  it('describes a measured night in his own local times, with no warning', () => {
    const described = row(sleptNight);
    expect(described?.title).toBe('Bedroom peak overnight — 19.1 °C');
    expect(described?.lines).toContainEqual({
      label: 'Window',
      text: '22:00 → 06:00 — the night you actually slept',
    });
    expect(described?.lines).toContainEqual({
      label: 'Rule',
      text: 'the highest reading between sleep onset and wake',
    });
    expect(described?.warning).toBeUndefined();
  });

  it("says the HRV floor is his own, not a population band and not Garmin's", () => {
    const described = row(hrvFloor);
    expect(described?.title).toBe('Acute personal HRV floor — 39.6 ms');
    expect(described?.lines).toEqual([
      { label: 'Nights used', text: '47 of your own overnight readings' },
      { label: 'Window', text: 'the 84 days before this morning, excluding it' },
      {
        label: 'Rule',
        text: "your own median (46.0 ms) minus 1.5 standard deviations of it. This is your own floor, not a population band and not Garmin's.",
      },
      { label: 'This morning', text: '36 ms — below it' },
    ]);
  });

  it('states the off-the-bike line when the read carries it (Batch 294)', () => {
    const described = row({
      ...hrvFloor,
      sources: {
        ...hrvFloor.sources,
        illnessStddevsBelowMedian: 2.5,
        illnessFractionBelowMedian: 0.3,
        illnessLineMs: 34.6,
      },
    });
    expect(described?.lines).toContainEqual({
      label: 'Off the bike',
      text:
        'only at 34.6 ms or lower (2.5 standard deviations or 30% under your median), or below ' +
        "the floor together with a raised resting heart rate or a symptom you've reported.",
    });
  });

  it('says interval grades are on held average power, and where the boundaries came from', () => {
    const described = row(grading);
    expect(described?.title).toBe('Work intervals on target — 11 of 16');
    expect(described?.lines[0]).toEqual({
      label: 'Boundaries',
      text: 'the planned-duration clock (Garmin supplied no usable step laps, so a boundary can be out by a few seconds)',
    });
    expect(described?.lines[2]).toEqual({
      label: 'This session',
      text: '11 on target, 2 over, 3 under, 0 ungraded',
    });
  });

  it('explains the weekly review figures in the same shape', () => {
    expect(row(reviewAverage)?.title).toBe('Average bedroom peak — 18.8 °C');
    expect(row(reviewAverage)?.lines).toContainEqual({
      label: 'Window',
      text: '7 measured over your real sleep window, 0 over a clock window',
    });
    const disruption = row(reviewDisruption);
    expect(disruption?.title).toBe('Nights warm enough to disrupt sleep — 0');
    expect(disruption?.lines).toContainEqual({
      label: 'Compared against',
      text: '20.0 °C, your disruption threshold',
    });
  });

  it('never speaks of Mark as "he" or "his"', () => {
    for (const entry of [clockNight, sleptNight, hrvFloor, grading, reviewAverage, reviewDisruption]) {
      const described = row(entry);
      const text = [described?.title, ...(described?.lines ?? []).map((line) => line.text), described?.warning]
        .filter(Boolean)
        .join(' ');
      expect(text).not.toMatch(/\b(he|his|him)\b/i);
    }
  });

  it('skips a figure with no value, and a list entry it cannot read', () => {
    expect(row({ ...hrvFloor, value: null })).toBeNull();
    expect(provenanceEntries([{ figure: 'x' }, hrvFloor, 'nonsense'])).toHaveLength(1);
    expect(provenanceEntries(undefined)).toEqual([]);
  });
});
