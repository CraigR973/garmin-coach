import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { WorkoutDetailSheet } from './WorkoutDetailSheet';

type Workout = Parameters<typeof WorkoutDetailSheet>[0]['workout'];

const apiFetchMock = vi.fn();
vi.mock('@/lib/api', () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...(args as [string])),
}));

const META = { generatedAtUtc: '2026-07-25T00:00:00.000Z' };

// The read fetch and follow-up chat history both go through apiFetch. Default to
// a completed session whose read is genuinely absent, and an empty chat.
function stubApi(
  read: unknown = null,
  state: 'absent' | 'generating' | 'failed' | 'ready' = read ? 'ready' : 'absent',
) {
  apiFetchMock.mockImplementation(async (path: string) => {
    if (typeof path === 'string' && path.includes('/messages')) return { data: [] };
    return { data: { state, reason: null, read }, meta: META, errors: [] };
  });
}

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
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <WorkoutDetailSheet open workout={workout} onClose={vi.fn()} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  apiFetchMock.mockReset();
  stubApi(null);
});

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

    // A planned (not completed) session shows no post-workout read block.
    expect(screen.queryByText('How it went')).toBeNull();
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

  it('marks a completed session as Completed', async () => {
    renderSheet({ ...structuredBike, status: 'completed' });
    expect(screen.getByText('Completed')).toBeTruthy();
    // Let the (empty) read fetch settle so the honest empty state resolves.
    expect(await screen.findByText(/No read yet/)).toBeTruthy();
  });
});

describe('WorkoutDetailSheet completed read (Batch 152)', () => {
  it('surfaces the stored post-workout read alongside the planned structure', async () => {
    stubApi({
      analysisId: '11111111-1111-4111-8111-111111111111',
      analysisType: 'post_workout',
      verdict: 'maintain',
      generatedAtUtc: '2026-07-25T09:00:00.000Z',
      outputMarkdown: '## Strong ride\n\nYou held every work interval.',
      feedback: null,
    });

    renderSheet({ ...structuredBike, status: 'completed' });

    // The read Mark opened it for: how he performed, not just the plan.
    expect(await screen.findByText('How it went')).toBeTruthy();
    expect(await screen.findByText(/held every work interval/)).toBeTruthy();
    expect(screen.getByText('maintain')).toBeTruthy();

    // Reuses Home's read stack — rate/correct and the follow-up chat.
    expect(screen.getByText('Was this right?')).toBeTruthy();
    expect(screen.getByText('Ask about this read')).toBeTruthy();

    // The planned structure stays available as reference.
    expect(screen.getByText('Session structure')).toBeTruthy();
  });

  it('shows an honest empty state when a completed session has no read yet', async () => {
    renderSheet({ ...structuredBike, status: 'completed' });

    expect(await screen.findByText(/No read yet/)).toBeTruthy();
    // No read means no interactive stack to key to an analysis.
    expect(screen.queryByText('Was this right?')).toBeNull();
    expect(screen.queryByText('Ask about this read')).toBeNull();
  });

  it('shows an honest in-flight state while the session read is generating', async () => {
    stubApi(null, 'generating');
    renderSheet({ ...structuredBike, status: 'completed' });

    expect(await screen.findByText(/Writing your read now/)).toBeTruthy();
    expect(screen.queryByText(/No read yet/)).toBeNull();
  });

  it('shows a retryable failure distinct from an absent read', async () => {
    stubApi(null, 'failed');
    renderSheet({ ...structuredBike, status: 'completed' });

    expect(await screen.findByText(/couldn't write this read/)).toBeTruthy();
    expect(screen.getByText(/Save the session check-in again to retry/)).toBeTruthy();
    expect(screen.queryByText(/No read yet/)).toBeNull();
  });
});
