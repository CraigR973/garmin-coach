import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { AgeComparisonCard, type AgeComparison } from './AgeComparisonCard';

const markLike: AgeComparison = {
  age: 57,
  ageBand: '50–59',
  fitnessAge: 48,
  fitnessAgeDelta: 9,
  fitnessAgeTone: 'good',
  rows: [
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
    {
      metricKey: 'resting_heart_rate_bpm',
      label: 'Resting HR',
      value: 45,
      unit: ' bpm',
      ageAverage: 71,
      ageBand: '50–59',
      betterDirection: 'lower',
      tone: 'good',
      descriptor: 'Much better than average',
    },
  ],
};

describe('AgeComparisonCard', () => {
  it('leads with Garmin fitness age and the years-younger phrasing', () => {
    render(<AgeComparisonCard comparison={markLike} />);
    expect(screen.getByText('48')).toBeTruthy();
    expect(screen.getByText(/9 years younger than your actual age/i)).toBeTruthy();
    expect(screen.getByText(/typical 50–59 year-old/i)).toBeTruthy();
  });

  it('shows each metric against its age-band average', () => {
    render(<AgeComparisonCard comparison={markLike} />);
    expect(screen.getByText('54')).toBeTruthy();
    expect(screen.getByText('45 bpm')).toBeTruthy();
    expect(screen.getByText(/avg 31 · 50–59/)).toBeTruthy();
    // Resting HR is lower-is-better, so the card spells that out.
    expect(screen.getByText(/avg 71 bpm · 50–59 · lower is better/)).toBeTruthy();
  });

  it('falls back gracefully when nothing has synced', () => {
    render(<AgeComparisonCard comparison={{ rows: [] }} />);
    expect(screen.getByText(/shows up once VO₂max and overnight metrics have synced/i)).toBeTruthy();
  });

  it('reports an older fitness age without inventing a younger claim', () => {
    render(
      <AgeComparisonCard
        comparison={{
          age: 50,
          ageBand: '50–59',
          fitnessAge: 58,
          fitnessAgeDelta: -8,
          fitnessAgeTone: 'warn',
          rows: [],
        }}
      />,
    );
    expect(screen.getByText('58')).toBeTruthy();
    expect(screen.getByText(/8 years older than your actual age/i)).toBeTruthy();
  });
});
