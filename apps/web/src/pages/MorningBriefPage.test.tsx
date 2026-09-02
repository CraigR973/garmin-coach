import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import userEvent from '@testing-library/user-event';
import { act, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { DailyLoopEnvelope } from '@/hooks/useDailyLoop';
import { MorningBriefPage } from './MorningBriefPage';

const apiFetchMock = vi.fn();
const speechSynthesisMock = {
  speak: vi.fn(),
  pause: vi.fn(),
  resume: vi.fn(),
  cancel: vi.fn(),
  getVoices: vi.fn(() => [] as SpeechSynthesisVoice[]),
  onvoiceschanged: null as (() => void) | null,
};

vi.mock('@/lib/api', () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const snapshot: DailyLoopEnvelope = {
  data: {
    subjectDate: '2026-06-20',
    timezone: 'Europe/London',
    morningAnalysis: {
      id: '22222222-2222-4222-8222-222222222222',
      generatedAtUtc: '2026-06-20T06:35:00Z',
      verdict: 'green',
      promptVersion: 'morning-v1',
      modelName: 'claude-sonnet-4-6',
      outputMarkdown: '**Green light**\n\nRested and ready.',
      planAdjustments: ['Keep the scheduled ride.'],
      reasons: ['Sleep and HRV are in range.'],
      readinessInterpretation: 'load_driven',
      todayActions: [],
      thermalReview: {},
      metricsVsBaselines: [
        {
          metricKey: 'hrv_7_day_avg_ms',
          label: 'HRV (7-day)',
          currentValue: 50,
          baselineMedian: 49,
          lowerQuartile: 43,
          upperQuartile: 57,
          sampleCount: 14,
          excludedSampleCount: 70,
          reliabilityStartDate: '2026-06-11',
        },
      ],
      ageComparison: { rows: [], sleepRows: [] },
    },
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
      latestTemperatureC: 17.4,
      targetTemperatureC: 17,
      capturedAtUtc: '2026-06-20T06:25:00Z',
      overnightLowC: 11.2,
      overnightWindMaxMph: 12,
      overnightWindGustMph: 18,
      thermalReview: {},
      fans: [
        {
          id: 'fan-bedroom',
          label: 'Bedroom fan',
          autoEnabled: true,
          autoTarget: true,
          mode: 'control',
          isOn: true,
          speed: 5,
          respondingToC: 20.1,
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
  meta: {
    generatedAtUtc: '2026-06-20T06:40:00Z',
  },
  errors: [],
};

function renderWithQuery(ui: ReactNode) {
  apiFetchMock.mockImplementation(() => Promise.resolve(snapshot));
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  apiFetchMock.mockClear();
  speechSynthesisMock.speak.mockClear();
  speechSynthesisMock.pause.mockClear();
  speechSynthesisMock.resume.mockClear();
  speechSynthesisMock.cancel.mockClear();
  speechSynthesisMock.getVoices.mockClear();
  speechSynthesisMock.getVoices.mockReturnValue([]);
  speechSynthesisMock.onvoiceschanged = null;
  Object.defineProperty(window, 'speechSynthesis', {
    configurable: true,
    value: speechSynthesisMock,
  });
  Object.defineProperty(window, 'SpeechSynthesisUtterance', {
    configurable: true,
    value: class MockSpeechSynthesisUtterance {
      text: string;
      lang = '';
      pitch = 1;
      rate = 1;
      onend: (() => void) | null = null;
      onerror: (() => void) | null = null;
      onpause: (() => void) | null = null;
      onresume: (() => void) | null = null;

      constructor(text: string) {
        this.text = text;
      }
    },
  });
  localStorage.clear();
});

describe('morning brief page', () => {
  it('renders the full morning brief page', async () => {
    renderWithQuery(<MorningBriefPage />);
    expect(await screen.findByText('Coach read')).toBeTruthy();
    expect(screen.getByText('Green light')).toBeTruthy();
    expect(screen.getByRole('button', { name: /listen to brief/i })).toBeTruthy();
  });

  it('puts the deterministic verdict before the supporting brief detail (Batch 244)', async () => {
    renderWithQuery(<MorningBriefPage />);

    const verdict = await screen.findByRole('region', { name: /today.s verdict/i });
    const metrics = screen.getByText("Last night's metrics");
    const coachRead = screen.getByText('Coach read');

    expect(verdict.compareDocumentPosition(metrics)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    expect(verdict.compareDocumentPosition(coachRead)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  });

  it("surfaces the metrics-vs-baselines snapshot table (Batch 130)", async () => {
    renderWithQuery(<MorningBriefPage />);
    expect(await screen.findByText("Last night's metrics")).toBeTruthy();
    expect(screen.getByText('HRV (7-day)')).toBeTruthy();
    expect(screen.getByText('50')).toBeTruthy();
  });

  it('marks the brief reviewed on open, clearing Home\'s unviewed-brief CTA (Batch 96)', async () => {
    expect(localStorage.getItem('coach_brief_reviewed_date')).toBeNull();
    renderWithQuery(<MorningBriefPage />);
    await screen.findByText('Coach read');
    expect(localStorage.getItem('coach_brief_reviewed_date')).toBe('2026-06-20');
  });

  it('leads with the Today action block above the coach read (Batch 86)', async () => {
    const withAction = structuredClone(snapshot);
    withAction.data.morningAnalysis!.todayActions = [
      { kind: 'sleep', title: 'Wind-down breathwork tonight', href: '/sleep' },
    ];
    apiFetchMock.mockImplementation(() => Promise.resolve(withAction));
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <MorningBriefPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const block = await screen.findByTestId('today-actions');
    expect(within(block).getByText('Wind-down breathwork tonight')).toBeTruthy();
    // The coaching reasoning still renders below the action block.
    expect(screen.getByText('Coach read')).toBeTruthy();
    expect(screen.getByText('Green light')).toBeTruthy();
  });

  it('plays, pauses, resumes, and stops the brief audio (Batch 106)', async () => {
    const user = userEvent.setup();
    renderWithQuery(<MorningBriefPage />);
    const listen = await screen.findByRole('button', { name: /listen to brief/i });

    await user.click(listen);
    expect(speechSynthesisMock.speak).toHaveBeenCalledTimes(1);
    expect(speechSynthesisMock.speak.mock.calls[0]?.[0]?.text).toBe('Green light\n\nRested and ready.');
    expect(screen.getByRole('button', { name: /pause brief audio/i })).toBeTruthy();

    await user.click(screen.getByRole('button', { name: /pause brief audio/i }));
    expect(speechSynthesisMock.pause).toHaveBeenCalledTimes(1);

    const utterance = speechSynthesisMock.speak.mock.calls[0]?.[0];
    await act(async () => {
      utterance?.onpause?.();
    });
    await user.click(screen.getByRole('button', { name: /resume brief audio/i }));
    expect(speechSynthesisMock.resume).toHaveBeenCalledTimes(1);

    await act(async () => {
      utterance?.onresume?.();
    });
    await user.click(screen.getByRole('button', { name: /stop brief audio/i }));
    expect(speechSynthesisMock.cancel).toHaveBeenCalled();
  });

  it('selects the best local voice for the read-aloud, ignoring remote-service voices (Batch 111)', async () => {
    document.documentElement.lang = 'en-GB';
    const user = userEvent.setup();
    const genericLocalVoice = { name: 'English', lang: 'en-GB', localService: true } as SpeechSynthesisVoice;
    const remoteEnhancedVoice = {
      name: 'Google UK English Female (Natural)',
      lang: 'en-GB',
      localService: false,
    } as SpeechSynthesisVoice;
    const naturalLocalVoice = { name: 'Daniel (Enhanced)', lang: 'en-GB', localService: true } as SpeechSynthesisVoice;
    speechSynthesisMock.getVoices.mockReturnValue([genericLocalVoice, remoteEnhancedVoice, naturalLocalVoice]);

    renderWithQuery(<MorningBriefPage />);
    const listen = await screen.findByRole('button', { name: /listen to brief/i });
    await user.click(listen);

    const utterance = speechSynthesisMock.speak.mock.calls[0]?.[0];
    expect(utterance?.voice).toBe(naturalLocalVoice);

    document.documentElement.lang = 'en';
  });
  // -------------------------------------------------------------------------
  // Batch 248 (UX241-02): /brief is where the "brief is ready" push lands, and
  // it rendered `failed`, `generating` and `not-checked-in` byte-identically —
  // one "No morning brief yet" card for all three. The three captures taken
  // during the audit had the same md5. On a morning when generation failed Mark
  // was told, on the app's most important page, to wait for something that was
  // never coming, with no retry and no hint anything had gone wrong.
  // -------------------------------------------------------------------------

  // Must satisfy the shared Zod schema — `fetchDailyLoop` parses the response,
  // so a hand-waved fixture fails to render before any assertion is reached.
  const checkedIn: DailyLoopEnvelope['data']['manualEntry'] = {
    id: '33333333-3333-4333-8333-333333333333',
    userId: '44444444-4444-4444-8444-444444444444',
    entryDate: '2026-06-20',
    entryAtUtc: '2026-06-20T06:30:00Z',
    actualWorkoutJson: {},
    supplementsJson: {},
    foodJson: {},
  };

  function withoutBrief(overrides: Partial<DailyLoopEnvelope['data']>): DailyLoopEnvelope {
    return {
      ...snapshot,
      data: { ...snapshot.data, morningAnalysis: null, ...overrides },
    };
  }

  it('offers a retry when today\'s generation failed (Batch 248 / UX241-02)', async () => {
    apiFetchMock.mockImplementation(() =>
      Promise.resolve(
        withoutBrief({
          briefGeneration: { status: 'failed', reason: 'timeout' },
          // A failed or in-flight generation always has a check-in behind it.
          manualEntry: checkedIn,
        }),
      ),
    );
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <MorningBriefPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText(/couldn.t finish your brief/i)).toBeTruthy();
    // The retry is the point — a failure with no way out is what Batch 141 ended
    // on Home and left standing here.
    const retry = screen.getByRole('link', { name: /try again/i });
    expect(retry.getAttribute('href')).toBe('/check-in');
    expect(screen.queryByText(/no morning brief yet/i)).toBeNull();
  });

  it('shows the writing-your-brief state while generation is in flight', async () => {
    apiFetchMock.mockImplementation(() =>
      Promise.resolve(
        withoutBrief({
          briefGeneration: { status: 'generating', reason: null },
          // A failed or in-flight generation always has a check-in behind it.
          manualEntry: checkedIn,
        }),
      ),
    );
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <MorningBriefPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText(/writing your brief/i)).toBeTruthy();
    expect(screen.queryByText(/couldn.t finish your brief/i)).toBeNull();
  });

  it('invites a check-in when he has not said good morning yet', async () => {
    apiFetchMock.mockImplementation(() =>
      Promise.resolve(withoutBrief({ briefGeneration: null, manualEntry: null })),
    );
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <MorningBriefPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText(/say good morning/i)).toBeTruthy();
    expect(screen.queryByText(/writing your brief/i)).toBeNull();
  });

  it('warns and offers a refresh when the payload is an earlier day (Batch 248 / UX241-11)', async () => {
    // The persisted query cache and the service worker's NetworkFirst fallback
    // can both paint yesterday's brief on a cold open. Home has warned about
    // this since Batch 138; /brief did not, so the only signal was a date in
    // small caps at the top of the page.
    apiFetchMock.mockImplementation(() => Promise.resolve(snapshot));
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <MorningBriefPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    // The fixture's subjectDate is 2026-06-20, which is never local-today.
    const notice = await screen.findByText(/refresh for today/i);
    expect(notice).toBeTruthy();
    expect(screen.getByRole('button', { name: /refresh/i })).toBeTruthy();
  });
});
