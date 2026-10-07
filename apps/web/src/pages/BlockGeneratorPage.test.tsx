import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  ACCEPT_PLAN,
  DECLINE_PLAN,
  DECLINED,
  MADE,
  MAKE_PLAN_BUTTON,
  MAKE_PLAN_LINE,
  MAKE_PLAN_TITLE,
  NEXT_PLAN_BUTTON,
  NEXT_PLAN_TITLE,
  WHY_THIS_PLAN,
  acceptedLine,
  lockedTitle,
  nextPlanLine,
  planSpan,
  sessionDay,
} from '@/lib/nextPlan';
import { BlockGeneratorPage } from './BlockGeneratorPage';

const apiFetchMock = vi.fn();

vi.mock('@/lib/api', () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}));

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

const noDraft = {
  data: { draft: null, canGenerate: true },
  meta: { generatedAtUtc: '2026-07-01T06:00:00Z' },
  errors: [],
};

const draft = {
  data: {
    draft: {
      status: 'draft',
      framework: '13-week 2121',
      startDate: '2026-08-03',
      endDate: '2026-11-01',
      ftpWatts: 280,
      athleteName: 'Mark',
      generatedAtUtc: '2026-07-01T06:00:00',
      lockedAtUtc: null,
      weeks: [
        {
          weekNumber: 1,
          blockType: 'build',
          label: 'Build1',
          focus: 'Progress aerobic capacity and quality bike work.',
          startDate: '2026-08-03',
          endDate: '2026-08-09',
          workouts: [
            {
              dayOffset: 1,
              workoutDate: '2026-08-04',
              title: 'VO2 Max 30/30',
              workoutType: 'bike_vo2',
              plannedDurationMin: 60,
              intensityTarget: '105-110% FTP',
              structuredWorkout: { format: 'bike', steps: [] },
            },
          ],
        },
      ],
    },
    canGenerate: false,
  },
  meta: { generatedAtUtc: '2026-07-01T06:00:00Z' },
  errors: [],
};

const lockResponse = {
  data: {
    blocksCreated: 13,
    workoutsWritten: 65,
    startDate: '2026-08-03',
    endDate: '2026-11-01',
  },
  meta: { generatedAtUtc: '2026-07-01T06:00:00Z' },
  errors: [],
};

const WHY_LINE =
  'Week 1 opens with an FTP ramp test on Tuesday 20 October. Ride it in ERG until you can\u2019t hold the step.';

const planNo3 = {
  data: {
    draft: {
      status: 'draft',
      framework: '13-week 2121',
      planName: 'Plan No. 3',
      planNumber: 3,
      whyThisPlan: [WHY_LINE],
      startDate: '2026-10-19',
      endDate: '2027-01-17',
      ftpWatts: 280,
      athleteName: 'Mark',
      generatedAtUtc: '2026-10-07T07:00:00',
      lockedAtUtc: null,
      progressionProposal: null,
      weeks: [
        {
          weekNumber: 1,
          blockType: 'build',
          label: 'TEST + BUILD',
          startDate: '2026-10-19',
          endDate: '2026-10-25',
          totalMin: 414,
          workouts: [
            {
              id: 's005',
              dayOffset: 5,
              slot: 0,
              kind: 'sprints',
              workoutDate: '2026-10-24',
              title: 'Z2 + Neuromuscular',
              workoutType: 'bike_endurance',
              plannedDurationMin: 58,
              intensityTarget: 'Zone 2 ~65–72% FTP',
              structuredWorkout: { format: 'bike', steps: [] },
            },
            {
              id: 's006',
              dayOffset: 5,
              slot: 1,
              kind: 'strength_b',
              workoutDate: '2026-10-24',
              title: 'Dumbbells B (upper body)',
              workoutType: 'strength_maintenance',
              plannedDurationMin: 20,
              intensityTarget: 'Dumbbells 2 × 12',
              structuredWorkout: { format: 'strength', steps: [] },
            },
          ],
        },
      ],
    },
    canGenerate: false,
  },
  meta: { generatedAtUtc: '2026-10-07T07:00:00Z' },
  errors: [],
};

const draftWithProposal = {
  ...draft,
  data: {
    ...draft.data,
    draft: {
      ...draft.data.draft,
      ftpWatts: 292,
      progressionProposal: {
        status: 'ready',
        source: 'last_completed_block',
        currentFtpWatts: 280,
        recommendedFtpWatts: 292,
        ftpChangeWatts: 12,
        focus: 'Carry the build forward with a slightly higher FTP seed.',
        structuralNudge: null,
        summary: 'Last block looks ready for a measured FTP bump.',
        evidence: ['Work intervals: 5 on / 6 over / 1 under (92% hit-or-over).'],
        outcome: { weekCount: 13 },
      },
    },
  },
};

