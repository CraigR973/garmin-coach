import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { WeeklyMix } from '@coach/shared';
import { WeeklyMixCard } from './WeeklyMixCard';

const baseMix: WeeklyMix = {
  weekStart: '2026-07-06',
  subjectDate: '2026-07-07',
  buckets: [
    { bucket: 'vo2', label: 'VO2', target: 1, done: 0, due: 1, remainingPlanned: 0, atRisk: true },
    { bucket: 'sweet_spot', label: 'Sweet Spot', target: 1, done: 1, due: 0, remainingPlanned: 0, atRisk: false },
    { bucket: 'z2', label: 'Zone 2', target: 3, done: 1, due: 2, remainingPlanned: 2, atRisk: false },
  ],
  shortfall: null,
};

describe('WeeklyMixCard', () => {
  it('renders each bucket as a done/target chip', () => {
    render(<WeeklyMixCard mix={baseMix} />);
    expect(screen.getByText(/This week's mix/i)).not.toBeNull();
    expect(screen.getByText(/VO2 0\/1/)).not.toBeNull();
    expect(screen.getByText(/Sweet Spot 1\/1/)).not.toBeNull();
    expect(screen.getByText(/Zone 2 1\/3/)).not.toBeNull();
  });

  it('shows the re-patch weekday on the eased bucket but hides the full message by default', () => {
    const mix: WeeklyMix = {
      ...baseMix,
      shortfall: {
        bucket: 'vo2',
        label: 'VO2',
        repatched: true,
        moveToWeekday: 'Saturday',
        moveToDate: '2026-07-11',
        message: 'moving it to Saturday keeps the week’s quality work',
      },
    };
    render(<WeeklyMixCard mix={mix} />);
    expect(screen.getByText(/→ Sat/)).not.toBeNull();
    expect(screen.queryByText(/keeps the week’s quality work/)).toBeNull();
  });

  it('renders the shortfall message when showShortfall is set (Plan page)', () => {
    const mix: WeeklyMix = {
      ...baseMix,
      shortfall: {
        bucket: 'vo2',
        label: 'VO2',
        repatched: false,
        moveToWeekday: null,
        moveToDate: null,
        message: 'No VO2 session this week — readiness gets the veto.',
      },
    };
    render(<WeeklyMixCard mix={mix} showShortfall />);
    expect(screen.getByText(/No VO2 session this week/)).not.toBeNull();
  });

  it('renders nothing when there are no bike sessions in the week', () => {
    const { container } = render(<WeeklyMixCard mix={{ ...baseMix, buckets: [] }} />);
    expect(container.firstChild).toBeNull();
  });

  // Batch 217: on 2026-08-15 Mark asked where "VO2 has 1 of a 2-session target
  // done" came from. The chip alone cannot say; the disclosure can.
  it('folds each bucket basis behind a disclosure', () => {
    const mix: WeeklyMix = {
      ...baseMix,
      buckets: baseMix.buckets.map((bucket) => ({
        ...bucket,
        basis: `Counted from your own plan: ${bucket.target} ${bucket.label}.`,
      })),
    };
    render(<WeeklyMixCard mix={mix} />);
    expect(screen.getByText(/Where these numbers come from/i)).not.toBeNull();
    expect(screen.getByText(/Counted from your own plan: 1 VO2\./)).not.toBeNull();
    expect(screen.getByText(/Counted from your own plan: 3 Zone 2\./)).not.toBeNull();
  });

  it('hides the disclosure entirely on a stored read that predates the basis', () => {
    render(<WeeklyMixCard mix={baseMix} />);
    expect(screen.queryByText(/Where these numbers come from/i)).toBeNull();
  });
});
