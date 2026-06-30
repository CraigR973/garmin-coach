import { describe, expect, it } from 'vitest';
import { buildChartSeries, mutedSpans } from './bedroomChart';
import { overnightGlanceText } from './dailyFlow';

type FanPoint = Parameters<typeof buildChartSeries>[1][number];

function fan(t: string, action: string, on: boolean | null, speed: number | null): FanPoint {
  return { t, action, on, speed, reason: null, observedTempC: null, autoEnabled: true };
}

describe('buildChartSeries', () => {
  it('merges temp and fan onto one sorted time axis', () => {
    const series = buildChartSeries(
      [
        { t: '2026-06-19T22:00:00Z', c: 20 },
        { t: '2026-06-20T02:00:00Z', c: 19 },
      ],
      [
        fan('2026-06-19T22:05:00Z', 'apply', true, 5),
        fan('2026-06-20T02:05:00Z', 'apply', false, null),
      ],
    );
    expect(series.map((p) => p.t)).toEqual([...series].sort((a, b) => a.t - b.t).map((p) => p.t));
    expect(series[0]).toMatchObject({ c: 20, speed: null });
    expect(series[1]).toMatchObject({ c: null, speed: 5 }); // fan on → its speed
    expect(series[3]).toMatchObject({ c: null, speed: 0 }); // fan off → 0, not a gap
  });

  it('renders muted ticks (auto_off / unreachable) as gaps, not zero', () => {
    const series = buildChartSeries(
      [],
      [fan('2026-06-19T22:05:00Z', 'auto_off', null, null)],
    );
    expect(series[0].speed).toBeNull();
  });
});

describe('mutedSpans', () => {
  it('groups contiguous muted ticks and splits on action change', () => {
    const spans = mutedSpans([
      fan('2026-06-19T22:00:00Z', 'auto_off', null, null),
      fan('2026-06-19T22:15:00Z', 'auto_off', null, null),
      fan('2026-06-19T22:30:00Z', 'unreachable', null, null),
      fan('2026-06-19T22:45:00Z', 'apply', true, 3), // ends the muted run
    ]);
    expect(spans).toHaveLength(2);
    expect(spans[0]).toMatchObject({ action: 'auto_off', label: 'Autopilot off' });
    expect(spans[1]).toMatchObject({ action: 'unreachable', label: 'Fan unreachable' });
    // The auto_off run spans its two ticks + one interval tail.
    expect(spans[0].end - spans[0].start).toBe(2 * 15 * 60 * 1000);
  });

  it('returns nothing when the fan was always actuating', () => {
    expect(mutedSpans([fan('2026-06-19T22:00:00Z', 'hold', true, 3)])).toEqual([]);
  });
});

describe('overnightGlanceText', () => {
  it('summarises room range and fan runtime', () => {
    expect(
      overnightGlanceText({ minTempC: 19.2, maxTempC: 21.4, fanRanMinutes: 210, peakSpeed: 5 }),
    ).toBe('Last night: 19→21 °C, fan ran 3.5 h (peak speed 5)');
  });

  it('says when the fan did not run', () => {
    expect(
      overnightGlanceText({ minTempC: 16, maxTempC: 18, fanRanMinutes: 0, peakSpeed: null }),
    ).toBe('Last night: 16→18 °C, fan didn\'t run');
  });

  it('is silent when there is no room data', () => {
    expect(overnightGlanceText(null)).toBeNull();
    expect(
      overnightGlanceText({ minTempC: null, maxTempC: null, fanRanMinutes: 0, peakSpeed: null }),
    ).toBeNull();
  });
});
