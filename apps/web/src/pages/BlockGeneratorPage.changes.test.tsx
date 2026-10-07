import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { OPEN_COACH_EVENT } from '@/lib/coachOrigin';
import { WHY_THIS_PLAN } from '@/lib/nextPlan';
import * as words from '@/lib/planChanges';
import { BlockGeneratorPage } from './BlockGeneratorPage';

const apiFetchMock = vi.fn();
const toastSuccess = vi.fn();
const toastError = vi.fn();

vi.mock('@/lib/api', () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}));

vi.mock('sonner', () => ({
  toast: {
    success: (...args: unknown[]) => toastSuccess(...args),
    error: (...args: unknown[]) => toastError(...args),
  },
}));

const DAYS = {
  strengthA: 0,
  vo2: 1,
  zone2: 2,
  sweetSpot: 3,
  rest: 4,
  sprints: 5,
  strengthB: 5,
  longRide: 6,
};

const ride = (overrides: Record<string, unknown>) => ({
  workoutType: 'bike_endurance',
  intensityTarget: 'Zone 2 ~65–72% FTP',
  structuredWorkout: { format: 'bike', steps: [] },
  ...overrides,
});

function envelope(overrides: Record<string, unknown> = {}, data: Record<string, unknown> = {}) {
  return {
    data: {
      draft: {
        status: 'draft',
        framework: '13-week 2121',
        planName: 'Plan No. 3',
        planNumber: 3,
        whyThisPlan: ['It keeps your week from Plan No. 2: dumbbells on Monday.'],
        startDate: '2026-10-19',
        endDate: '2026-11-01',
        ftpWatts: 280,
        athleteName: 'Mark',
        generatedAtUtc: '2026-10-07T07:00:00',
        lockedAtUtc: null,
        days: DAYS,
        revision: 0,
        changes: [],
        basis: { previousPlan: 'Plan No. 2', longestWeekMin: 453 },
        weeks: [
          {
            weekNumber: 1,
            blockType: 'build',
            label: 'TEST + BUILD',
            startDate: '2026-10-19',
            endDate: '2026-10-25',
            totalMin: 414,
            workouts: [
              ride({
                id: 's002',
                dayOffset: 1,
                slot: 0,
                kind: 'test',
                workoutDate: '2026-10-20',
                title: 'FTP Ramp Test',
                plannedDurationMin: 40,
              }),
              ride({
                id: 's007',
                dayOffset: 6,
                slot: 0,
                kind: 'long',
                workoutDate: '2026-10-25',
                title: 'Long Z2',
                plannedDurationMin: 120,
              }),
            ],
          },
          {
            weekNumber: 2,
            blockType: 'build',
            label: 'BUILD',
            startDate: '2026-10-26',
            endDate: '2026-11-01',
            totalMin: 445,
            workouts: [
              ride({
                id: 's009',
                dayOffset: 1,
                slot: 0,
                kind: 'vo2',
                workoutDate: '2026-10-27',
                title: 'VO₂ (30/30s, 2 × 10 @ 130%)',
                workoutType: 'bike_vo2',
                plannedDurationMin: 51,
                intensityTarget: '130% FTP in ERG, 30s on / 30s easy',
              }),
            ],
          },
        ],
        ...overrides,
      },
      canGenerate: false,
      sessionEdits: {
        s002: { minutes: null, intervals: null, fixed: 'The ramp test stays as it is. You can move it or remove it.' },
        s007: { minutes: { min: 30, max: 240 }, intervals: null, fixed: null },
        s009: {
          minutes: null,
          intervals: {
            repeat: 10,
            workSec: 30,
            workPct: 130,
            restSec: 30,
            restPct: 55,
            label: '10 × 30s/30s @ 130%/55%',
            matchingSets: 2,
          },
          fixed: null,
        },
      },
      startOptions: ['2026-10-12', '2026-10-19', '2026-10-26'],
      sessionChangesSinceRebuild: 0,
      weeksOverLongest: [],
      ...data,
    },
    meta: { generatedAtUtc: '2026-10-10T09:00:00Z' },
    errors: [],
  };
}

function changedEnvelope(summary: string) {
  return envelope({
    revision: 1,
    changes: [{ revision: 1, atUtc: '2026-10-10T09:00:00', by: 'you', summary, change: {} }],
  });
}

