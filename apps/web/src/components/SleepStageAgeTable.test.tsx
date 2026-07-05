import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { SleepStageAgeTable } from '@/components/SleepStageAgeTable';

const rows = [
  {
    metricKey: 'sleep_duration_hours',
    label: 'Duration',
    value: 7.2,
    unit: ' h',
    ageAverage: 7.1,
    ageBand: '50–59',
    betterDirection: 'higher' as const,
    tone: 'neutral' as const,
    descriptor: 'About average',
  },
  {
    metricKey: 'rem_sleep_pct',
    label: 'REM',
    value: 18.2,
    unit: '%',
    ageAverage: 21,
    ageBand: '50–59',
    betterDirection: 'higher' as const,
    tone: 'warn' as const,
    descriptor: 'Below average',
  },
];

function rowFor(label: string): HTMLElement {
  return screen.getByText(label).closest('tr') as HTMLElement;
}

describe('SleepStageAgeTable', () => {
  it('renders the stage, last-night, and typical columns', () => {
    render(<SleepStageAgeTable rows={rows} ageBand="50–59" />);

    expect(screen.getByText('Stage')).toBeTruthy();
    expect(screen.getByText('Last night')).toBeTruthy();
    expect(screen.getByText('Typical')).toBeTruthy();
  });

  it('shows last-night values alongside the age-band average and descriptor', () => {
    render(<SleepStageAgeTable rows={rows} ageBand="50–59" />);

    const rem = rowFor('REM');
    expect(within(rem).getByText('18.2%')).toBeTruthy();
    expect(within(rem).getByText('21%')).toBeTruthy();
    expect(within(rem).getByText('Below average')).toBeTruthy();
    expect(screen.getByText(/50–59 age band/i)).toBeTruthy();
  });

  it('renders a fallback when sleep-stage rows are not available', () => {
    render(<SleepStageAgeTable rows={[]} ageBand="50–59" />);
    expect(screen.getByText(/fills in when the overnight sleep stages are available/i)).toBeTruthy();
  });
});
