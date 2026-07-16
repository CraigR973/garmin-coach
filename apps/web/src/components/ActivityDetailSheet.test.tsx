import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ActivityDetailSheet } from './ActivityDetailSheet';

type Activity = Parameters<typeof ActivityDetailSheet>[0]['activity'];

function renderSheet(activity: Activity) {
  render(<ActivityDetailSheet open activity={activity} onClose={vi.fn()} />);
}

describe('ActivityDetailSheet (Batch 136)', () => {
  it('shows a logged walk with its kind, name, duration, and start rows', () => {
    renderSheet({
      activityKind: 'walk',
      name: 'Evening Walk',
      durationMin: 70,
      startUtc: '2026-06-24T18:00:00Z',
    });

    expect(screen.getByText('Evening Walk')).toBeTruthy();
    expect(screen.getByText('Walk')).toBeTruthy();
    expect(screen.getByText('Logged')).toBeTruthy();
    expect(screen.getByText('70 min')).toBeTruthy();
    // Row labels render (values are locale/timezone dependent, so not asserted).
    expect(screen.getByText('Duration')).toBeTruthy();
    expect(screen.getByText('Started')).toBeTruthy();
    expect(screen.getByText('Day')).toBeTruthy();
    expect(screen.getByText(/You did this/)).toBeTruthy();
  });

  it('omits the Duration row when the activity has no duration', () => {
    renderSheet({
      activityKind: 'ride',
      name: 'Lunch Ride',
      durationMin: null,
      startUtc: '2026-06-24T12:00:00Z',
    });

    expect(screen.getByText('Ride')).toBeTruthy();
    expect(screen.queryByText('Duration')).toBeNull();
    expect(screen.getByText('Started')).toBeTruthy();
  });
});