function respond(first: unknown, afterChange: unknown = first) {
  apiFetchMock.mockImplementation((path: string, options?: { method?: string }) => {
    if (options?.method === 'POST' && path === '/api/v1/block-generator/changes') {
      return Promise.resolve(afterChange);
    }
    return Promise.resolve(first);
  });
}

function changeBodies(): unknown[] {
  return apiFetchMock.mock.calls
    .filter(([path]) => path === '/api/v1/block-generator/changes')
    .map(([, options]) => JSON.parse(String(options?.body)));
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <BlockGeneratorPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('BlockGeneratorPage: change anything in the proposed plan (Batch 324)', () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
    toastSuccess.mockReset();
    toastError.mockReset();
  });

  it('changes a steady ride’s minutes and says what changed', async () => {
    const user = userEvent.setup();
    const summary = 'Sun 25 Oct, Long Z2: 120 min becomes 150 min.';
    respond(envelope(), changedEnvelope(summary));
    renderPage();

    await user.click(await screen.findByRole('button', { name: 'Change Long Z2 on Sun 25 Oct' }));
    expect(screen.getByText(words.minutesLabel(30, 240))).toBeTruthy();
    const minutes = screen.getByLabelText(words.MINUTES);
    await user.clear(minutes);
    await user.type(minutes, '150');
    await user.click(screen.getByRole('button', { name: words.SAVE }));

    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith(summary));
    expect(changeBodies()).toEqual([
      { change: { kind: 'minutes', session: 's007', minutes: 150 }, expectedRevision: 0 },
    ]);
  });

  it('changes a ride’s intervals by the five numbers', async () => {
    const user = userEvent.setup();
    respond(envelope(), changedEnvelope('VO₂ changed.'));
    renderPage();

    await user.click(
      await screen.findByRole('button', { name: 'Change VO₂ (30/30s, 2 × 10 @ 130%) on Tue 27 Oct' }),
    );
    expect(screen.getByText(words.matchingSets(2))).toBeTruthy();
    const reps = screen.getByLabelText(words.REPS);
    await user.clear(reps);
    await user.type(reps, '12');
    await user.click(screen.getByRole('button', { name: words.SAVE }));

    await waitFor(() =>
      expect(changeBodies()).toEqual([
        {
          change: {
            kind: 'intervals',
            session: 's009',
            repeat: 12,
            workSec: 30,
            workPct: 130,
            restSec: 30,
            restPct: 55,
          },
          expectedRevision: 0,
        },
      ]),
    );
  });

  it('says why the ramp test stays as it is', async () => {
    const user = userEvent.setup();
    respond(envelope());
    renderPage();
    await user.click(await screen.findByRole('button', { name: 'Change FTP Ramp Test on Tue 20 Oct' }));
    expect(screen.getByText('The ramp test stays as it is. You can move it or remove it.')).toBeTruthy();
    expect(screen.queryByLabelText(words.MINUTES)).toBeNull();
    expect(screen.queryByLabelText(words.REPS)).toBeNull();
  });

  it('moves a session to any day of the plan', async () => {
    const user = userEvent.setup();
    respond(envelope(), changedEnvelope('Moved.'));
    renderPage();

    await user.click(await screen.findByRole('button', { name: 'Move Long Z2 on Sun 25 Oct' }));
    await user.selectOptions(screen.getByLabelText(words.MOVE_TO), '2026-10-31');
    await user.click(screen.getByRole('button', { name: words.MOVE }));

    await waitFor(() =>
      expect(changeBodies()).toEqual([
        { change: { kind: 'move', session: 's007', toDate: '2026-10-31' }, expectedRevision: 0 },
      ]),
    );
  });

  it('removes a session only once he confirms', async () => {
    const user = userEvent.setup();
    respond(envelope(), changedEnvelope('Removed.'));
    renderPage();

    await user.click(await screen.findByRole('button', { name: 'Remove Long Z2 on Sun 25 Oct' }));
    expect(screen.getByText(words.removeQuestion('Long Z2', 'Sun 25 Oct'))).toBeTruthy();
    await user.click(screen.getByRole('button', { name: words.KEEP_IT }));
    expect(changeBodies()).toEqual([]);

    await user.click(screen.getByRole('button', { name: 'Remove Long Z2 on Sun 25 Oct' }));
    await user.click(screen.getByRole('button', { name: words.REMOVE }));
    await waitFor(() =>
      expect(changeBodies()).toEqual([
        { change: { kind: 'remove', session: 's007' }, expectedRevision: 0 },
      ]),
    );
  });

  it('adds a session to a day with nothing on it', async () => {
    const user = userEvent.setup();
    respond(envelope(), changedEnvelope('Fri 23 Oct: Easy spin added, 45 min.'));
    renderPage();

    await screen.findByText('Plan No. 3');
    expect(screen.getAllByText(words.NOTHING_PLANNED).length).toBeGreaterThan(0);
    await user.click(screen.getByRole('button', { name: words.addTo('Fri 23 Oct') }));
    await user.selectOptions(screen.getByRole('combobox', { name: words.addTo('Fri 23 Oct') }), 'easy');
    expect((screen.getByLabelText(words.MINUTES) as HTMLInputElement).value).toBe('45');
    await user.click(screen.getByRole('button', { name: words.ADD }));

    await waitFor(() =>
      expect(changeBodies()).toEqual([
        {
          change: { kind: 'add', date: '2026-10-23', sessionType: 'easy', minutes: 45 },
          expectedRevision: 0,
        },
      ]),
    );
    expect(toastSuccess).toHaveBeenCalledWith('Fri 23 Oct: Easy spin added, 45 min.');
  });

  it('warns before his days rebuild the plan over changes he has made', async () => {
    const user = userEvent.setup();
    apiFetchMock.mockImplementation((path: string, options?: { method?: string }) =>
      Promise.resolve(
        options?.method === 'POST' && path === '/api/v1/block-generator/changes'
          ? changedEnvelope('Rebuilt.')
          : envelope({}, { sessionChangesSinceRebuild: 2 }),
      ),
    );
    renderPage();

    await screen.findByText(words.DAYS_HEADING);
    await user.selectOptions(screen.getByLabelText(words.DAY_LABELS.vo2), '2');
    await user.selectOptions(screen.getByLabelText(words.DAY_LABELS.zone2), '1');
    await user.click(screen.getByRole('button', { name: words.CHANGE_DAYS }));
    expect(screen.getByText(words.rebuildWarning(2))).toBeTruthy();
    expect(changeBodies()).toEqual([]);
    await user.click(screen.getByRole('button', { name: words.REBUILD }));

    await waitFor(() =>
      expect(changeBodies()).toEqual([
        { change: { kind: 'days', days: { ...DAYS, vo2: 2, zone2: 1 } }, expectedRevision: 0 },
      ]),
    );
  });

  it('changes the start, and everything moves with it', async () => {
    const user = userEvent.setup();
    respond(envelope(), changedEnvelope('Now starts Monday 26 October (it was Monday 19 October).'));
    renderPage();

    await screen.findByText(words.START_LINE);
    await user.selectOptions(screen.getByLabelText(words.START_HEADING), '2026-10-26');
    await user.click(screen.getByRole('button', { name: words.CHANGE_START }));

    await waitFor(() =>
      expect(changeBodies()).toEqual([
        { change: { kind: 'start', startDate: '2026-10-26' }, expectedRevision: 0 },
      ]),
    );
  });

  it('lists his changes, marks the coach’s, and goes back to the plan as proposed', async () => {
    const user = userEvent.setup();
    const changed = envelope({
      revision: 2,
      changes: [
        { revision: 1, atUtc: 'x', by: 'you', summary: 'Sat 31 Oct, Z2 + Neuromuscular: removed.', change: {} },
        { revision: 2, atUtc: 'x', by: 'coach', summary: 'Sun 25 Oct, Long Z2: 120 min becomes 150 min.', change: {} },
      ],
    });
    respond(changed, envelope({ revision: 3 }));
    renderPage();

    expect(await screen.findByText(words.YOUR_CHANGES)).toBeTruthy();
    expect(screen.getByText('Sat 31 Oct, Z2 + Neuromuscular: removed.')).toBeTruthy();
    expect(
      screen.getByText(`Sun 25 Oct, Long Z2: 120 min becomes 150 min. ${words.COACH_SUGGESTION}`),
    ).toBeTruthy();
    expect(screen.getByText(words.WHY_AS_PROPOSED)).toBeTruthy();
    expect(screen.queryByText(WHY_THIS_PLAN)).toBeNull();

    await user.click(screen.getByRole('button', { name: words.RESET }));
    expect(screen.getByText(words.RESET_LINE)).toBeTruthy();
    await user.click(screen.getByRole('button', { name: words.RESET_CONFIRM }));
    await waitFor(() =>
      expect(changeBodies()).toEqual([{ change: { kind: 'reset' }, expectedRevision: 2 }]),
    );
  });

  it('warns about a week longer than his longest, and still lets it stand', async () => {
    apiFetchMock.mockResolvedValue(envelope({}, { weeksOverLongest: [2] }));
    renderPage();
    expect(await screen.findByText(words.overLongest('Plan No. 2', 453))).toBeTruthy();
    expect(screen.getByText(words.overLongest('Plan No. 2', 453)).textContent).toBe(
      'Longer than your longest week of Plan No. 2 (7 h 33).',
    );
  });

  it('shows the server’s words when a change is refused', async () => {
    const user = userEvent.setup();
    apiFetchMock.mockImplementation((path: string, options?: { method?: string }) =>
      options?.method === 'POST' && path === '/api/v1/block-generator/changes'
        ? Promise.reject(new Error('This ride needs at least 30 minutes for its warm-up and cool-down.'))
        : Promise.resolve(envelope()),
    );
    renderPage();
    await user.click(await screen.findByRole('button', { name: 'Change Long Z2 on Sun 25 Oct' }));
    const minutes = screen.getByLabelText(words.MINUTES);
    await user.clear(minutes);
    await user.type(minutes, '25');
    await user.click(screen.getByRole('button', { name: words.SAVE }));
    await waitFor(() =>
      expect(toastError).toHaveBeenCalledWith(
        'This ride needs at least 30 minutes for its warm-up and cool-down.',
      ),
    );
  });

  it('opens the coach to talk the plan through', async () => {
    const user = userEvent.setup();
    const opened = vi.fn();
    window.addEventListener(OPEN_COACH_EVENT, opened);
    respond(envelope());
    renderPage();
    await user.click(await screen.findByRole('button', { name: words.TALK_TO_COACH }));
    expect(opened).toHaveBeenCalledTimes(1);
    window.removeEventListener(OPEN_COACH_EVENT, opened);
  });

  it('shows each week’s time and every day', async () => {
    respond(envelope());
    renderPage();
    expect(await screen.findByText(words.weekHeading(2, 'BUILD'))).toBeTruthy();
    expect(screen.getByText('26 Oct–1 Nov · 7 h 25')).toBeTruthy();
    expect(screen.getByText('19–25 Oct · 6 h 54')).toBeTruthy();
    // Every day of the week is listed: five of week 1's seven have nothing on them.
    expect(screen.getAllByText(words.NOTHING_PLANNED)).toHaveLength(5 + 6);
  });

  it('uses the words signed off, and no others', () => {
    const text = readFileSync(
      resolve(__dirname, '../../../../docs/drafts/2026-10-07-batch-324-wording.md'),
      'utf8',
    )
      .replace(/\*\*/g, '')
      .replace(/\s+/g, ' ');
    expect(text).toContain("signed off on Mark's behalf under Craig's delegation of 6 Oct 2026");
    const lines = [
      words.DAYS_HEADING,
      words.DAYS_LINE,
      ...Object.values(words.DAY_LABELS),
      words.CHANGE_DAYS,
      words.rebuildWarning(2),
      words.REBUILD,
      words.START_HEADING,
      words.START_LINE,
      words.CHANGE_START,
      words.overLongest('Plan No. 2', 453),
      words.NOTHING_PLANNED,
      words.CHANGE,
      words.MOVE,
      words.REMOVE,
      words.ADD,
      words.NAME,
      words.minutesLabel(20, 240),
      words.REPS,
      words.EFFORT_SECONDS,
      words.EFFORT_PCT,
      words.RECOVERY_SECONDS,
      words.RECOVERY_PCT,
      words.matchingSets(2),
      words.SAVE,
      words.CANCEL,
      words.MOVE_TO,
      words.removeQuestion('Z2 + Neuromuscular', 'Sat 31 Oct'),
      words.KEEP_IT,
      words.addTo('Fri 23 Oct'),
      ...words.ADD_TYPES.map((option) => option.label),
      words.YOUR_CHANGES,
      words.COACH_SUGGESTION,
      words.RESET,
      words.RESET_LINE,
      words.RESET_CONFIRM,
      words.KEEP_THEM,
      words.WHY_AS_PROPOSED,
      words.TALK_TO_COACH,
      words.OFFER_HEADING,
      words.APPLY,
      words.APPLYING,
      words.APPLIED,
      words.SEE_PLAN,
      `Week 2 · BUILD · 26 Oct–1 Nov · ${words.hoursAndMinutes(445)}`,
    ];
    for (const line of lines) {
      expect(text, line).toContain(line);
    }
  });
});
