import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import {
  MetricComparisonTable,
  type AgeComparison,
  type MetricBaselineRow,
} from './MetricComparisonTable';

const baselineRows: MetricBaselineRow[] = [
  {
    metricKey: 'sleep_score',
    label: 'Sleep score',
    currentValue: 60, // below the band -> a "below" verdict
    baselineMedian: 74,
    lowerQuartile: 70,
    upperQuartile: 82,
  },
  {
    metricKey: 'resting_heart_rate_bpm',
    label: 'Resting HR',
    currentValue: 48,
    baselineMedian: 50,
    lowerQuartile: 46,
    upperQuartile: 53,
  },
  {
    metricKey: 'hrv_7_day_avg_ms',
    label: 'HRV (7-day)',
    currentValue: 50,
    baselineMedian: 49,
    lowerQuartile: 43,
    upperQuartile: 57,
    excludedSampleCount: 70,
    reliabilityStartDate: '2026-06-11',
  },
];

const ageComparison: AgeComparison = {
  age: 57,
  ageBand: '50–59',
  fitnessAge: 42,
  fitnessAgeDelta: 15,
  fitnessAgeTone: 'good',
  rows: [
    {
      metricKey: 'resting_heart_rate_bpm',
      label: 'Resting HR',
      value: 48,
      unit: ' bpm',
      ageAverage: 71,
      ageBand: '50–59',
      betterDirection: 'lower',
      tone: 'good',
      descriptor: 'Better than average',
    },
    {
      metricKey: 'hrv_overnight_ms',
      label: 'HRV (overnight)',
      value: 50,
      unit: ' ms',
      ageAverage: 30,
      ageBand: '50–59',
      betterDirection: 'higher',
      tone: 'good',
      descriptor: 'Better than average',
    },
    {
      metricKey: 'vo2max',
      label: 'VO₂max',
      value: 54,
      unit: '',
      ageAverage: 31,
      ageBand: '50–59',
      betterDirection: 'higher',
      tone: 'good',
      descriptor: 'Much better than average',
    },
  ],
};

function rowFor(label: string): HTMLElement {
  return screen.getByText(label).closest('tr') as HTMLElement;
}

