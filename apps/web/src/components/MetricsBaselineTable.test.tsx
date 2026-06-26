import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { MetricsBaselineTable, type MetricBaselineRow } from './MetricsBaselineTable';

describe('MetricsBaselineTable', () => {
  it('shows a friendly fallback when there are no baselines yet', () => {
    render(<MetricsBaselineTable rows={[]} />);
    expect(screen.getByText(/baselines build up as more nights sync/i)).toBeTruthy();
  });

  it('renders the current value, baseline range, and a deterministic status', () => {
    const rows: MetricBaselineRow[] = [
      // In-band → Normal
      {
        metricKey: 'hrv_7_day_avg_ms',
        label: 'HRV (7-day)',
        currentValue: 51,
        baselineMedian: 49,
        lowerQuartile: 43,
        upperQuartile: 57,
      },
      // Below band on a higher-is-better metric → flagged Low
      {
        metricKey: 'sleep_score',
        label: 'Sleep score',
        currentValue: 60,
        baselineMedian: 74,
        lowerQuartile: 72,
        upperQuartile: 78,
      },
    ];
    render(<MetricsBaselineTable rows={rows} />);

    expect(screen.getByText('HRV (7-day)')).toBeTruthy();
    expect(screen.getByText('51')).toBeTruthy();
    expect(screen.getByText('43–57')).toBeTruthy();
    expect(screen.getByText('Normal')).toBeTruthy();
    expect(screen.getByText('Low')).toBeTruthy();
  });
});
