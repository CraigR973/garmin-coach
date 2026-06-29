import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { MetricComparisonTable, type AgeComparison } from './MetricComparisonTable';
import { type MetricBaselineRow } from './MetricsBaselineTable';

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
  it('renders the three comparison columns and the age disclaimer', () => {
    render(<MetricComparisonTable rows={baselineRows} ageComparison={ageComparison} />);

    expect(screen.getByText('Last night')).toBeTruthy();
    expect(screen.getByText('vs your normal')).toBeTruthy();
    expect(screen.getByText('vs your age')).toBeTruthy();
    expect(screen.getByText(/typical 50–59 year-old/i)).toBeTruthy();
  });

  it('states both differences on the resting HR row', () => {
    render(<MetricComparisonTable rows={baselineRows} ageComparison={ageComparison} />);

    const row = rowFor('Resting HR');
    expect(within(row).getByText('48')).toBeTruthy(); // last night anchor value
    expect(within(row).getByText('in range')).toBeTruthy(); // vs your normal
    expect(within(row).getByText('23 below')).toBeTruthy(); // vs the age-group average
    expect(within(row).queryByText('—')).toBeNull(); // both frames present
  });

  it('shows the out-of-band difference and — where a frame is missing', () => {
    render(<MetricComparisonTable rows={baselineRows} ageComparison={ageComparison} />);

    const row = rowFor('Sleep score');
    expect(within(row).getByText('60')).toBeTruthy();
    expect(within(row).getByText('10 below')).toBeTruthy(); // 10 under the 70–82 band
    expect(within(row).getByText('—')).toBeTruthy(); // no age norm for sleep score
  });

  it('appends VO₂max as an age-only row with no personal baseline', () => {
    render(<MetricComparisonTable rows={baselineRows} ageComparison={ageComparison} />);

    const row = rowFor('VO₂max');
    expect(within(row).getByText('54')).toBeTruthy(); // current fitness
    expect(within(row).getByText('23 above')).toBeTruthy(); // vs the age-group average
    expect(within(row).getByText('—')).toBeTruthy(); // no "vs your normal" for VO₂max
    // The bridged age label is folded into the baseline row, not shown twice.
    expect(screen.queryByText('HRV (overnight)')).toBeNull();
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
