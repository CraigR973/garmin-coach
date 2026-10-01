import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import userEvent from '@testing-library/user-event';
import { act, cleanup, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { DailyLoopEnvelope } from '@/hooks/useDailyLoop';
import { SYMPTOM_NOTICES } from '@/lib/symptoms';
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

/** A morning with a ride on it, so the hero speaks to the session (a day with no
 *  session is a rest day, whose line is the rest day's since Batch 298). */
function withRide(envelope: DailyLoopEnvelope): DailyLoopEnvelope {
  envelope.data.plannedWorkouts = [
    {
      id: '55555555-5555-4555-8555-555555555555',
      userId: '11111111-1111-4111-8111-111111111111',
      planBlockId: null,
      workoutDate: '2026-06-20',
      version: 1,
      title: 'Sweet Spot',
      workoutType: 'bike_sweet_spot',
      status: 'planned',
      isActive: true,
      plannedDurationMin: 60,
      intensityTarget: '88-90% FTP',
      structuredWorkout: {},
      source: 'seed',
      adherence: null,
    },
  ];
  return envelope;
}

describe('morning brief page', () => {
  it('renders the full morning brief page', async () => {
    renderWithQuery(<MorningBriefPage />);
    expect(await screen.findByText('Coach read')).toBeTruthy();
    expect(screen.getByText('Green light')).toBeTruthy();
    expect(screen.getByRole('button', { name: /listen to brief/i })).toBeTruthy();
  });

  it('shows how the numbers were worked out under the coach read, collapsed (Batch 273.2)', async () => {
    const withWorking = structuredClone(snapshot);
    withWorking.data.morningAnalysis!.thermalReview = {
      indoorPeakC: 19.1,
      provenance: [
        {
          figure: 'environment.thermalReview.indoorPeakC',
          label: 'bedroom peak overnight',
          value: 19.1,
          units: '°C',
          rule: 'the highest reading inside the window, from readings taken between sleep onset and wake',
          window: { kind: 'sleep', startUtc: '2026-06-19T21:00:00', endUtc: '2026-06-20T05:00:00', label: null },
          sources: { rowsInWindow: 16, firstReadingUtc: '2026-06-19T21:05:00' },
          threshold: { name: 'thermal disruption', comparedAgainst: 20, units: '°C', source: null },
        },
      ],
    };
    apiFetchMock.mockImplementation(() => Promise.resolve(withWorking));
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter>
          <MorningBriefPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const panel = await screen.findByTestId('provenance-panel');
    expect(panel.hasAttribute('open')).toBe(false);
    expect(within(panel).getByText('How these numbers were worked out')).toBeTruthy();
    expect(within(panel).getByText('Bedroom peak overnight — 19.1 °C')).toBeTruthy();
    expect(within(panel).getByText(/22:00 → 06:00 — the night you actually slept/)).toBeTruthy();
    // It sits under the coach's prose, not above it.
    expect(screen.getByText('Rested and ready.').compareDocumentPosition(panel)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );
  });

  it('shows no working panel for a brief stored before the working existed (Batch 273.2)', async () => {
    renderWithQuery(<MorningBriefPage />);
    expect(await screen.findByText('Coach read')).toBeTruthy();
    expect(screen.queryByTestId('provenance-panel')).toBeNull();
  });

  it("records a disagreement with today's call without changing it (Batch 274)", async () => {
    const user = userEvent.setup();
    apiFetchMock.mockImplementation((path: string, options?: RequestInit) => {
      if (path === '/api/v1/disputes/verdicts' && options?.method === 'POST') {
        return Promise.resolve({
          data: {
            id: '66666666-6666-4666-8666-666666666666',
            kind: 'verdict',
            analysisId: '22222222-2222-4222-8222-222222222222',
            subjectDate: '2026-06-20',
            figure: null,
            label: null,
            verdict: 'Green',
            reason: 'I felt rough.',
            createdAtUtc: '2026-06-20T08:00:00Z',
          },
          meta: { generatedAtUtc: '2026-06-20T08:00:00Z' },
          errors: [],
        });
      }
      return Promise.resolve(snapshot);
    });
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter>
          <MorningBriefPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await user.click(await screen.findByRole('button', { name: "I disagree with today's call" }));
    await user.type(screen.getByRole('textbox'), 'I felt rough.');
    await user.click(screen.getByRole('button', { name: 'Record it' }));

    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/disputes/verdicts', {
      method: 'POST',
      body: JSON.stringify({ subjectDate: '2026-06-20', reason: 'I felt rough.' }),
    });
    expect(
      await screen.findByText("Recorded. It won't change today's call, and it will show in your weekly review."),
    ).toBeTruthy();
  });

  it('puts the deterministic verdict before the supporting brief detail (Batch 244)', async () => {
    renderWithQuery(<MorningBriefPage />);

    const verdict = await screen.findByRole('region', { name: /today.s verdict/i });
    const metrics = screen.getByText("Last night's metrics");
    const coachRead = screen.getByText('Coach read');

    expect(verdict.compareDocumentPosition(metrics)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    expect(verdict.compareDocumentPosition(coachRead)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  });

  it('renders the deterministic acute escalation and standing medical boundary (Batch 246)', async () => {
    const withAcuteBoundary = structuredClone(snapshot);
    withAcuteBoundary.data.morningAnalysis!.acutePhysiology = {
      status: 'triggered',
      standingLine:
        "This read comes from your watch and your room sensors. It can't see how you actually feel — if those two disagree, trust yourself.",
      requiresBikeRest: true,
      triggeredSignals: ['resting_heart_rate'],
      dataSufficiency: { status: 'sufficient', message: null, missingRows: [] },
      escalations: [
        {
          kind: 'resting_heart_rate',
          message:
            'Your resting heart rate is 51 this morning against a usual 44. Take today off the bike.',
        },
      ],
    };
    apiFetchMock.mockImplementation(() => Promise.resolve(withAcuteBoundary));
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <MorningBriefPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText('Take today off the bike')).toBeTruthy();
    expect(screen.getByText('An acute recovery signal rules out riding today.')).toBeTruthy();
    const alert = screen.getByRole('alert');
    expect(within(alert).getByText('Why this needs rest')).toBeTruthy();
    expect(within(alert).getByText(/resting heart rate is 51/i)).toBeTruthy();
    expect(
      screen.getByText(
        "This read comes from your watch and your room sensors. It can't see how you actually feel — if those two disagree, trust yourself.",
      ),
    ).toBeTruthy();
  });

  it('says "No training today" when a reported symptom rules training out (Batch 294)', async () => {
    const withFloor = structuredClone(snapshot);
    withFloor.data.morningAnalysis!.verdict = 'red';
    withFloor.data.morningAnalysis!.acutePhysiology = {
      status: 'triggered',
      standingLine:
        "This read comes from your watch and your room sensors. It can't see how you actually feel — if those two disagree, trust yourself.",
      requiresBikeRest: true,
      requiresTrainingRest: true,
      triggeredSignals: ['symptoms'],
      dataSufficiency: { status: 'sufficient', message: null, missingRows: [] },
      escalations: [
        {
          kind: 'symptoms',
          level: 'rest',
          message:
            "You've told me about a fever, aches or a chest infection. Training through that adds strain your body doesn't need.",
        },
      ],
    };
    apiFetchMock.mockImplementation(() => Promise.resolve(withFloor));
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <MorningBriefPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText('No training today')).toBeTruthy();
    expect(screen.getByText("The symptoms you've reported rule out training today.")).toBeTruthy();
    expect(screen.queryByText('Take today off the bike')).toBeNull();
    const alert = screen.getByRole('alert');
    expect(within(alert).getByText('Why this needs rest')).toBeTruthy();
    expect(within(alert).getByText(/fever, aches or a chest infection/i)).toBeTruthy();
  });

  it('shows the held headline when the graded verdict holds the targets (Batch 296)', async () => {
    const held = withRide(structuredClone(snapshot));
    held.data.morningAnalysis!.verdictEngine = 'graded';
    held.data.morningAnalysis!.verdictHeld = true;
    apiFetchMock.mockImplementation(() => Promise.resolve(held));
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <MorningBriefPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText('Good to go — hold your targets')).toBeTruthy();
    expect(
      screen.getByText(
        'One thing is a little off: ride as planned, and hold your targets rather than pushing past them.',
      ),
    ).toBeTruthy();
  });

  // Batch 298: one story. Wording signed off by Craig on Mark's behalf, 1 Oct 2026.
  it('says the session stands on a light-week Amber, naming the week (Batch 298)', async () => {
    const lightWeek = withRide(structuredClone(snapshot));
    lightWeek.data.morningAnalysis!.verdict = 'amber';
    lightWeek.data.morningAnalysis!.verdictEngine = 'graded';
    lightWeek.data.morningAnalysis!.verdictLightWeekHold = 'consolidation';
    apiFetchMock.mockImplementation(() => Promise.resolve(lightWeek));
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <MorningBriefPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText('Ride as planned — hold your targets')).toBeTruthy();
    expect(
      screen.getByText(
        "It's your consolidation week, so today's session stays as planned: hold your targets.",
      ),
    ).toBeTruthy();
    expect(screen.queryByText('Ease the hard work; easy riding stays as planned.')).toBeNull();
  });

  it('says what Home says on a rest or holiday day, as on 1 Oct (Batch 298)', async () => {
    // 1 Oct: a graded Amber on a holiday rest day. Home said the day was for recovery
    // and the brief said "Ease the hard work".
    const holiday = structuredClone(snapshot);
    holiday.data.morningAnalysis!.verdict = 'amber';
    holiday.data.morningAnalysis!.verdictEngine = 'graded';
    apiFetchMock.mockImplementation(() => Promise.resolve(holiday));
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <MorningBriefPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(
      await screen.findByText("Today's a rest day — recovery is the plan, not training."),
    ).toBeTruthy();
    expect(screen.queryByText('Ease the hard work; easy riding stays as planned.')).toBeNull();
  });

  it('eases only the hard work on a graded Amber, and keeps the old line for a ladder read (Batch 296)', async () => {
    const graded = withRide(structuredClone(snapshot));
    graded.data.morningAnalysis!.verdict = 'amber';
    graded.data.morningAnalysis!.verdictEngine = 'graded';
    apiFetchMock.mockImplementation(() => Promise.resolve(graded));
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { unmount } = render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <MorningBriefPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(await screen.findByText('Ease the hard work; easy riding stays as planned.')).toBeTruthy();
    unmount();

    // A read stored before the switch carries no engine: the ladder's line stands.
    const ladder = withRide(structuredClone(snapshot));
    ladder.data.morningAnalysis!.verdict = 'amber';
    apiFetchMock.mockImplementation(() => Promise.resolve(ladder));
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter>
          <MorningBriefPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(await screen.findByText('Ease back — shorter, and drop the hard stuff.')).toBeTruthy();
    expect(screen.queryByText('Ease the hard work; easy riding stays as planned.')).toBeNull();
  });

  it('shows the exact insufficient-data line instead of a Green interpretation (Batch 246)', async () => {
    const withBlackout = structuredClone(snapshot);
    withBlackout.data.morningAnalysis!.verdict = 'amber';
    withBlackout.data.morningAnalysis!.acutePhysiology = {
      status: 'insufficient_data',
      standingLine:
        "This read comes from your watch and your room sensors. It can't see how you actually feel — if those two disagree, trust yourself.",
      requiresBikeRest: false,
      triggeredSignals: [],
      dataSufficiency: {
        status: 'insufficient_data',
        message: 'Insufficient data to judge today.',
        missingRows: ['daily_metric', 'sleep'],
      },
      escalations: [],
    };
    apiFetchMock.mockImplementation(() => Promise.resolve(withBlackout));
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <MorningBriefPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText('Insufficient data to judge today.')).toBeTruthy();
    expect(screen.queryByText(/ready to train/i)).toBeNull();
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

  // Batch 301: the 999, 111 and GP notices lived only in the stored morning, which is
  // written only after the paid brief succeeds. In an Anthropic outage (21 Jul, 31 Aug)
  // a "Chest or heart" answer showed "Couldn't finish your brief" and nothing else.
  function renderBriefPage() {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <MorningBriefPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );
  }

  it('shows the chest notice beside a failed brief when his check-in reported it (Batch 301)', async () => {
    apiFetchMock.mockImplementation(() =>
      Promise.resolve(
        withoutBrief({
          briefGeneration: { status: 'failed', reason: 'billing' },
          manualEntry: { ...checkedIn, symptoms: 'chest_heart' },
        }),
      ),
    );
    renderBriefPage();

    expect(await screen.findByText(/couldn.t finish your brief/i)).toBeTruthy();
    const notice = screen.getByText(SYMPTOM_NOTICES.chest_heart.notice).closest('[role="alert"]');
    expect(notice).not.toBeNull();
    expect(within(notice as HTMLElement).getByText('Why this needs rest')).toBeTruthy();
    expect(screen.getByRole('link', { name: /try again/i })).toBeTruthy();
  });

  it('shows the fever notice while the brief is still being written (Batch 301)', async () => {
    apiFetchMock.mockImplementation(() =>
      Promise.resolve(
        withoutBrief({
          briefGeneration: { status: 'generating', reason: null },
          manualEntry: { ...checkedIn, symptoms: 'fever_aches' },
        }),
      ),
    );
    renderBriefPage();

    expect(await screen.findByText(/writing your brief/i)).toBeTruthy();
    expect(screen.getByText(SYMPTOM_NOTICES.fever_aches.notice)).toBeTruthy();
  });

  it('shows no notice beside a failed brief when he answered None or was not asked (Batch 301)', async () => {
    for (const symptoms of ['none', null] as const) {
      apiFetchMock.mockImplementation(() =>
        Promise.resolve(
          withoutBrief({
            briefGeneration: { status: 'failed', reason: 'billing' },
            manualEntry: { ...checkedIn, symptoms },
          }),
        ),
      );
      renderBriefPage();

      expect(await screen.findByText(/couldn.t finish your brief/i)).toBeTruthy();
      expect(screen.queryByText('Why this needs rest')).toBeNull();
      expect(screen.queryByText('Why today is capped')).toBeNull();
      cleanup();
    }
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