function renderPage(queryClient?: QueryClient) {
  const qc =
    queryClient ??
    new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <BlockGeneratorPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('BlockGeneratorPage', () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
  });

  it('offers to make the next plan when none is waiting', async () => {
    apiFetchMock.mockResolvedValue(noDraft);
    renderPage();
    expect(await screen.findByText(MAKE_PLAN_TITLE)).toBeTruthy();
    expect(screen.getByText(MAKE_PLAN_LINE)).toBeTruthy();
    expect(screen.getByRole('button', { name: MAKE_PLAN_BUTTON })).toBeTruthy();
    // It asks for neither a start date nor an FTP: both come from his last plan.
    expect(screen.queryByLabelText(/Start date/)).toBeNull();
    expect(screen.queryByLabelText(/FTP watts/)).toBeNull();
  });

  it('generates a block and shows a confirmation toast', async () => {
    const { toast } = await import('sonner');
    const user = userEvent.setup();

    apiFetchMock.mockImplementation((path: string, options?: { method?: string }) => {
      if (options?.method === 'POST' && path === '/api/v1/block-generator/generate') {
        return Promise.resolve(draft);
      }
      return Promise.resolve(noDraft);
    });

    renderPage();
    await screen.findByText(MAKE_PLAN_TITLE);
    await user.click(screen.getByRole('button', { name: MAKE_PLAN_BUTTON }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/block-generator/generate',
        expect.objectContaining({ method: 'POST', body: '{}' }),
      );
      expect(toast.success).toHaveBeenCalledWith(MADE);
    });
  });

  it('renders the draft weeks with accept and decline', async () => {
    apiFetchMock.mockResolvedValue(draft);
    renderPage();
    expect(await screen.findByText('Week 1 · Build1')).toBeTruthy();
    expect(screen.getByText('VO2 Max 30/30')).toBeTruthy();
    expect(screen.getByText('Tue 4 Aug')).toBeTruthy();
    expect(screen.getByRole('button', { name: ACCEPT_PLAN })).toBeTruthy();
    expect(screen.getByRole('button', { name: DECLINE_PLAN })).toBeTruthy();
  });

  it('renders the last-block proposal on the draft', async () => {
    apiFetchMock.mockResolvedValue(draftWithProposal);
    renderPage();
    expect(await screen.findByText('Last-block proposal')).toBeTruthy();
    expect(screen.getByText('280w → 292w')).toBeTruthy();
    expect(screen.getByText(/measured FTP bump/)).toBeTruthy();
  });

  it('accepts the plan and says its rides are on their way to Zwift', async () => {
    const { toast } = await import('sonner');
    const user = userEvent.setup();

    apiFetchMock.mockImplementation((path: string, options?: { method?: string }) => {
      if (options?.method === 'POST' && path === '/api/v1/block-generator/lock') {
        return Promise.resolve(lockResponse);
      }
      return Promise.resolve(draft);
    });

    renderPage();
    await screen.findByText('Week 1 · Build1');
    await user.click(screen.getByRole('button', { name: ACCEPT_PLAN }));

    await waitFor(() => {
      // A draft made before Batch 323 has no plan name.
      expect(toast.success).toHaveBeenCalledWith(acceptedLine('Your plan'));
    });
  });

  it('shows Plan No. 3: why this plan, each day, and both of Saturday\u2019s sessions', async () => {
    const user = userEvent.setup();
    apiFetchMock.mockResolvedValue(planNo3);
    renderPage();
    expect(await screen.findByText('Plan No. 3')).toBeTruthy();
    expect(screen.getByText(planSpan('2026-10-19', '2027-01-17'))).toBeTruthy();
    expect(screen.getByText(WHY_THIS_PLAN)).toBeTruthy();
    expect(screen.getByText(WHY_LINE)).toBeTruthy();
    expect(screen.getAllByText('Sat 24 Oct')).toHaveLength(2);
    expect(screen.getByText('Z2 + Neuromuscular')).toBeTruthy();
    expect(screen.getByText('Dumbbells B (upper body)')).toBeTruthy();

    // Batch 324: changing the second of Saturday's sessions names it by its id.
    await user.click(
      screen.getByRole('button', { name: 'Change Dumbbells B (upper body) on Sat 24 Oct' }),
    );
    const name = screen.getByLabelText('Name');
    await user.clear(name);
    await user.type(name, 'Dumbbells B with bands');
    await user.click(screen.getByRole('button', { name: /^Save$/ }));
    await waitFor(() => {
      const change = apiFetchMock.mock.calls.find(
        ([path]) => path === '/api/v1/block-generator/changes',
      );
      expect(change).toBeTruthy();
      expect(JSON.parse(String(change?.[1]?.body))).toEqual({
        change: { kind: 'title', session: 's006', title: 'Dumbbells B with bands' },
        expectedRevision: null,
      });
    });
  });

  it('accepts Plan No. 3 by name', async () => {
    const { toast } = await import('sonner');
    const user = userEvent.setup();
    apiFetchMock.mockImplementation((path: string, options?: { method?: string }) => {
      if (options?.method === 'POST' && path === '/api/v1/block-generator/lock') {
        return Promise.resolve(lockResponse);
      }
      return Promise.resolve(planNo3);
    });
    renderPage();
    await screen.findByText('Plan No. 3');
    await user.click(screen.getByRole('button', { name: ACCEPT_PLAN }));
    await waitFor(() => {
      expect(toast.success).toHaveBeenCalledWith(
        'Plan No. 3 is in your plan, and its rides are on their way to Zwift.',
      );
    });
  });

  it('says the rides are on their way to intervals.icu while they are not reaching Zwift', async () => {
    const { toast } = await import('sonner');
    const user = userEvent.setup();
    apiFetchMock.mockImplementation((path: string, options?: { method?: string }) => {
      if (options?.method === 'POST' && path === '/api/v1/block-generator/lock') {
        return Promise.resolve(lockResponse);
      }
      return Promise.resolve(planNo3);
    });
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    // Batch 326: the day the app already holds says intervals.icu has paused the account.
    queryClient.setQueryData(['daily-loop', 'today'], {
      data: {
        zwiftRail: {
          state: 'paused',
          pauseDate: null,
          showLoginReminder: false,
          checkedAtUtc: '2026-10-07T17:05:00Z',
        },
      },
    });
    renderPage(queryClient);
    await screen.findByText('Plan No. 3');
    await user.click(screen.getByRole('button', { name: ACCEPT_PLAN }));
    await waitFor(() => {
      expect(toast.success).toHaveBeenCalledWith(
        'Plan No. 3 is in your plan, and its rides are on their way to intervals.icu.',
      );
    });
    // The builder never fetches the day itself (that issues the week's REM action).
    expect(apiFetchMock).not.toHaveBeenCalledWith('/api/v1/daily-loop');
  });

  it('declines the plan, and nothing in his plan changes', async () => {
    const { toast } = await import('sonner');
    const user = userEvent.setup();
    apiFetchMock.mockImplementation((path: string, options?: { method?: string }) => {
      if (options?.method === 'POST' && path === '/api/v1/block-generator/discard') {
        return Promise.resolve(undefined);
      }
      return Promise.resolve(planNo3);
    });
    renderPage();
    await screen.findByText('Plan No. 3');
    await user.click(screen.getByRole('button', { name: DECLINE_PLAN }));
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/block-generator/discard',
        expect.objectContaining({ method: 'POST' }),
      );
      expect(toast.success).toHaveBeenCalledWith(DECLINED);
    });
  });

  it('says an accepted plan is in his plan', async () => {
    apiFetchMock.mockResolvedValue({
      ...planNo3,
      data: { draft: { ...planNo3.data.draft, status: 'locked' }, canGenerate: true },
    });
    renderPage();
    expect(await screen.findByText(lockedTitle('Plan No. 3'))).toBeTruthy();
  });

  it('uses the words signed off, and no others', () => {
    const text = readFileSync(
      resolve(__dirname, '../../../../docs/drafts/2026-10-07-batch-323-wording.md'),
      'utf8',
    )
      .replace(/\*\*/g, '')
      .replace(/\s+/g, ' ');
    expect(text).toContain("signed off on Mark's behalf under Craig's delegation of 6 Oct 2026");
    for (const words of [
      NEXT_PLAN_TITLE,
      nextPlanLine('Plan No. 3', '2026-10-19', '2026-10-12'),
      nextPlanLine('Plan No. 3', '2026-10-19', '2026-10-20'),
      NEXT_PLAN_BUTTON,
      WHY_THIS_PLAN,
      ACCEPT_PLAN,
      acceptedLine('Plan No. 3'),
      DECLINE_PLAN,
      DECLINED,
      `${MAKE_PLAN_TITLE} · ${MAKE_PLAN_LINE} · ${MAKE_PLAN_BUTTON}`,
      MADE,
      lockedTitle('Plan No. 3'),
      planSpan('2026-10-19', '2027-01-17'),
      sessionDay('2026-10-20'),
    ]) {
      expect(text, words).toContain(words);
    }
  });
});
