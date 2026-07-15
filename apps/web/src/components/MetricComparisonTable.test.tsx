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

  it('shows the baseline range and the explicit status cue in the third column, tinting an in-band number green', () => {
    render(<MetricComparisonTable rows={baselineRows} ageComparison={ageComparison} />);

    const row = rowFor('Resting HR');
    const value = within(row).getByText('48'); // last night anchor value
    expect(value.className).toContain('text-success'); // 48 sits inside the 46–53 band
    expect(within(row).getByText('46–53')).toBeTruthy(); // personal-baseline range
    expect(within(row).getByText('in range')).toBeTruthy(); // restored explicit status
    expect(within(row).getByText(/23 below for your age/)).toBeTruthy(); // vs the age-group average
  });

  it('tints an out-of-band number amber and shows no age descriptor when there is no age frame', () => {
    render(<MetricComparisonTable rows={baselineRows} ageComparison={ageComparison} />);

    const row = rowFor('Sleep score');
    const value = within(row).getByText('60');
    expect(value.className).toContain('text-warning'); // 60 sits below the 70–82 band
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
    expect(value.className).toContain('text-success');
    const status = within(row).getByText(/2 below/);
    expect(status.className).toContain('text-success');
  });

  it('surfaces the HRV/SpO₂ reliability footnote when nights were excluded', () => {
    render(<MetricComparisonTable rows={baselineRows} ageComparison={ageComparison} />);
    expect(screen.getByText(/strap was re-fitted/i)).toBeTruthy();
  });

  it('renders a fallback when there is no history yet', () => {
    render(<MetricComparisonTable rows={[]} ageComparison={{ rows: [] }} />);
    expect(screen.getByText(/fills in as more nights sync/i)).toBeTruthy();
  });
});
