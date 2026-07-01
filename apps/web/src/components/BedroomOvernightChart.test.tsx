import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { BedroomOvernightData } from '@/hooks/useBedroomOvernight';
import { BedroomOvernightChart } from './BedroomOvernightChart';

function baseData(overrides: Partial<BedroomOvernightData> = {}): BedroomOvernightData {
  return {
    night: '2026-06-19',
    timezone: 'Europe/London',
    windowStartUtc: '2026-06-19T20:30:00Z',
    windowEndUtc: '2026-06-20T08:00:00Z',
    thresholds: { onC: 19.5, criticalC: 20.0 },
    temperature: [
      { t: '2026-06-19T22:00:00Z', c: 20.4 },
      { t: '2026-06-20T02:00:00Z', c: 19.2 },
    ],
    fan: [
      {
        t: '2026-06-19T22:05:00Z',
        on: true,
        speed: 5,
        action: 'apply',
        reason: null,
        observedTempC: 20.4,
        autoEnabled: true,
      },
    ],
    sleep: null,
    summary: {
      minTempC: 19.2,
      maxTempC: 20.4,
      fanRanMinutes: 15,
      peakSpeed: 5,
      warningMinutes: 15,
      criticalMinutes: 15,
      roomVerdict: 'amber',
    },
    nights: ['2026-06-19'],
    ...overrides,
  };
}

describe('BedroomOvernightChart', () => {
  it('renders the chart and the temp/fan legend when there is data', () => {
    render(<BedroomOvernightChart data={baseData()} />);
    expect(screen.getByTestId('overnight-chart')).toBeTruthy();
    expect(screen.getByText('Room °C')).toBeTruthy();
    expect(screen.getByText('Fan speed')).toBeTruthy();
    expect(screen.getByText(/fan on 19.5° · critical 20.0°/)).toBeTruthy();
  });

  it('shows the empty state when a night has no data', () => {
    render(<BedroomOvernightChart data={baseData({ temperature: [], fan: [] })} />);
    expect(screen.getByTestId('overnight-empty')).toBeTruthy();
    expect(screen.queryByTestId('overnight-chart')).toBeNull();
  });

  it('adds an "Asleep" legend entry only when sleep is present', () => {
    const { rerender } = render(<BedroomOvernightChart data={baseData({ sleep: null })} />);
    expect(screen.queryByText('Asleep')).toBeNull();

    rerender(
      <BedroomOvernightChart
        data={baseData({
          sleep: {
            start: '2026-06-19T22:30:00Z',
            end: '2026-06-20T06:30:00Z',
            score: 78,
            ageAdjustedScore: 82,
            durationSec: 28800,
            awakeSec: 900,
            restlessMoments: 12,
            stages: [{ start: '2026-06-19T22:30:00Z', end: '2026-06-19T23:30:00Z', stage: 'light' }],
          },
        })}
      />,
    );
    expect(screen.getByText('Asleep')).toBeTruthy();
  });

  it('explains a muted fan gap in the legend', () => {
    render(
      <BedroomOvernightChart
        data={baseData({
          fan: [
            {
              t: '2026-06-19T22:05:00Z',
              on: null,
              speed: null,
              action: 'unreachable',
              reason: null,
              observedTempC: null,
              autoEnabled: true,
            },
          ],
        })}
      />,
    );
    expect(screen.getByText('Fan unreachable')).toBeTruthy();
  });
});
