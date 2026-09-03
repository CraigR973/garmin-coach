import { cleanup, render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { SleepStageAgeTable } from '@/components/SleepStageAgeTable';

const rows = [
  {
    metricKey: 'sleep_duration_hours',
    label: 'Duration',
    value: 7.2,
    unit: ' h',
    ageAverage: 7.1,
    bandLow: 6.5,
    bandHigh: 8,
    ageBand: '50–59',
    betterDirection: 'higher' as const,
    tone: 'good' as const,
    descriptor: 'Healthy for your age',
  },
  {
    metricKey: 'rem_sleep_pct',
    label: 'REM',
    value: 18.2,
    unit: '%',
    ageAverage: 19,
    bandLow: 15,
    bandHigh: 23,
    garminTargetLow: 21,
    garminTargetHigh: 31,
    ageBand: '50–59',
    betterDirection: 'higher' as const,
    tone: 'good' as const,
    descriptor: 'Healthy for your age',
  },
];

function rowFor(label: string): HTMLElement {
  return screen.getByText(label).closest('tr') as HTMLElement;
}

describe('SleepStageAgeTable', () => {
  it('renders the stage, last-night, and healthy-range columns', () => {
    render(<SleepStageAgeTable rows={rows} ageBand="50–59" />);

    expect(screen.getByText('Stage')).toBeTruthy();
    expect(screen.getByText('Last night')).toBeTruthy();
    expect(screen.getByText('Healthy range (50–59)')).toBeTruthy();
    expect(screen.queryByText('Typical')).toBeNull();
  });

  it('shows last-night values alongside the age-band range and descriptor', () => {
    render(<SleepStageAgeTable rows={rows} ageBand="50–59" />);

    const rem = rowFor('REM');
    expect(within(rem).getByText('18.2%')).toBeTruthy();
    expect(within(rem).getByText('15–23%')).toBeTruthy();
    expect(within(rem).getByText('Healthy for your age')).toBeTruthy();
    expect(screen.getByText(/50–59 age band/i)).toBeTruthy();
  });

  it('keeps Garmin young-adult targets as a quiet contrast below the table', () => {
    render(<SleepStageAgeTable rows={rows} ageBand="50–59" />);

    expect(screen.getByText('Garmin target contrast')).toBeTruthy();
    expect(screen.getByText(/REM: healthy 50–59 15–23%; Garmin target 21–31%/)).toBeTruthy();
  });

  it('shows a dash, not a stray average, for a descriptive-only row like Restless', () => {
    const withRestless = [
      ...rows,
      {
        metricKey: 'restless_moments_count',
        label: 'Restless',
        value: 45,
        unit: '',
        ageAverage: null,
        ageBand: '50–59',
        betterDirection: 'lower' as const,
        tone: 'neutral' as const,
        descriptor: 'Shown for context — no age range',
      },
    ];
    render(<SleepStageAgeTable rows={withRestless} ageBand="50–59" />);

    const restless = rowFor('Restless');
    expect(within(restless).getByText('45')).toBeTruthy(); // last night is still shown
    expect(within(restless).getByText('—')).toBeTruthy(); // no misleading "healthy range"
    expect(within(restless).queryByText('13')).toBeNull(); // the stray average is gone
    expect(within(restless).getByText(/Shown for context/i)).toBeTruthy();
  });

  it('cites the age-norm source in the footnote', () => {
    render(<SleepStageAgeTable rows={rows} ageBand="50–59" />);
    expect(screen.getByText(/Ohayon et al\., 2004/)).toBeTruthy();
  });

  it('says which total the stage percentages are shares of (Batch 230)', () => {
    // Mark's watch shows stage minutes against a Duration that excludes time
    // awake; these percentages include it. Without the note none of the four
    // divides into anything on his screen \u2014 48 min of a shown 7h33m is 10.6%,
    // and the app says 9.8%.
    const basis =
      'Stage percentages are shares of measured sleep \u2014 deep + light + REM + awake \u2014 so they include time awake in bed.';
    render(<SleepStageAgeTable rows={rows} ageBand="50\u201359" stagePctBasis={basis} />);
    expect(screen.getByText(/shares of measured sleep/i)).toBeTruthy();

    // Absent on a stored pre-230 read, and the table still renders.
    cleanup();
    render(<SleepStageAgeTable rows={rows} ageBand="50\u201359" />);
    expect(screen.queryByText(/shares of measured sleep/i)).toBeNull();
    expect(screen.getByText(/Ohayon et al\., 2004/)).toBeTruthy();
  });

  it('states the band\'s own denominator beside the values it judges (Batch 250)', () => {
    // HS240-14: Ohayon's percentages are shares of total sleep time; these values
    // are shares of measured sleep, which also includes time awake in bed. The
    // band therefore sits high by 0.8 points for REM and 4.7 for light, so a
    // value just under a floor is nearer it than the table makes it look.
    const bandBasis =
      'The age bands are Ohayon et al. 2004 polysomnography percentages of total sleep time.';
    render(
      <SleepStageAgeTable rows={rows} ageBand="50\u201359" bandBasis={bandBasis} />,
    );
    expect(screen.getByText(bandBasis)).toBeTruthy();
  });

  it('omits the band note entirely when none is supplied', () => {
    render(<SleepStageAgeTable rows={rows} ageBand="50\u201359" />);
    expect(screen.queryByText(/Ohayon et al. 2004 polysomnography/)).toBeNull();
  });

  it('renders a fallback when sleep-stage rows are not available', () => {
    render(<SleepStageAgeTable rows={[]} ageBand="50–59" />);
    expect(screen.getByText(/fills in when the overnight sleep stages are available/i)).toBeTruthy();
  });
});
