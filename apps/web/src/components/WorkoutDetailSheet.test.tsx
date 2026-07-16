import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { WorkoutDetailSheet } from './WorkoutDetailSheet';

type Workout = Parameters<typeof WorkoutDetailSheet>[0]['workout'];

const structuredBike: NonNullable<Workout> = {
  id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  workoutDate: '2026-06-23',
  version: 1,
  title: 'VO2 Max 30/30',
  workoutType: 'bike_vo2',
  status: 'planned',
  plannedDurationMin: 60,
  intensityTarget: '105-110% FTP',
  source: 'test',
  structuredWorkout: {
    delivery: 'indoor',
    steps: [
      { minutes: 10, ramp: [45, 75] },
      { pattern: '4x4min/4min@55%', target: '110%' },
      { minutes: 5, ramp: [75, 45] },
    ],
  },
};

function renderSheet(workout: Workout) {
  render(<WorkoutDetailSheet open workout={workout} onClose={vi.fn()} />);
}

describe('WorkoutDetailSheet (Batch 135)', () => {
  it('shows the structured breakdown and power profile for a bike session', () => {
    renderSheet(structuredBike);

    // Metadata: type label, duration, intensity, and coach-planned source.
    expect(screen.getByText('VO₂')).toBeTruthy();
    expect(screen.getByText('60 min')).toBeTruthy();
    expect(screen.getByText('105-110% FTP')).toBeTruthy();
    expect(screen.getByText('Coach-planned')).toBeTruthy();
    expect(screen.getByText('Indoor')).toBeTruthy();

    // Structured steps, warm-up/cool-down labelled by position, plus the SVG.
    expect(screen.getByText('Session structure')).toBeTruthy();
    expect(screen.getByText('Warm-up')).toBeTruthy();
    expect(screen.getByText('10 min · 45→75% FTP')).toBeTruthy();
    expect(screen.getByText('Intervals')).toBeTruthy();
    expect(screen.getByText('4× (4 min @ 110% / 4 min @ 55%)')).toBeTruthy();
    expect(screen.getByText('Cool-down')).toBeTruthy();
    expect(screen.getByRole('img', { name: 'Power profile preview' })).toBeTruthy();
    expect(screen.queryByText('No structured breakdown for this session.')).toBeNull();
  });

  it('shows a metadata-only read for a non-bike session with no structure', () => {
    renderSheet({
      id: 'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
      workoutDate: '2026-06-23',
      version: 1,
      title: 'Flexibility',
      workoutType: 'mobility',
      status: 'planned',
      plannedDurationMin: 16,
      intensityTarget: 'easy',
      source: 'plan_action_add',
      structuredWorkout: {},
    });

    expect(screen.getByText('Mobility')).toBeTruthy();
    expect(screen.getByText('16 min')).toBeTruthy();
    // A user-added session reads back as such, not "Coach-planned".
    expect(screen.getByText('You added this')).toBeTruthy();
    expect(screen.getByText('No structured breakdown for this session.')).toBeTruthy();
    expect(screen.queryByText('Session structure')).toBeNull();
    // Non-bike sessions never show the indoor/outdoor row.
    expect(screen.queryByText('Where')).toBeNull();
  });

  it('marks a completed session as Completed', () => {
    renderSheet({ ...structuredBike, status: 'completed' });
    expect(screen.getByText('Completed')).toBeTruthy();
  });
});