describe('MetricComparisonTable', () => {
  it('renders an explicit status column beside metric and last-night (Batch 122)', () => {
    render(<MetricComparisonTable rows={baselineRows} ageComparison={ageComparison} />);

    expect(screen.getByText('Last night')).toBeTruthy();
    expect(screen.getByText('Status')).toBeTruthy();
    expect(screen.queryByText('vs your age')).toBeNull(); // no longer its own column
    expect(screen.queryByText('vs your normal')).toBeNull(); // dropped in Batch 35
    expect(screen.getByText(/typical 50–59 year-old/i)).toBeTruthy();
  });

  it('keeps meaning-bearing table copy at the raised readable floor (Batch 127)', () => {
    render(<MetricComparisonTable rows={baselineRows} ageComparison={ageComparison} />);

    const status = screen.getByText(/23 below for your age/);
    const ageNote = screen.getByText(/general-population average for/i);
    const reliabilityNote = screen.getByText(/strap was re-fitted/i);

    expect(status.className).toContain('text-sm');
    expect(ageNote.className).toContain('text-sm');
    expect(reliabilityNote.className).toContain('text-sm');
  });

  it('shows the baseline range and the explicit status cue in the third column, tinting an in-band number green', () => {
    render(<MetricComparisonTable rows={baselineRows} ageComparison={ageComparison} />);

    const row = rowFor('Resting HR');
    const value = within(row).getByText('48'); // last night anchor value
    expect(value.className).toContain('text-success-text'); // 48 sits inside the 46–53 band
    expect(within(row).getByText('46–53')).toBeTruthy(); // personal-baseline range
    expect(within(row).getByText('in range')).toBeTruthy(); // restored explicit status
    expect(within(row).getByText(/23 below for your age/)).toBeTruthy(); // vs the age-group average
  });

  it('tints an out-of-band number amber and shows no age descriptor when there is no age frame', () => {
    render(<MetricComparisonTable rows={baselineRows} ageComparison={ageComparison} />);

    const row = rowFor('Sleep score');
    const value = within(row).getByText('60');
    expect(value.className).toContain('text-warning-text'); // 60 sits below the 70–82 band
    expect(within(row).getByText('70–82')).toBeTruthy();
    expect(within(row).getByText(/10 below/)).toBeTruthy();
    expect(within(row).queryByText(/for your age/)).toBeNull(); // no age norm for sleep score, no empty-dash clutter
  });

  it('appends VO₂max as an age-only row with no baseline range and a neutral tint', () => {
    render(<MetricComparisonTable rows={baselineRows} ageComparison={ageComparison} />);

    const row = rowFor('VO₂max');
    const value = within(row).getByText('54'); // current fitness
    expect(value.className).toContain('text-text-primary'); // no band → neutral, not tinted
    expect(within(row).queryByText(/70–82|46–53|43–57/)).toBeNull();
    expect(within(row).getByText('—')).toBeTruthy();
    expect(within(row).getByText(/23 above for your age/)).toBeTruthy(); // vs the age-group average
    // The bridged age label is folded into the baseline row, not shown twice.
    expect(screen.queryByText('HRV (overnight)')).toBeNull();
  });

  it('keeps the status green when a lower-is-better metric lands outside the band in the good direction', () => {
    const lowerIsBetterRows = baselineRows.map((row) =>
      row.metricKey === 'resting_heart_rate_bpm' ? { ...row, currentValue: 44 } : row,
    );

    render(<MetricComparisonTable rows={lowerIsBetterRows} ageComparison={ageComparison} />);

    const row = rowFor('Resting HR');
    const value = within(row).getByText('44');
    expect(value.className).toContain('text-success-text');
    const status = within(row).getByText(/2 below/);
    expect(status.className).toContain('text-success-text');
  });

  it('keeps readiness green when it lands above the personal baseline (higher-is-better)', () => {
    // Batch 129: readiness_score is emitted as a baseline row but was missing from the
    // higher-is-better set, so an above-normal (good) readiness rendered as an amber ⚠.
    const rows: MetricBaselineRow[] = [
      {
        metricKey: 'readiness_score',
        label: 'Readiness',
        currentValue: 88,
        baselineMedian: 70,
        lowerQuartile: 62,
        upperQuartile: 78,
      },
    ];
    render(<MetricComparisonTable rows={rows} ageComparison={{ rows: [] }} />);

    const row = rowFor('Readiness');
    expect(within(row).getByText('88').className).toContain('text-success-text');
    const status = within(row).getByText(/10 above/);
    expect(status.className).toContain('text-success-text');
  });

  it('flags overnight respiration amber when it rises above the baseline, green when it falls below', () => {
    // Batch 129: average_respiration is a concern when elevated (stress/illness), fine when low.
    const high: MetricBaselineRow[] = [
      { metricKey: 'average_respiration', label: 'Respiration', currentValue: 16, baselineMedian: 12, lowerQuartile: 11, upperQuartile: 13 },
    ];
    const { unmount } = render(<MetricComparisonTable rows={high} ageComparison={{ rows: [] }} />);
    expect(within(rowFor('Respiration')).getByText('16').className).toContain('text-warning-text');
    expect(within(rowFor('Respiration')).getByText(/3 above/).className).toContain('text-warning-text');
    unmount();

    const low: MetricBaselineRow[] = [
      { metricKey: 'average_respiration', label: 'Respiration', currentValue: 9, baselineMedian: 12, lowerQuartile: 11, upperQuartile: 13 },
    ];
    render(<MetricComparisonTable rows={low} ageComparison={{ rows: [] }} />);
    expect(within(rowFor('Respiration')).getByText('9').className).toContain('text-success-text');
    expect(within(rowFor('Respiration')).getByText(/2 below/).className).toContain('text-success-text');
  });

  it('surfaces the HRV/SpO₂ reliability footnote when nights were excluded', () => {
    render(<MetricComparisonTable rows={baselineRows} ageComparison={ageComparison} />);
    expect(screen.getByText(/strap was re-fitted/i)).toBeTruthy();
  });

  it('shows the morning charge basis and explains drain without a false full-day comparison', () => {
    const rows: MetricBaselineRow[] = [
      {
        metricKey: 'body_battery_charge',
        label: 'Body Battery charge',
        currentValue: 69,
        baselineMedian: 68,
        lowerQuartile: 59.5,
        upperQuartile: 72,
        basis: "Garmin's overnight charge accumulated from midnight to this morning's sync.",
      },
      {
        metricKey: 'body_battery_drain',
        label: 'Body Battery drain',
        currentValue: null,
        baselineMedian: 67,
        lowerQuartile: 57.5,
        upperQuartile: 75,
        unavailableReason:
          'This drain is still a part-day value at the morning sync; compare it with your full-day baseline after the day closes.',
      },
    ];

    render(<MetricComparisonTable rows={rows} ageComparison={{ rows: [] }} />);

    const charge = rowFor('Body Battery charge');
    expect(within(charge).getByText('69')).toBeTruthy();
    expect(within(charge).getByText(/overnight charge accumulated from midnight/i)).toBeTruthy();

    const drain = rowFor('Body Battery drain');
    expect(within(drain).getByText('—')).toBeTruthy();
    expect(within(drain).getByText(/still a part-day value/i)).toBeTruthy();
    expect(within(drain).queryByText('57.5–75')).toBeNull();
  });

  it('renders a fallback when there is no history yet', () => {
    render(<MetricComparisonTable rows={[]} ageComparison={{ rows: [] }} />);
    expect(screen.getByText(/fills in as more nights sync/i)).toBeTruthy();
  });

  // --- Batch 230.6: the tolerance stops claiming membership of a printed range
  //
  // Mark's 2026-08-26 table: HRV current 50, printed range 45–49, centre 47, so
  // tol = max(47 × 0.03, 0.5) = 1.41 and the real bound is 50.41. The row read
  // "in range" — a claim he could disprove by looking at it. The next morning
  // HRV 51 against the same printed range read "2 above". Same range, one point
  // apart, opposite verdicts, with the boundary between them invisible.
  describe('the near-miss band (Batch 230)', () => {
    const hrv = (currentValue: number): MetricBaselineRow[] => [
      {
        metricKey: 'hrv_7_day_avg_ms',
        label: 'HRV (7-day)',
        currentValue,
        baselineMedian: 47,
        lowerQuartile: 45,
        upperQuartile: 49,
      },
    ];

    it('still reads "in range" strictly inside the printed range', () => {
      render(<MetricComparisonTable rows={hrv(49)} ageComparison={{ rows: [] }} />);
      const row = rowFor('HRV (7-day)');
      expect(within(row).getByText('45–49')).toBeTruthy();
      expect(within(row).getByText('in range')).toBeTruthy();
    });

    it('names the near-miss instead of claiming a range the value is outside', () => {
      render(<MetricComparisonTable rows={hrv(50)} ageComparison={{ rows: [] }} />);
      const row = rowFor('HRV (7-day)');
      // The printed range is still his quartile range — the subtraction he can do.
      expect(within(row).getByText('45–49')).toBeTruthy();
      expect(within(row).queryByText('in range')).toBeNull();
      expect(within(row).getByText('just above, still typical')).toBeTruthy();
      // Not a deviation, so the number stays green.
      expect(within(row).getByText('50').className).toContain('text-success-text');
    });

    it('names a near-miss below the range too', () => {
      render(<MetricComparisonTable rows={hrv(44)} ageComparison={{ rows: [] }} />);
      const row = rowFor('HRV (7-day)');
      expect(within(row).getByText('just below, still typical')).toBeTruthy();
    });

    it('measures the deviation from the printed quartile, not the hidden bound', () => {
      // 51 is past 49 + 1.41, so it is a real deviation — and "2 above" is
      // 51 − 49, which reconciles against the range on the same line. Measuring
      // from the tolerance bound instead would print 0.6 and reconcile with
      // nothing the table shows.
      render(<MetricComparisonTable rows={hrv(51)} ageComparison={{ rows: [] }} />);
      const row = rowFor('HRV (7-day)');
      expect(within(row).getByText('2 above')).toBeTruthy();
    });
  });

  // --- Batch 230.1: the population frame reaches every surface
  //
  // REM's age row lives in `ageComparison.sleepRows` and renders in
  // `SleepStageAgeTable`, which is on `/sleep` only — so on the brief and on Home
  // REM was the one age-normed metric shown with no band at all: "✓ in range",
  // full stop, on a night 5 points under the 15–23% floor.
  it('states REM against its age band as well as his own range (Batch 230)', () => {
    const rem: MetricBaselineRow[] = [
      {
        metricKey: 'rem_sleep_pct',
        label: 'REM sleep',
        currentValue: 9.8,
        baselineMedian: 9.9,
        lowerQuartile: 7.5,
        upperQuartile: 13.1,
        basis: '% of measured sleep — deep + light + REM + awake',
        ageFrame: {
          ageBand: '50–59',
          bandLow: 15,
          bandHigh: 23,
          unit: '%',
          tone: 'warn',
          descriptor: 'Below the healthy range for your age',
        },
      },
    ];
    render(<MetricComparisonTable rows={rem} ageComparison={{ rows: [] }} />);

    const row = rowFor('REM sleep');
    // Normal for him...
    expect(within(row).getByText('7.5–13.1%')).toBeTruthy();
    expect(within(row).getByText('in range')).toBeTruthy();
    // ...and below the band, on the same row, with the band's own numbers.
    expect(within(row).getByText(/Below the healthy range for your age \(15–23%\)/)).toBeTruthy();
    // And which total the percentage is a percentage of.
    expect(within(row).getByText(/% of measured sleep/)).toBeTruthy();
    // The age footnote appears for a frame that never came through `rows`.
    expect(screen.getByText(/general-population average for/i)).toBeTruthy();
  });
});
