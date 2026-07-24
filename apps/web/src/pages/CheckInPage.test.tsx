import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
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

  it('shows a retryable error, not an endless spinner, when generation failed (Batch 141)', async () => {
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
    let putCount = 0;
    apiFetchMock.mockImplementation((path: string, options?: { method?: string }) => {
      if (options?.method === 'PUT') {
        putCount += 1;
        // A retry re-triggers generation: it goes back to "generating".
        return Promise.resolve({
          ...failed,
          data: { ...failed.data, briefGeneration: { status: 'generating', reason: null } },
        });
      }
      if (path === '/api/v1/daily-loop') return Promise.resolve(failed);
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

    // The failure surfaces as a retryable error, and the spinner is gone.
    expect(await screen.findByText(/couldn't finish your brief/i)).toBeTruthy();
    expect(screen.queryByText('Writing your brief')).toBeNull();

    // "Try again" re-triggers generation via a fresh manual-entry PUT.
    await user.click(screen.getByRole('button', { name: /try again/i }));
    await waitFor(() => expect(putCount).toBe(1));
    expect(apiFetchMock).toHaveBeenCalledWith(
      '/api/v1/daily-loop/2026-06-20/manual-entry',
      expect.objectContaining({ method: 'PUT' }),
    );
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
    // Niggle maps into "notes" (a free-text column), not "feel" — opening "More"
    // shows it landed in the right field.
    await user.click(screen.getByRole('button', { name: /more/i }));
    expect(((await screen.findByLabelText('Anything worth noting')) as HTMLTextAreaElement).value).toBe('niggle');
    expect((screen.getByLabelText('In a few words') as HTMLInputElement).value).toBe('');

    await user.click(niggle);
    expect(niggle.getAttribute('aria-pressed')).toBe('false');
    expect((screen.getByLabelText('Anything worth noting') as HTMLTextAreaElement).value).toBe('');
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
