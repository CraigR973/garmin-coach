import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { SYMPTOM_NOTICES } from '@/lib/symptoms';
import { CheckInPage } from './CheckInPage';

const apiFetchMock = vi.fn();

vi.mock('@/lib/api', () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

afterEach(() => {
  vi.useRealTimers();
  apiFetchMock.mockReset();
});

const snapshot = {
  data: {
    subjectDate: '2026-06-20',
    timezone: 'Europe/London',
    morningAnalysis: null,
    dailyMetrics: null,
    sleep: null,
    manualEntry: null,
    postWorkoutAnalyses: [],
    postFlexibilityAnalyses: [],
    postStrengthAnalyses: [],
    postWalkAnalyses: [],
    plannedWorkouts: [],
    hostedTtsConsent: false,
    holiday: { isActive: false, activeWindow: null },
    thermalState: {
      thermalReview: {},
      fans: [
        {
          id: 'fan-bedroom',
          label: 'Bedroom fan',
          autoEnabled: true,
          autoTarget: true,
          mode: 'idle',
          isOn: false,
          speed: null,
          respondingToC: null,
        },
      ],
    },
    dataQualityWarnings: [],
    walkingBrief: {
      asOfDate: '2026-06-20',
      window4w: { sessionCount: 0, totalDistanceM: 0, totalDurationMin: 0, sessionsPerWeek: 0 },
      window12w: { sessionCount: 0, totalDistanceM: 0, totalDurationMin: 0, sessionsPerWeek: 0 },
      recentSessions: [],
      trend: 'insufficient_data',
      trendReason: 'Only 0 walk(s) in the last 28 days.',
    },
  },
  meta: { generatedAtUtc: '2026-06-20T06:40:00Z' },
  errors: [],
};

describe('CheckInPage', () => {
  it('saves a quick check-in — overall tap + a chip — in a couple of taps, with no typing', async () => {
    apiFetchMock.mockImplementation((path: string, options?: { method?: string }) => {
      if (options?.method === 'PUT') return Promise.resolve(snapshot);
      if (path === '/api/v1/daily-loop') return Promise.resolve(snapshot);
      return Promise.reject(new Error(`Unexpected request: ${path}`));
    });

    const queryClient = new QueryClient();
    const user = userEvent.setup();

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <CheckInPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await screen.findByRole('button', { name: 'Good' });
    // Batch 63: the BP/notes/session fields sit behind "More" and are not visible
    // by default — the quick path never requires opening it.
    expect(screen.queryByLabelText('Systolic')).toBeNull();

    await user.click(screen.getByRole('button', { name: 'Good' }));
    await user.click(screen.getByRole('button', { name: 'Slept well' }));
    await user.click(screen.getByRole('button', { name: /get today's brief/i }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/daily-loop/2026-06-20/manual-entry',
        expect.objectContaining({ method: 'PUT' }),
      );
    });
    const [, options] = apiFetchMock.mock.calls.find(
      ([path, opts]) => path === '/api/v1/daily-loop/2026-06-20/manual-entry' && opts?.method === 'PUT',
    ) as [string, { body: string }];
    expect(JSON.parse(options.body)).toMatchObject({ subjectiveScore: 8, feel: 'slept well' });
  });

  it('asks about symptoms with None preselected, and sends the answer he taps (Batch 294)', async () => {
    apiFetchMock.mockImplementation((path: string, options?: { method?: string }) => {
      if (options?.method === 'PUT') return Promise.resolve(snapshot);
      if (path === '/api/v1/daily-loop') return Promise.resolve(snapshot);
      return Promise.reject(new Error(`Unexpected request: ${path}`));
    });
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <CheckInPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const group = await screen.findByRole('radiogroup', { name: 'Any symptoms today?' });
    const options = within(group).getAllByRole('radio');
    expect(options.map((option) => option.textContent)).toEqual([
      'None',
      'Head coldRunny or blocked nose, sneezing, sore throat',
      'Fever or achesA temperature, aching muscles, or a chesty cough',
      'Chest or heartChest pain or tightness, a racing or irregular heartbeat, or feeling faint',
    ]);
    expect(within(group).getByRole('radio', { name: 'None' }).getAttribute('aria-checked')).toBe(
      'true',
    );

    await user.click(within(group).getByRole('radio', { name: /Head cold/ }));
    expect(
      within(group).getByRole('radio', { name: /Head cold/ }).getAttribute('aria-checked'),
    ).toBe('true');
    await user.click(screen.getByRole('button', { name: /get today's brief/i }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/daily-loop/2026-06-20/manual-entry',
        expect.objectContaining({ method: 'PUT' }),
      );
    });
    const [, options2] = apiFetchMock.mock.calls.find(
      ([path, opts]) => path === '/api/v1/daily-loop/2026-06-20/manual-entry' && opts?.method === 'PUT',
    ) as [string, { body: string }];
    expect(JSON.parse(options2.body)).toMatchObject({ symptoms: 'head_cold' });
  });

  it('seeds the symptom answer from the stored check-in (Batch 294)', async () => {
    const stored = {
      ...snapshot,
      data: {
        ...snapshot.data,
        manualEntry: {
          id: '8a2c4b36-5a8c-4e0b-a7a4-0c6f1b2d3e4f',
          userId: '1b6c7a8e-2d3f-4a5b-8c9d-0e1f2a3b4c5d',
          entryDate: '2026-06-20',
          entryAtUtc: '2026-06-20T06:30:00Z',
          actualWorkoutJson: {},
          supplementsJson: {},
          foodJson: {},
          symptoms: 'fever_aches',
        },
      },
    };
    apiFetchMock.mockImplementation(() => Promise.resolve(stored));
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <CheckInPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const group = await screen.findByRole('radiogroup', { name: 'Any symptoms today?' });
    await waitFor(() => {
      expect(
        within(group).getByRole('radio', { name: /Fever or aches/ }).getAttribute('aria-checked'),
      ).toBe('true');
    });
  });

  it("shows the answer's medical notice the moment he picks it, before any save or brief (Batch 301)", async () => {
    apiFetchMock.mockImplementation((path: string) => {
      if (path === '/api/v1/daily-loop') return Promise.resolve(snapshot);
      return Promise.reject(new Error(`Unexpected request: ${path}`));
    });
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <CheckInPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const group = await screen.findByRole('radiogroup', { name: 'Any symptoms today?' });
    // None is preselected, and an ordinary morning shows nothing.
    expect(screen.queryByText('Why this needs rest')).toBeNull();
    expect(screen.queryByText('Why today is capped')).toBeNull();

    await user.click(within(group).getByRole('radio', { name: /Chest or heart/ }));
    const chest = screen.getByText(SYMPTOM_NOTICES.chest_heart.notice).closest('[role="alert"]');
    expect(chest).not.toBeNull();
    expect(within(chest as HTMLElement).getByText('Why this needs rest')).toBeTruthy();

    await user.click(within(group).getByRole('radio', { name: /Fever or aches/ }));
    expect(
      screen.getByText(SYMPTOM_NOTICES.fever_aches.notice).closest('[role="alert"]'),
    ).not.toBeNull();
    expect(screen.queryByText(SYMPTOM_NOTICES.chest_heart.notice)).toBeNull();

    await user.click(within(group).getByRole('radio', { name: /Head cold/ }));
    const cold = screen.getByText(SYMPTOM_NOTICES.head_cold.notice).closest('[role="status"]');
    expect(cold).not.toBeNull();
    expect(within(cold as HTMLElement).getByText('Why today is capped')).toBeTruthy();

    await user.click(within(group).getByRole('radio', { name: 'None' }));
    expect(screen.queryByText(SYMPTOM_NOTICES.head_cold.notice)).toBeNull();
    expect(screen.queryByText('Why today is capped')).toBeNull();

    // The advice needed no save and no brief: nothing but the daily loop was fetched.
    expect(apiFetchMock.mock.calls.every(([path]) => path === '/api/v1/daily-loop')).toBe(true);
  });

  it('shows the notice for an answer he saved earlier, as when he comes back to try again (Batch 301)', async () => {
    const stored = {
      ...snapshot,
      data: {
        ...snapshot.data,
        briefGeneration: { status: 'failed', reason: 'billing' },
        manualEntry: {
          id: '8a2c4b36-5a8c-4e0b-a7a4-0c6f1b2d3e4f',
          userId: '1b6c7a8e-2d3f-4a5b-8c9d-0e1f2a3b4c5d',
          entryDate: '2026-06-20',
          entryAtUtc: '2026-06-20T06:30:00Z',
          actualWorkoutJson: {},
          supplementsJson: {},
          foodJson: {},
          symptoms: 'chest_heart',
        },
      },
    };
    apiFetchMock.mockImplementation(() => Promise.resolve(stored));
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <CheckInPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText(/couldn't finish your brief/i)).toBeTruthy();
    expect(await screen.findByText(SYMPTOM_NOTICES.chest_heart.notice)).toBeTruthy();
  });

  it("captures last night's bedding, windows, blind and pre-cool setup", async () => {
    apiFetchMock.mockImplementation((path: string, options?: { method?: string }) => {
      if (options?.method === 'PUT') return Promise.resolve(snapshot);
      if (path === '/api/v1/daily-loop') return Promise.resolve(snapshot);
      return Promise.reject(new Error(`Unexpected request: ${path}`));
    });

    const queryClient = new QueryClient();
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <CheckInPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await screen.findByRole('button', { name: 'Good' });
    await user.click(screen.getByRole('button', { name: /last night's setup/i }));
    await user.selectOptions(screen.getByLabelText('Bedding'), 'thin_cover');
    fireEvent.change(screen.getByLabelText('Pre-cool started'), { target: { value: '18:30' } });
    await user.type(screen.getByLabelText('Windows open'), '2');
    await user.type(screen.getByLabelText('Opening per window (cm)'), '10');
    await user.selectOptions(screen.getByLabelText('Blind position'), 'away_from_windowsill');
    await user.click(screen.getByRole('button', { name: /get today's brief/i }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/daily-loop/2026-06-20/manual-entry',
        expect.objectContaining({ method: 'PUT' }),
      );
    });
    const [, options] = apiFetchMock.mock.calls.find(
      ([path, opts]) => path === '/api/v1/daily-loop/2026-06-20/manual-entry' && opts?.method === 'PUT',
    ) as [string, { body: string }];
    expect(JSON.parse(options.body).sleepSetupJson).toEqual({
      beddingWeight: 'thin_cover',
      windowCount: 2,
      windowApertureCm: 10,
      blindPosition: 'away_from_windowsill',
      preCoolStartLocal: '18:30',
    });
  });

  it("records only application for last night's assigned REM actions and keeps unknown distinct", async () => {
    const withRemCheckIn = {
      ...snapshot,
      data: {
        ...snapshot.data,
        remInterventionCheckIn: {
          assignmentId: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
          periodLabel: '2026-W24',
          windowStart: '2026-06-15',
          windowEnd: '2026-06-21',
          wakeDate: '2026-06-20',
          interventions: [
            {
              id: 'consistent_wake',
              action: 'Keep the normal wake time.',
              status: 'unknown',
            },
            {
              id: 'wind_down',
              action: 'Start the wind-down 30 minutes earlier.',
              status: 'applied',
            },
          ],
        },
      },
    };
    apiFetchMock.mockImplementation((path: string, options?: { method?: string }) => {
      if (options?.method === 'PUT') return Promise.resolve(withRemCheckIn);
      if (path === '/api/v1/daily-loop') return Promise.resolve(withRemCheckIn);
      return Promise.reject(new Error(`Unexpected request: ${path}`));
    });

    const queryClient = new QueryClient();
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <CheckInPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Last night's REM focus")).toBeTruthy();
    expect(screen.getByText(/watch already supplies REM and awake time/i)).toBeTruthy();
    expect(screen.getByText(/Unknown stays unknown/i)).toBeTruthy();
    const firstResponse = screen.getByLabelText('consistent_wake response');
    await user.click(firstResponse.querySelector('button:nth-child(2)') as HTMLButtonElement);
    await user.click(screen.getByRole('button', { name: /get today's brief/i }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/daily-loop/2026-06-20/manual-entry',
        expect.objectContaining({ method: 'PUT' }),
      );
    });
    const [, options] = apiFetchMock.mock.calls.find(
      ([path, opts]) => path === '/api/v1/daily-loop/2026-06-20/manual-entry' && opts?.method === 'PUT',
    ) as [string, { body: string }];
    expect(JSON.parse(options.body).remInterventionFeedbackJson).toEqual({
      periodLabel: '2026-W24',
      responses: [
        { interventionId: 'consistent_wake', status: 'not_applied' },
        { interventionId: 'wind_down', status: 'applied' },
      ],
    });
  });

  it('keeps his typed check-in when a background refetch lands mid-edit, and saves it (Batch 139)', async () => {
    // A fresh server response always differs from the cached one (at minimum a new
    // meta.generatedAtUtc), so React Query's structural sharing yields a *new*
    // query.data reference and the seed effect re-runs — the exact production
    // condition. manualEntry stays null (nothing saved yet), so before Batch 139
    // that re-run reset the form to empty.
    const refetched = { ...snapshot, meta: { ...snapshot.meta, generatedAtUtc: '2026-06-20T06:45:00Z' } };
    let getCalls = 0;
    apiFetchMock.mockImplementation((path: string, options?: { method?: string }) => {
      if (options?.method === 'PUT') return Promise.resolve(snapshot);
      if (path === '/api/v1/daily-loop') {
        getCalls += 1;
        return Promise.resolve(getCalls === 1 ? snapshot : refetched);
      }
      return Promise.reject(new Error(`Unexpected request: ${path}`));
    });

    const queryClient = new QueryClient();
    const user = userEvent.setup();

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <CheckInPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const good = await screen.findByRole('button', { name: 'Good' });
    await user.click(good);
    await user.click(screen.getByRole('button', { name: 'Slept well' }));
    expect(good.getAttribute('aria-pressed')).toBe('true');

    // Simulate an iOS PWA warm resume: it refetches ['daily-loop']
    // (refetchOnWindowFocus, widened in lib/resumeRefetch.ts). The server has no
    // saved entry yet, so the fresh snapshot's manualEntry is null — before Batch
    // 139 the seed effect reset the form here and the next save wrote an empty entry.
    await act(async () => {
      await queryClient.refetchQueries({ queryKey: ['daily-loop'] });
    });

    // His edits survive the refetch...
    expect(screen.getByRole('button', { name: 'Good' }).getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByRole('button', { name: 'Slept well' }).getAttribute('aria-pressed')).toBe('true');

    // ...and are what gets saved, not an empty entry.
    await user.click(screen.getByRole('button', { name: /get today's brief/i }));
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/daily-loop/2026-06-20/manual-entry',
        expect.objectContaining({ method: 'PUT' }),
      );
    });
    const [, options] = apiFetchMock.mock.calls.find(
      ([path, opts]) => path === '/api/v1/daily-loop/2026-06-20/manual-entry' && opts?.method === 'PUT',
    ) as [string, { body: string }];
    expect(JSON.parse(options.body)).toMatchObject({ subjectiveScore: 8, feel: 'slept well' });
  });

  it('saves an exact odd feel score and preserves it through a warm-resume refetch (Batch 146)', async () => {
    const refetched = { ...snapshot, meta: { ...snapshot.meta, generatedAtUtc: '2026-06-20T06:45:00Z' } };
    let getCalls = 0;
    apiFetchMock.mockImplementation((path: string, options?: { method?: string }) => {
      if (options?.method === 'PUT') return Promise.resolve(snapshot);
      if (path === '/api/v1/daily-loop') {
        getCalls += 1;
        return Promise.resolve(getCalls === 1 ? snapshot : refetched);
      }
      return Promise.reject(new Error(`Unexpected request: ${path}`));
    });

    const queryClient = new QueryClient();
    const user = userEvent.setup();

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <CheckInPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const score = (await screen.findByRole('spinbutton', { name: 'Feel score' })) as HTMLInputElement;
    await user.clear(score);
    await user.type(score, '7');
    expect(score.value).toBe('7');
    expect(screen.getAllByText('OK').length).toBeGreaterThanOrEqual(1);

    await act(async () => {
      await queryClient.refetchQueries({ queryKey: ['daily-loop'] });
    });

    expect((screen.getByRole('spinbutton', { name: 'Feel score' }) as HTMLInputElement).value).toBe('7');

    await user.click(screen.getByRole('button', { name: /get today's brief/i }));
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/daily-loop/2026-06-20/manual-entry',
        expect.objectContaining({ method: 'PUT' }),
      );
    });
    const [, options] = apiFetchMock.mock.calls.find(
      ([path, opts]) => path === '/api/v1/daily-loop/2026-06-20/manual-entry' && opts?.method === 'PUT',
    ) as [string, { body: string }];
    expect(JSON.parse(options.body)).toMatchObject({ subjectiveScore: 7 });
  });

  it('still seeds the form from the server while it is pristine (Batch 139 guard)', async () => {
    const withEntry = {
      ...snapshot,
      data: {
        ...snapshot.data,
        manualEntry: {
          id: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
          userId: '11111111-1111-4111-8111-111111111111',
          plannedWorkoutId: null,
          activityId: null,
          plannedWorkoutVersion: null,
          entryDate: '2026-06-20',
          entryAtUtc: '2026-06-20T07:00:00Z',
          bpSystolic: null,
          bpDiastolic: null,
          subjectiveScore: 8,
          rpe: null,
          feel: 'slept well',
          adherenceStatus: null,
          actualWorkoutJson: {},
          supplementsJson: {},
          foodJson: {},
          notes: null,
        },
      },
    };
    // First load has no entry; a later refetch brings the one the backstop saved.
    let calls = 0;
    apiFetchMock.mockImplementation((path: string) => {
      if (path === '/api/v1/daily-loop') {
        calls += 1;
        return Promise.resolve(calls === 1 ? snapshot : withEntry);
      }
      return Promise.reject(new Error(`Unexpected request: ${path}`));
    });

    const queryClient = new QueryClient();

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <CheckInPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    // Pristine on first load: overall is not selected.
    const good = await screen.findByRole('button', { name: 'Good' });
    expect(good.getAttribute('aria-pressed')).toBe('false');

    await act(async () => {
      await queryClient.refetchQueries({ queryKey: ['daily-loop'] });
    });

    // An untouched form reflects the newly-arrived server entry — the dirty guard
    // only protects unsaved edits, it does not freeze the form to first load.
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Good' }).getAttribute('aria-pressed')).toBe('true');
    });
  });

  it('shows the 0-10 feel input with word anchors', async () => {
    apiFetchMock.mockImplementation((path: string) => {
      if (path === '/api/v1/daily-loop') return Promise.resolve(snapshot);
      return Promise.reject(new Error(`Unexpected request: ${path}`));
    });

    const queryClient = new QueryClient();

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <CheckInPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText('How you feel today')).toBeTruthy();
    expect(screen.getByRole('slider', { name: '0 to 10 feel score' })).toBeTruthy();
    expect(screen.getByRole('spinbutton', { name: 'Feel score' })).toBeTruthy();
    expect(screen.queryByText('Overall')).toBeNull();
    expect(screen.queryByRole('button', { name: '6' })).toBeNull();
  });

  it("queues today's brief on submit, shows staged progress, then surfaces it when polling sees it (Batch 97)", async () => {
    const briefAnalysis = {
      id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
      generatedAtUtc: '2026-06-20T07:10:00Z',
      verdict: 'amber',
      promptVersion: 'morning-analysis-v8-2026-07-11',
      outputMarkdown: '**Your question**\n\nYou are tired because your REM ran low.',
    };
    const withBrief = { ...snapshot, data: { ...snapshot.data, morningAnalysis: briefAnalysis } };
    const refetchGate: { resolve: null | (() => void) } = { resolve: null };
    apiFetchMock.mockImplementation((path: string, options?: { method?: string }) => {
      if (options?.method === 'PUT') return Promise.resolve(snapshot); // save returns immediately
      if (path === '/api/v1/daily-loop') {
        if (apiFetchMock.mock.calls.filter(([calledPath]) => calledPath === '/api/v1/daily-loop').length === 1) {
          return Promise.resolve(snapshot); // initial load
        }
        return new Promise((resolve) => {
          refetchGate.resolve = () => resolve(withBrief);
        });
      }
      return Promise.reject(new Error(`Unexpected request: ${path}`));
    });

    const queryClient = new QueryClient();
    const user = userEvent.setup();

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <CheckInPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await user.click(await screen.findByRole('button', { name: /get today's brief/i }));

    expect(await screen.findByText("I'll notify you when it's ready")).toBeTruthy();
    expect(screen.getByText('Syncing your overnight data')).toBeTruthy();
    expect(screen.getByText('Reading your morning')).toBeTruthy();
    expect(screen.getByText('Writing your brief')).toBeTruthy();
    if (refetchGate.resolve) {
      refetchGate.resolve();
    }

    // Batch 110: the finished brief is picked up from the normal daily-loop
    // snapshot but no longer renders inline here — Home surfaces it as the
    // unviewed brief, so this page just offers a link to it.
    const viewLink = await screen.findByRole('link', { name: /view brief/i });
    expect(viewLink.getAttribute('href')).toBe('/brief');
    expect(screen.queryByText(/you are tired because your rem ran low/i)).toBeNull();
    expect(screen.queryByText("Today's brief")).toBeNull();

    // Batch 96: once a brief exists, re-submitting would silently regenerate it —
    // the button instead offers to view the existing one.
    expect(screen.queryByRole('button', { name: /get today's brief/i })).toBeNull();
  });

  // The daily-loop envelope carries a failed generation (the 2026-07-21 credit
  // outage) with no brief — pre-141 this hung on "Writing your brief" forever.
  const failed = {
    ...snapshot,
    data: {
      ...snapshot.data,
      morningAnalysis: null,
      briefGeneration: { status: 'failed', reason: 'billing' },
    },
  };
  const generating = {
    ...failed,
    data: { ...failed.data, briefGeneration: { status: 'generating', reason: null } },
  };

  /** The server after "Try again" is accepted: every later read says generating. */
  function retryableServer(first: unknown = failed, after: unknown = generating) {
    const calls = { put: 0, retry: 0 };
    apiFetchMock.mockImplementation((path: string, options?: { method?: string }) => {
      if (options?.method === 'PUT') {
        calls.put += 1;
        return Promise.resolve(after);
      }
      if (path === '/api/v1/daily-loop/2026-06-20/brief/retry') {
        calls.retry += 1;
        return Promise.resolve(after);
      }
      if (path === '/api/v1/daily-loop') {
        return Promise.resolve(calls.put + calls.retry > 0 ? after : first);
      }
      return Promise.reject(new Error(`Unexpected request: ${path}`));
    });
    return calls;
  }

  function renderCheckIn() {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <CheckInPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );
  }

  it('shows a retryable error, not an endless spinner, when generation failed (Batch 141)', async () => {
    const calls = retryableServer();
    const user = userEvent.setup();
    renderCheckIn();

    // The failure surfaces as a retryable error, and the spinner is gone.
    expect(await screen.findByText(/couldn't finish your brief/i)).toBeTruthy();
    expect(screen.queryByText('Writing your brief')).toBeNull();

    // Batch 302: "Try again" asks only for the brief. It used to be a second save of
    // the check-in, and a save is an answer to the symptom question.
    await user.click(screen.getByRole('button', { name: /try again/i }));
    await waitFor(() => expect(calls.retry).toBe(1));
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/daily-loop/2026-06-20/brief/retry', {
      method: 'POST',
    });
    expect(calls.put).toBe(0);
    // The wait starts from the reply, not from the failure still on screen: on `main`
    // a retry dropped straight back to the failure card until the next refetch.
    expect(await screen.findByText("I'll notify you when it's ready")).toBeTruthy();
    expect(screen.queryByText(/couldn't finish your brief/i)).toBeNull();
  });

  it('saves the check-in when he has changed it before trying again (Batch 302)', async () => {
    const calls = retryableServer();
    const user = userEvent.setup();
    renderCheckIn();

    expect(await screen.findByText(/couldn't finish your brief/i)).toBeTruthy();
    // A changed answer is a new check-in, and has to reach the server as one.
    await user.click(screen.getByRole('radio', { name: /chest or heart/i }));
    await user.click(screen.getByRole('button', { name: /try again/i }));

    await waitFor(() => expect(calls.put).toBe(1));
    expect(calls.retry).toBe(0);
    const [, options] = apiFetchMock.mock.calls.find(([, init]) => init?.method === 'PUT')!;
    expect(JSON.parse(options.body).symptoms).toBe('chest_heart');
  });

  it('says the call is on Home when the morning is stored and only its brief failed (Batch 302)', async () => {
    const graded = {
      id: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
      generatedAtUtc: '2026-06-20T07:01:00Z',
      verdict: 'red',
      promptVersion: 'morning-analysis-v54-2026-10-01',
      outputMarkdown: '',
    };
    retryableServer({ ...failed, data: { ...failed.data, gradedMorning: graded } });
    renderCheckIn();

    expect(await screen.findByText("Couldn't finish your written brief")).toBeTruthy();
    expect(
      screen.getByText(
        "Today's call and your plan are ready on Home. Your check-in is saved — tap to try again.",
      ),
    ).toBeTruthy();
    expect(screen.getByRole('link', { name: 'See today' }).getAttribute('href')).toBe('/');
    expect(screen.getByRole('button', { name: 'Try again' })).toBeTruthy();
    // The older words are for a morning with no colour to show.
    expect(screen.queryByText("Couldn't finish your brief")).toBeNull();
    expect(screen.queryByText(/something went wrong while writing/i)).toBeNull();
  });

  it('resolves an orphaned generation to the retryable card past the client max-wait (Batch 144)', async () => {
    // The envelope stays stuck at `generating` — a background task orphaned by a
    // process restart or a hung Anthropic call is never flipped to failed (no reaper)
    // and no analysis ever lands, so the Batch 141 `failed` signal never fires. Pre-144
    // this spun on "Writing your brief" forever (the 2026-07-21 90-minute class).
    const generating = {
      ...snapshot,
      data: {
        ...snapshot.data,
        morningAnalysis: null,
        briefGeneration: { status: 'generating', reason: null },
      },
    };
    apiFetchMock.mockImplementation((path: string, options?: { method?: string }) => {
      if (options?.method === 'PUT') return Promise.resolve(generating);
      if (path === '/api/v1/daily-loop') return Promise.resolve(generating);
      return Promise.reject(new Error(`Unexpected request: ${path}`));
    });

    // Capture the 12-minute max-wait backstop timer without faking the clock (which
    // fights react-query + userEvent): spy on setTimeout, grab the one long-delay
    // callback the wait arms, and invoke it to simulate the cap elapsing. Every other
    // (short) timer — userEvent, findBy, the 3s poll — passes through to the real one.
    const realSetTimeout = window.setTimeout;
    let capCallback: (() => void) | null = null;
    const setTimeoutSpy = vi
      .spyOn(window, 'setTimeout')
      .mockImplementation(((handler: TimerHandler, timeout?: number, ...rest: unknown[]) => {
        // The cap arms at ~12 min; keep clear of react-query's 5-min gcTime timer.
        if (typeof timeout === 'number' && timeout > 600_000) {
          capCallback = handler as () => void;
          return 987654321 as unknown as ReturnType<typeof setTimeout>;
        }
        return (realSetTimeout as typeof setTimeout)(handler, timeout, ...rest);
      }) as typeof setTimeout);

    const queryClient = new QueryClient();
    const user = userEvent.setup();

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <CheckInPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await user.click(await screen.findByRole('button', { name: /get today's brief/i }));

    // The wait is showing, and the backstop timer has been armed.
    expect(await screen.findByText("I'll notify you when it's ready")).toBeTruthy();
    expect(screen.getByText('Writing your brief')).toBeTruthy();
    expect(capCallback).toBeTypeOf('function');

    // Simulate the 12-minute cap elapsing with the generation still stuck.
    act(() => capCallback?.());

    // The client self-corrects to the retryable card, not an endless spinner.
    expect(await screen.findByText(/couldn't finish your brief/i)).toBeTruthy();
    expect(screen.queryByText('Writing your brief')).toBeNull();
    setTimeoutSpy.mockRestore();
  });

  it('shows "View brief" instead of "Get today\'s brief" when a brief already exists on load (Batch 96)', async () => {
    const briefAnalysis = {
      id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
      generatedAtUtc: '2026-06-20T07:10:00Z',
      verdict: 'green',
      promptVersion: 'morning-analysis-v8-2026-07-11',
      outputMarkdown: '**Green light**',
    };
    const withBrief = { ...snapshot, data: { ...snapshot.data, morningAnalysis: briefAnalysis } };

    apiFetchMock.mockImplementation((path: string) => {
      if (path === '/api/v1/daily-loop') return Promise.resolve(withBrief);
      return Promise.reject(new Error(`Unexpected request: ${path}`));
    });

    const queryClient = new QueryClient();

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <CheckInPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const viewLink = await screen.findByRole('link', { name: /view brief/i });
    expect(viewLink.getAttribute('href')).toBe('/brief');
    expect(screen.queryByRole('button', { name: /get today's brief/i })).toBeNull();
  });

  it('toggles a quick chip on and off, mapping it into the right column', async () => {
    apiFetchMock.mockImplementation((path: string) => {
      if (path === '/api/v1/daily-loop') return Promise.resolve(snapshot);
      return Promise.reject(new Error(`Unexpected request: ${path}`));
    });

    const queryClient = new QueryClient();
    const user = userEvent.setup();

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <CheckInPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const niggle = await screen.findByRole('button', { name: 'Niggle' });
    expect(niggle.getAttribute('aria-pressed')).toBe('false');

    await user.click(niggle);
    expect(niggle.getAttribute('aria-pressed')).toBe('true');
    // Niggle maps into "notes" (a free-text column), not "feel". Batch 253
    // (UX241-09) promoted both out of the collapsed "More" and above the fold, so
    // this no longer has to open an accordion to see where the chip landed.
    expect(((await screen.findByLabelText('In your own words')) as HTMLTextAreaElement).value).toBe('niggle');
    expect((screen.getByLabelText('In a few words') as HTMLInputElement).value).toBe('');

    await user.click(niggle);
    expect(niggle.getAttribute('aria-pressed')).toBe('false');
    expect((screen.getByLabelText('In your own words') as HTMLTextAreaElement).value).toBe('');
  });

  it('puts his own words above the fold, not behind "More" (Batch 253, UX241-09)', async () => {
    // His free text is where his intent enters the system: the 2026-09-01 note
    // about window draughts opened the brief's second paragraph, and his
    // post-workout question got its own heading in the read that answered it. It
    // used to be two taps down, summarised alongside blood pressure and
    // supplements — the fields he mostly leaves blank.
    const queryClient = new QueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <CheckInPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByLabelText('In your own words')).toBeTruthy();
    expect(screen.getByLabelText('In a few words')).toBeTruthy();
    expect(screen.getByText('Anything you want me to know?')).toBeTruthy();

    // BP and supplements stay behind "More" — reachable, never required.
    expect(screen.queryByLabelText('Systolic')).toBeNull();
    expect(
      screen.getByText(/Blood pressure and yesterday's supplements & food/i),
    ).toBeTruthy();
  });

  it('still saves BP when "More" is opened and filled in', async () => {
    apiFetchMock.mockImplementation((path: string, options?: { method?: string }) => {
      if (options?.method === 'PUT') return Promise.resolve(snapshot);
      if (path === '/api/v1/daily-loop') return Promise.resolve(snapshot);
      return Promise.reject(new Error(`Unexpected request: ${path}`));
    });

    const queryClient = new QueryClient();
    const user = userEvent.setup();

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <CheckInPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await user.click(await screen.findByRole('button', { name: /more/i }));
    await user.type(await screen.findByLabelText('Systolic'), '108');
    expect(screen.queryByText('How did your sessions go?')).toBeNull();
    await user.click(screen.getByRole('button', { name: /get today's brief/i }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/daily-loop/2026-06-20/manual-entry',
        expect.objectContaining({ method: 'PUT' }),
      );
    });
  });

  it('does not render session logging in the morning check-in, even when workouts exist', async () => {
    const withWorkout = {
      ...snapshot,
      data: {
        ...snapshot.data,
        plannedWorkouts: [
          {
            id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
            userId: '11111111-1111-4111-8111-111111111111',
            planBlockId: null,
            workoutDate: '2026-06-20',
            version: 1,
            title: 'Sweet Spot Builder',
            workoutType: 'bike_sweet_spot',
            status: 'planned',
            isActive: true,
            plannedDurationMin: 60,
            intensityTarget: '88-94% FTP',
            structuredWorkout: {},
            source: 'test',
            adherence: null,
          },
        ],
      },
    };
    apiFetchMock.mockImplementation((path: string, options?: { method?: string }) => {
      if (options?.method === 'PUT') return Promise.resolve(withWorkout);
      if (path === '/api/v1/daily-loop') return Promise.resolve(withWorkout);
      return Promise.reject(new Error(`Unexpected request: ${path}`));
    });

    const queryClient = new QueryClient();
    const user = userEvent.setup();

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <CheckInPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await user.click(await screen.findByRole('button', { name: /more/i }));
    await screen.findByText('Yesterday');
    expect(screen.queryByText('Sweet Spot Builder')).toBeNull();
    expect(screen.queryByText('How did your sessions go?')).toBeNull();
  });

  it('shows the shared error state when the daily loop fails to load, without blocking manual entry', async () => {
    apiFetchMock.mockImplementation((path: string) => {
      if (path === '/api/v1/daily-loop') return Promise.reject(new Error('Network down'));
      return Promise.reject(new Error(`Unexpected request: ${path}`));
    });

    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <CheckInPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Couldn't load today's plan")).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeTruthy();
    // The quick check-in (overall tap + chips) stays usable even when the daily
    // loop fails to load; the fuller fields are still reachable behind "More".
    expect(screen.getByRole('button', { name: 'Good' })).toBeTruthy();
    await userEvent.setup().click(screen.getByRole('button', { name: /more/i }));
    expect(screen.getByLabelText('Systolic')).toBeTruthy();
  });
});
