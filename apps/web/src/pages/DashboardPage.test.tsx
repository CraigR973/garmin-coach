import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { DailyLoopEnvelope } from '@/hooks/useDailyLoop';
import { DashboardPage } from './DashboardPage';

const apiFetchMock = vi.fn();
let onlineStatus = true;

vi.mock('@/lib/api', () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}));

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    player: {
      id: '11111111-1111-4111-8111-111111111111',
      displayName: 'Mark',
      role: 'player',
      timezone: 'Europe/London',
    },
  }),
}));

vi.mock('@/hooks/useOnlineStatus', () => ({
  useOnlineStatus: () => onlineStatus,
}));

const baseSnapshot: DailyLoopEnvelope = {
  data: {
    subjectDate: '2026-06-20',
    timezone: 'Europe/London',
    morningAnalysis: {
      id: '22222222-2222-4222-8222-222222222222',
      generatedAtUtc: '2026-06-20T06:35:00Z',
      verdict: 'green',
      promptVersion: 'morning-v1',
      modelName: 'claude-sonnet-4-6',
      outputMarkdown: '**Green light**',
      planAdjustments: ['Keep the scheduled ride.'],
      reasons: ['Sleep and HRV are in range.'],
      readinessInterpretation: 'load_driven',
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
      ageComparison: {
        age: 57,
        ageBand: '50–59',
        fitnessAge: 48,
        fitnessAgeDelta: 9,
        fitnessAgeTone: 'good',
        rows: [
          {
            metricKey: 'vo2max',
            label: 'VO₂max',
            value: 54,
            unit: '',
            ageAverage: 31,
            ageBand: '50–59',
            betterDirection: 'higher',
            tone: 'good',
            descriptor: 'Much better than average',
          },
        ],
      },
    },
    dailyMetrics: {
      id: '33333333-3333-4333-8333-333333333333',
      userId: '11111111-1111-4111-8111-111111111111',
      calendarDate: '2026-06-20',
      recordedAtUtc: '2026-06-20T06:20:00Z',
      readinessScore: 72,
      readinessLevel: 'Ready',
      readinessSleepScore: 78,
      recoveryTimeMin: 180,
      acuteLoad: 640,
      trainingStatus: 'productive',
      hrvLastNightAvgMs: 50,
      hrvWeeklyAvgMs: 48,
      hrvStatus: 'balanced',
      hrvBaselineLowMs: 43,
      hrvBaselineHighMs: 57,
      restingHeartRateBpm: 45,
      stressAvg: 21,
      bodyBatteryCharged: 63,
      bodyBatteryDrained: 19,
      bodyBatteryEnd: 79,
      weightKg: 78.4,
      vo2max: 54,
      rawPayload: {},
    },
    sleep: {
      id: '44444444-4444-4444-8444-444444444444',
      userId: '11111111-1111-4111-8111-111111111111',
      calendarDate: '2026-06-20',
      sleepStartUtc: '2026-06-19T22:15:00Z',
      sleepEndUtc: '2026-06-20T06:15:00Z',
      score: 70,
      ageAdjustedScore: 74,
      qualifier: 'Good',
      durationSec: 28800,
      deepSleepSec: 5400,
      lightSleepSec: 13200,
      remSleepSec: 5400,
      awakeSleepSec: 1800,
      unmeasurableSleepSec: 0,
      averageSpo2Pct: 96.4,
      lowestSpo2Pct: 93.8,
      averageRespiration: 13.4,
      restingHeartRateBpm: 45,
      avgOvernightHrvMs: 50,
      hrvStatus: 'balanced',
      avgSleepStress: 12.2,
      restlessMomentsCount: 3,
      bodyBatteryChange: 55,
      factorsJson: {},
      rawPayload: {},
    },
    manualEntry: null,
    postWorkoutAnalyses: [],
    postFlexibilityAnalyses: [],
    postStrengthAnalyses: [],
    postWalkAnalyses: [],
    plannedWorkouts: [
      {
        id: '55555555-5555-4555-8555-555555555555',
        userId: '11111111-1111-4111-8111-111111111111',
        planBlockId: null,
        workoutDate: '2026-06-20',
        version: 1,
        title: 'Tempo ride',
        workoutType: 'bike_tempo',
        status: 'planned',
        isActive: true,
        plannedDurationMin: 60,
        intensityTarget: '85-90% FTP',
        structuredWorkout: {},
        source: 'seed',
        adherence: null,
      },
    ],
    thermalState: {
      latestTemperatureC: 17.4,
      targetTemperatureC: 17,
      capturedAtUtc: '2026-06-20T06:25:00Z',
      overnightLowC: 11.2,
      overnightWindMaxMph: 12,
      overnightWindGustMph: 18,
      thermalReview: {},
      fan: { autoEnabled: true, mode: 'control', isOn: true, speed: 5, respondingToC: 20.1 },
    },
    sleepProjection: {
      status: 'fallback',
      tone: 'routine',
      headline: 'Use the usual sleep protocol',
      summary: "There is not enough personal signal from today's training and Mark's measured sleep drivers to change the plan.",
      evidence: [],
      prepActions: [
        'Pre-cool the bedroom toward 17C.',
        'Breathing at 20:00, snack by 21:30, seal near 22:00, bed 23:15.',
      ],
      protocol: {
        preCoolTemperatureC: 17,
        coherenceBreathingTime: '20:00',
        latestSnackTime: '21:30',
        sealTargetTime: '22:00',
        bedtime: '23:15',
      },
    },
    dataQualityWarnings: [],
    walkingBrief: {
      asOfDate: '2026-06-20',
      window4w: { sessionCount: 6, totalDistanceM: 18500, totalDurationMin: 250, sessionsPerWeek: 1.5 },
      window12w: { sessionCount: 18, totalDistanceM: 52000, totalDurationMin: 720, sessionsPerWeek: 1.5 },
      recentSessions: [],
      trend: 'stable',
      trendReason: 'Frequency holding at ~1.5/wk over 28 days.',
    },
    breathworkBrief: {
      asOfDate: '2026-06-20',
      window4w: { sessionCount: 18, totalDurationMin: 54, sessionsPerWeek: 4.5 },
      window12w: { sessionCount: 54, totalDurationMin: 162, sessionsPerWeek: 4.5 },
      recentSessions: [],
      trend: 'stable',
      trendReason: 'Frequency holding at ~4.5/wk over 28 days.',
    },
  },
  meta: {
    generatedAtUtc: '2026-06-20T06:40:00Z',
  },
  errors: [],
};

function buildSnapshot(mutator?: (snapshot: DailyLoopEnvelope) => void) {
  const snapshot = JSON.parse(JSON.stringify(baseSnapshot)) as DailyLoopEnvelope;
  mutator?.(snapshot);
  return snapshot;
}

const overnightSnapshot = {
  data: {
    night: '2026-06-19',
    timezone: 'Europe/London',
    windowStartUtc: '2026-06-19T20:30:00Z',
    windowEndUtc: '2026-06-20T08:00:00Z',
    thresholds: { onC: 19.5, criticalC: 20.0 },
    temperature: [{ t: '2026-06-19T22:00:00Z', c: 20.4 }],
    fan: [],
    sleep: null,
    summary: {
      minTempC: 19,
      maxTempC: 21,
      fanRanMinutes: 210,
      peakSpeed: 5,
      warningMinutes: 210,
      criticalMinutes: 60,
      roomVerdict: 'red',
    },
    nights: ['2026-06-19'],
  },
  meta: { generatedAtUtc: '2026-06-20T08:05:00Z' },
  errors: [],
};

const postRideSnapshot = () =>
  buildSnapshot((snapshot) => {
    snapshot.data.postWorkoutAnalyses = [
      {
        id: '66666666-6666-4666-8666-666666666666',
        activityId: '77777777-7777-4777-8777-777777777777',
        activityName: 'Tempo ride',
        activityType: 'indoor_cycling',
        generatedAtUtc: '2026-06-20T12:20:00Z',
        promptVersion: 'post-workout-v1',
        modelName: 'claude-sonnet-4-6',
        outputMarkdown: '**Recovery protocol:** refuel within 20 minutes.',
        recoveryDecision: { excluded: false, status: 'ready_for_review' },
        timeSeriesSummary: { power: { avg: 220 } },
        intervals: [],
        execution: {},
        tomorrowImpact: 'Easy endurance tomorrow.',
        postRideCheckIn: null,
      },
    ];
  });

const postRideWithIntervalsSnapshot = () =>
  buildSnapshot((snapshot) => {
    snapshot.data.postWorkoutAnalyses = [
      {
        id: '66666666-6666-4666-8666-666666666666',
        activityId: '77777777-7777-4777-8777-777777777777',
        activityName: 'Sweet spot ride',
        activityType: 'indoor_cycling',
        generatedAtUtc: '2026-06-20T12:20:00Z',
        promptVersion: 'post-workout-analysis-v2-2026-07-03',
        modelName: 'claude',
        outputMarkdown: '**Rating:** strong, held the work on target.',
        recoveryDecision: { excluded: false, status: 'ready_for_review' },
        timeSeriesSummary: { power: { avg: 210 } },
        intervals: [
          { index: 0, label: 'Warm-up', role: 'warmup', durationSec: 600, adherence: null, fade: null },
          {
            index: 1,
            label: 'Sweet spot',
            role: 'work',
            durationSec: 1200,
            pctFtp: 91,
            normalizedPowerWatts: 255,
            targetPctFtpLow: 91,
            targetPctFtpHigh: 91,
            adherence: 'on',
            fade: false,
          },
        ],
        execution: { hasPlan: true, workIntervalCount: 1 },
        tomorrowImpact: 'Easy endurance tomorrow.',
        postRideCheckIn: null,
      },
    ];
  });

function renderPage(snapshot = baseSnapshot) {
  apiFetchMock.mockClear(); // isolate each test's call history (negative assertions)
  apiFetchMock.mockImplementation((path: string) => {
    if (path === '/api/v1/daily-loop') {
      return Promise.resolve(snapshot);
    }
    if (path.startsWith('/api/v1/bedroom/overnight')) {
      return Promise.resolve(overnightSnapshot);
    }
    if (path.includes('/api/v1/workout-delivery/planned-workouts/')) {
      return Promise.resolve({ data: { proposals: [] }, meta: { generatedAtUtc: '2026-06-20T06:45:00Z' }, errors: [] });
    }
    if (path.includes('/api/v1/plan-actions/')) {
      return Promise.resolve({ data: {}, meta: { generatedAtUtc: '2026-06-20T06:45:00Z' }, errors: [] });
    }
    if (path.includes('/post-ride-check-in')) {
      return Promise.resolve(snapshot);
    }
    return Promise.reject(new Error(`Unexpected request: ${path}`));
  });

  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const WORKOUT_ID = '55555555-5555-4555-8555-555555555555';

afterEach(() => {
  vi.useRealTimers();
  onlineStatus = true;
});

describe('DashboardPage', () => {
  it('pre-ride expands Today and keeps every other section collapsed-but-present', async () => {
    renderPage();

    // Today is the primary → expanded: its body controls are live.
    expect(await screen.findByText('Cycle day')).toBeTruthy();
    expect(screen.getByText('Tempo ride')).toBeTruthy();
    expect(screen.getByRole('button', { name: /^edit$/i })).toBeTruthy();
    expect(screen.getByRole('button', { name: /swap day/i })).toBeTruthy();
    expect(screen.getByRole('button', { name: /^skip$/i })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /approve & upload/i })).toBeNull();
    // Batch 50: the verdict renders once (the VerdictHero) — the duplicated Today
    // header badge was dropped.
    expect(screen.getAllByText('Good to go').length).toBe(1);

    // Object permanence: the other sections are present but collapsed — their
    // summaries are in the DOM, their (lazy) bodies are not.
    expect(screen.getByText("Last night's sleep")).toBeTruthy();
    expect(screen.getByText(/8h 0m asleep/)).toBeTruthy();
    expect(screen.getByText('Tonight')).toBeTruthy();
    expect(screen.getByText('Bedroom')).toBeTruthy();
    expect(screen.getByText(/Indoor 17\.4°C/)).toBeTruthy();
    // Collapsed → the Last night body (comparison table, /brief link, overnight
    // glance) has not mounted yet, so the bedroom-overnight query stays lazy.
    expect(screen.queryByText('23 above')).toBeNull();
    expect(screen.queryByRole('link', { name: /full morning brief/i })).toBeNull();
    expect(screen.queryByTestId('overnight-room-verdict-badge')).toBeNull();
    // No ride analysed today → the ride-only sections aren't in the list at all.
    expect(screen.queryByText('After your ride')).toBeNull();
    expect(screen.queryByText('Tomorrow')).toBeNull();
  });

  it('places sections in the Batch 51 act/context desktop columns without changing the mobile stack', async () => {
    renderPage();
    await screen.findByText('Cycle day');

    // Act lane: today's plan card gets column 1 on md+…
    const todayCard = screen.getByRole('button', { name: /cycle day/i }).closest('#home-section-today');
    expect(todayCard?.className).toContain('md:col-start-1');
    // …context lane: the sleep/bedroom cards get column 2…
    const lastNightCard = screen
      .getByRole('button', { name: /last night's sleep/i })
      .closest('#home-section-lastNight');
    expect(lastNightCard?.className).toContain('md:col-start-2');
    const tonightCard = screen.getByText('Tonight').closest('#home-section-tonight');
    expect(tonightCard?.className).toContain('md:col-start-2');
    const bedroomCard = screen.getByText('Bedroom').closest('#home-section-bedroom');
    expect(bedroomCard?.className).toContain('md:col-start-2');
    // …and every card still shares one `grid-cols-1` container, so mobile
    // renders the exact same single stacked column as before this batch.
    expect(todayCard?.parentElement).toBe(lastNightCard?.parentElement);
    expect(todayCard?.parentElement?.className).toContain('grid-cols-1');
  });

  it('reveals a collapsed section body only when it is expanded (lazy)', async () => {
    const user = userEvent.setup();
    renderPage();

    await screen.findByText('Cycle day');
    expect(screen.queryByText('23 above')).toBeNull();
    expect(screen.queryByTestId('overnight-room-verdict-badge')).toBeNull();

    // Tap the collapsed Last-night header → its body mounts.
    await user.click(screen.getByRole('button', { name: /last night's sleep/i }));

    expect(await screen.findByText('23 above')).toBeTruthy(); // VO₂max vs age, age-only row
    expect(screen.getByRole('link', { name: /full morning brief/i }).getAttribute('href')).toBe('/brief');
    // Batch 35: the standalone baselines page is retired — no baselines link.
    expect(screen.queryByRole('link', { name: /baselines/i })).toBeNull();
    // The overnight glance (a separate query) only fires now that the body is open.
    expect(await screen.findByText('Last night: 19→21 °C, fan ran 3.5 h (peak speed 5)')).toBeTruthy();
    expect((await screen.findByTestId('overnight-room-verdict-badge')).textContent).toBe('Red');
  });

  it('renders the personalized sleep projection in Tonight', async () => {
    const user = userEvent.setup();
    renderPage(
      buildSnapshot((snapshot) => {
        snapshot.data.sleepProjection = {
          status: 'personalized',
          tone: 'protect',
          headline: "Protect tonight's wind-down",
          summary: 'A late hard session plus a warm room may make sleep more fragile.',
          evidence: ['Latest session started 18:05.', 'Bedroom is currently 20.1C.'],
          prepActions: [
            'Let Auto manage the pre-cool; check Bedroom if the room is still warm near 22:00.',
            'Bring the wind-down forward: breathing at 20:00 and snack finished by 21:30.',
          ],
          protocol: {
            preCoolTemperatureC: 17,
            coherenceBreathingTime: '20:00',
            latestSnackTime: '21:30',
            sealTargetTime: '22:00',
            bedtime: '23:15',
          },
        };
      }),
    );

    await screen.findByText('Cycle day');
    await user.click(screen.getByRole('button', { name: /tonight/i }));

    expect(screen.getByText("Protect tonight's wind-down")).toBeTruthy();
    expect(screen.getByText(/late hard session/)).toBeTruthy();
    expect(screen.getByText(/Let Auto manage/)).toBeTruthy();
    expect(screen.getByText('Evidence')).toBeTruthy();
    expect(screen.getByText('Latest session started 18:05.')).toBeTruthy();
  });

  it('renders a flexibility analysis on the Today section', async () => {
    renderPage(
      buildSnapshot((snapshot) => {
        snapshot.data.plannedWorkouts = [
          {
            ...snapshot.data.plannedWorkouts[0],
            title: 'Mobility',
            workoutType: 'mobility',
            plannedDurationMin: 16,
            intensityTarget: 'Easy mobility',
          },
        ];
        snapshot.data.postFlexibilityAnalyses = [
          {
            id: '99999999-9999-4999-8999-999999999999',
            activityId: '99999999-1111-4111-8111-999999999999',
            activityName: '16 Min Mobility Workout',
            activityType: 'other',
            generatedAtUtc: '2026-06-20T08:20:00Z',
            promptVersion: 'post-flexibility-v1',
            modelName: 'claude-sonnet-4-6',
            outputMarkdown: '**Mobility read:** relaxed and consistent.',
            heartRateReview: { avgAboveRestingBpm: 24 },
            consistency: { currentStreak: 3, sessions4w: 18 },
            activityCheckIn: null,
          },
        ];
      }),
    );

    expect(await screen.findByText('Flexibility day')).toBeTruthy();
    expect(screen.getByText('Flexibility read')).toBeTruthy();
    expect(screen.getByText('16 Min Mobility Workout')).toBeTruthy();
    expect(screen.getByText('Mobility read:')).toBeTruthy();
    expect(screen.getByText(/relaxed and consistent/i)).toBeTruthy();
    expect(screen.getByText('Advisory')).toBeTruthy();
  });

  it('renders a strength analysis on the Today section', async () => {
    renderPage(
      buildSnapshot((snapshot) => {
        snapshot.data.plannedWorkouts = [
          {
            ...snapshot.data.plannedWorkouts[0],
            title: 'Strength maintenance',
            workoutType: 'strength',
            plannedDurationMin: 30,
            intensityTarget: 'Maintenance',
          },
        ];
        snapshot.data.postStrengthAnalyses = [
          {
            id: '88888888-8888-4888-8888-888888888888',
            activityId: '88888888-1111-4111-8111-888888888888',
            activityName: 'Upper Body Strength',
            activityType: 'strength_training',
            generatedAtUtc: '2026-06-20T08:20:00Z',
            promptVersion: 'post-strength-v1',
            modelName: 'claude-sonnet-4-6',
            outputMarkdown: '**Strength read:** steady work, HR sat low.',
            heartRateReview: { avgAboveRestingBpm: 40 },
            consistency: { sessions4w: 6, trend: 'stable' },
            activityCheckIn: null,
          },
        ];
      }),
    );

    expect(await screen.findByText('Strength read')).toBeTruthy();
    expect(screen.getByText('Upper Body Strength')).toBeTruthy();
    expect(screen.getByText('Strength read:')).toBeTruthy();
    expect(screen.getByText(/steady work/i)).toBeTruthy();
  });

  it('renders walking, breathwork, and deliberate-walk reads on the Today section', async () => {
    renderPage(
      buildSnapshot((snapshot) => {
        snapshot.data.postWalkAnalyses = [
          {
            id: 'aaaaaaaa-9999-4999-8999-999999999999',
            activityId: 'aaaaaaaa-1111-4111-8111-999999999999',
            activityName: 'Morning Walk',
            activityType: 'walking',
            generatedAtUtc: '2026-06-20T08:40:00Z',
            promptVersion: 'post-walk-v1',
            modelName: 'claude-sonnet-4-6',
            outputMarkdown: '**Walk read:** easy aerobic work.',
            heartRateReview: { avgHeartRateBpm: 104 },
            paceReview: { avgPaceMinPerKm: 10.2 },
            activeRecoveryContext: { deliberateWalkCount: 1 },
            activityCheckIn: null,
          },
        ];
      }),
    );

    expect(await screen.findByText('Walking base')).toBeTruthy();
    expect(screen.getByText(/6 walks · 18.5 km · 250 min/i)).toBeTruthy();
    expect(screen.getByText('Breathwork rhythm')).toBeTruthy();
    expect(screen.getByText(/18 sessions · 54 min in 4 weeks/i)).toBeTruthy();
    expect(screen.getByText('Walk read')).toBeTruthy();
    expect(screen.getByText('Morning Walk')).toBeTruthy();
    expect(screen.getByText('Walk read:')).toBeTruthy();
  });

  it('edits today’s session with the duration and intensity dials', async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole('button', { name: /^edit$/i }));
    await user.clear(screen.getByLabelText('Duration percentage'));
    await user.type(screen.getByLabelText('Duration percentage'), '80');
    await user.clear(screen.getByLabelText('Intensity percentage'));
    await user.type(screen.getByLabelText('Intensity percentage'), '90');
    await user.click(screen.getByRole('button', { name: /apply & sync/i }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        `/api/v1/workout-delivery/planned-workouts/${WORKOUT_ID}/edit`,
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ durationScalePct: 80, intensityScalePct: 90 }),
        }),
      );
    });
  });

  it('skips today’s session after confirming', async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole('button', { name: /^skip$/i }));
    await user.click(await screen.findByRole('button', { name: /confirm skip/i }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        `/api/v1/workout-delivery/planned-workouts/${WORKOUT_ID}/skip`,
        expect.objectContaining({ method: 'POST' }),
      );
    });
  });

  it('swaps the session to another day', async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole('button', { name: /swap day/i }));
    const hint = await screen.findByText('Move this session to:');
    const dayButtons = within(hint.parentElement as HTMLElement).getAllByRole('button');
    await user.click(dayButtons[0]); // first option = the day after subjectDate (2026-06-21)

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        `/api/v1/workout-delivery/planned-workouts/${WORKOUT_ID}/swap`,
        expect.objectContaining({ method: 'POST', body: JSON.stringify({ targetDate: '2026-06-21' }) }),
      );
    });
  });

  it('shows the coach-changed state and approves the adjustment', async () => {
    const user = userEvent.setup();
    renderPage(
      buildSnapshot((snapshot) => {
        snapshot.data.morningAnalysis!.verdict = 'amber';
        snapshot.data.morningAnalysis!.planAdjustments = ['Cut it to 75% and drop the VO2 set.'];
        snapshot.data.plannedWorkouts[0].delivery = {
          liveStatus: 'pushed',
          liveOrigin: 'as_planned',
          intervalsEventId: 'evt_1',
          changed: true,
          adjustment: { verdict: 'Amber', changed: true },
        };
      }),
    );

    expect(await screen.findByText('Cut it to 75% and drop the VO2 set.')).toBeTruthy();
    expect(screen.getByRole('button', { name: /manual edit/i })).toBeTruthy();
    await user.click(screen.getByRole('button', { name: /approve & upload/i }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        `/api/v1/workout-delivery/planned-workouts/${WORKOUT_ID}/approve-adjustment`,
        expect.objectContaining({ method: 'POST' }),
      );
    });
  });

  it('dismisses the coach suggestion with Ignore (no backend call)', async () => {
    const user = userEvent.setup();
    renderPage(
      buildSnapshot((snapshot) => {
        snapshot.data.plannedWorkouts[0].delivery = {
          liveStatus: 'pushed',
          liveOrigin: 'as_planned',
          intervalsEventId: 'evt_1',
          changed: true,
          adjustment: { verdict: 'Amber', changed: true },
        };
      }),
    );

    await user.click(await screen.findByRole('button', { name: /ignore/i }));

    // Falls back to the no-changes state; Ignore never hits the backend.
    expect(screen.queryByRole('button', { name: /approve & upload/i })).toBeNull();
    expect(screen.getByRole('button', { name: /^edit$/i })).toBeTruthy();
    expect(apiFetchMock).not.toHaveBeenCalledWith(
      expect.stringContaining('/approve-adjustment'),
      expect.anything(),
    );
  });

  it('renders one Today card for a mixed day with each session scoped independently', async () => {
    const user = userEvent.setup();
    const secondWorkoutId = '99999999-9999-4999-9999-999999999999';
    renderPage(
      buildSnapshot((snapshot) => {
        snapshot.data.plannedWorkouts = [
          snapshot.data.plannedWorkouts[0],
          {
            id: secondWorkoutId,
            userId: '11111111-1111-4111-8111-111111111111',
            planBlockId: null,
            workoutDate: '2026-06-20',
            version: 1,
            title: 'Core strength',
            workoutType: 'strength',
            status: 'planned',
            isActive: true,
            plannedDurationMin: 30,
            intensityTarget: null,
            structuredWorkout: {},
            source: 'seed',
            adherence: null,
          },
        ];
      }),
    );

    expect(await screen.findByText('Cycle + Weights day')).toBeTruthy();
    expect(screen.getByText('Tempo ride')).toBeTruthy();
    expect(screen.getByText('Core strength')).toBeTruthy();
    // Batch 50: the verdict renders once (the VerdictHero) — not per session, and
    // no longer duplicated on the Today header.
    expect(screen.getAllByText('Good to go').length).toBe(1);
    // Only the bike session gets an Edit control; the strength row has none.
    expect(screen.getAllByRole('button', { name: /^edit$/i }).length).toBe(1);

    const swapButtons = screen.getAllByRole('button', { name: /swap day/i });
    expect(swapButtons.length).toBe(2);
    await user.click(swapButtons[1]); // the second (strength) session's own panel
    const hint = await screen.findByText('Move this session to:');
    const dayButtons = within(hint.parentElement as HTMLElement).getAllByRole('button');
    await user.click(dayButtons[0]);

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        `/api/v1/workout-delivery/planned-workouts/${secondWorkoutId}/swap`,
        expect.objectContaining({ method: 'POST', body: JSON.stringify({ targetDate: '2026-06-21' }) }),
      );
    });
    // The first (bike) session's swap panel never opened.
    expect(apiFetchMock).not.toHaveBeenCalledWith(
      `/api/v1/workout-delivery/planned-workouts/${WORKOUT_ID}/swap`,
      expect.anything(),
    );
  });

  it('leads with a non-bike session and offers no Zwift upload', async () => {
    renderPage(
      buildSnapshot((snapshot) => {
        snapshot.data.plannedWorkouts = [
          {
            id: '88888888-8888-4888-8888-888888888888',
            userId: '11111111-1111-4111-8111-111111111111',
            planBlockId: null,
            workoutDate: '2026-06-20',
            version: 1,
            title: 'Strength routine',
            workoutType: 'strength',
            status: 'planned',
            isActive: true,
            plannedDurationMin: 30,
            intensityTarget: null,
            structuredWorkout: {},
            source: 'seed',
            adherence: null,
          },
        ];
      }),
    );

    expect(await screen.findByText('Strength routine')).toBeTruthy();
    expect(screen.getByText('Non-bike session — nothing to upload to Zwift.')).toBeTruthy();
    expect(screen.getByRole('button', { name: /swap day/i })).toBeTruthy();
    expect(screen.getByRole('button', { name: /^skip$/i })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /^edit$/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /approve & upload/i })).toBeNull();
  });

  it('post-ride expands After your ride but keeps Today and Last night present', async () => {
    renderPage(postRideSnapshot());

    // After your ride is primary → expanded: its body + check-in form show.
    expect(await screen.findByText('After your ride')).toBeTruthy();
    expect(screen.getByText('How did it feel?')).toBeTruthy();
    // The ride-only sections exist now.
    expect(screen.getByText('Tomorrow')).toBeTruthy();
    expect(screen.getByText('Tonight')).toBeTruthy();
    expect(screen.getByText('Bedroom')).toBeTruthy();

    // Object permanence: Today + Last night are still on Home (collapsed), not gone.
    expect(screen.getByText('Cycle day')).toBeTruthy();
    expect(screen.getByText("Last night's sleep")).toBeTruthy();
    expect(screen.getByText(/8h 0m asleep/)).toBeTruthy(); // collapsed sleep summary
    // Bedroom is collapsed → its fan body has not mounted; the overnight glance
    // (in the collapsed Last-night body) hasn't mounted either.
    expect(screen.queryByText('Bedroom fan')).toBeNull();
    expect(screen.queryByText('Last night: 19→21 °C, fan ran 3.5 h (peak speed 5)')).toBeNull();
  });

  it('shows the interval execution table grading only the work intervals', async () => {
    renderPage(postRideWithIntervalsSnapshot());

    expect(await screen.findByText('Interval execution')).toBeTruthy();
    // The work interval is listed and graded; warm-up is not in the table.
    expect(screen.getByText('20 min Sweet spot')).toBeTruthy();
    expect(screen.getByText('On target')).toBeTruthy();
    expect(screen.queryByText('10 min Warm-up')).toBeNull();
  });

  it('renders no interval table for a ride without planned structure', async () => {
    renderPage(postRideSnapshot());

    await screen.findByText('After your ride');
    expect(screen.queryByText('Interval execution')).toBeNull();
  });

  it('saves the post-ride check-in from the ride card', async () => {
    const user = userEvent.setup();
    renderPage(postRideSnapshot());

    await screen.findByText('How did it feel?');
    await user.type(screen.getByLabelText('RPE'), '8');
    await user.type(screen.getByLabelText('Legs'), '6');
    await user.type(screen.getByLabelText('Feel'), 'hard but fair');
    await user.type(screen.getByLabelText('Niggles or notes'), 'Left calf tight.');
    await user.click(screen.getByRole('button', { name: /save ride check-in/i }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/daily-loop/2026-06-20/activities/77777777-7777-4777-8777-777777777777/post-ride-check-in',
        expect.objectContaining({
          method: 'PUT',
          body: JSON.stringify({
            subjectiveScore: 6,
            rpe: 8,
            feel: 'hard but fair',
            notes: 'Left calf tight.',
          }),
        }),
      );
    });
  });

  it('rest day expands Last night and keeps the day plan collapsed-but-present', async () => {
    const user = userEvent.setup();
    renderPage(
      buildSnapshot((snapshot) => {
        snapshot.data.plannedWorkouts = [];
      }),
    );

    // Last night is primary → expanded (comparison table visible in the body).
    expect(await screen.findByText("Last night's sleep")).toBeTruthy();
    expect(screen.getByText('23 above')).toBeTruthy();
    // The day plan is present but collapsed: 'Rest day' title + short summary.
    expect(screen.getByText('Rest day')).toBeTruthy();
    expect(screen.getByText('Rest is the plan today.')).toBeTruthy();
    // Its body (empty-state + "I did something else") is hidden until expanded.
    expect(screen.queryByRole('button', { name: /i did something else/i })).toBeNull();

    await user.click(screen.getByRole('button', { name: /rest day/i }));
    expect(await screen.findByText(/Rest is the plan today\. Add something light/)).toBeTruthy();
    expect(screen.getByRole('button', { name: /i did something else/i })).toBeTruthy();
    expect(screen.queryByText('After your ride')).toBeNull();
  });

  it('after 20:00 floats the bedroom-prep sections above Last night (order only)', async () => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date('2026-06-20T21:30:00'));
    renderPage(); // pre-ride default

    await screen.findByText('Cycle day');
    const tonight = screen.getByText('Tonight');
    const bedroom = screen.getByText('Bedroom');
    const lastNight = screen.getByText("Last night's sleep");
    // Evening: Tonight + Bedroom now sit ahead of Last night in the DOM…
    expect(tonight.compareDocumentPosition(lastNight) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(bedroom.compareDocumentPosition(lastNight) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // …but nothing is added or removed by the clock — every section still exists.
    expect(screen.getByText('Cycle day')).toBeTruthy();
    expect(tonight).toBeTruthy();
    expect(bedroom).toBeTruthy();
    expect(lastNight).toBeTruthy();
  });

  it('renders the morning check-in action in the Next strip by default (Batch 50)', async () => {
    renderPage(); // base: not checked in, nothing else pending → check-in rung
    const strip = await screen.findByRole('region', { name: 'Next action' });
    // Named "Morning check-in" (not just "Check in") so it reads distinctly
    // from the per-ride "Log how {ride} felt" action.
    const cta = within(strip).getByRole('link', { name: /morning check-in/i });
    expect(cta.getAttribute('href')).toBe('/check-in');
  });

  it('overrides the phase primary to expand Today for a pending change and flags the collapsed ride card (Batch 50)', async () => {
    renderPage(
      buildSnapshot((snapshot) => {
        // A ride was analysed today, its check-in still unlogged…
        snapshot.data.postWorkoutAnalyses = [
          {
            id: '66666666-6666-4666-8666-666666666666',
            activityId: '77777777-7777-4777-8777-777777777777',
            activityName: 'Tempo ride',
            activityType: 'indoor_cycling',
            generatedAtUtc: '2026-06-20T12:20:00Z',
            promptVersion: 'post-workout-v1',
            modelName: 'claude-sonnet-4-6',
            outputMarkdown: '**Recovery protocol:** refuel within 20 minutes.',
            recoveryDecision: { excluded: false, status: 'ready_for_review' },
            timeSeriesSummary: { power: { avg: 220 } },
            intervals: [],
            execution: {},
            tomorrowImpact: 'Easy endurance tomorrow.',
            postRideCheckIn: null,
          },
        ];
        // …and the coach also eased today's bike session (the higher-priority action).
        snapshot.data.plannedWorkouts[0].delivery = {
          liveStatus: 'pushed',
          liveOrigin: 'as_planned',
          intervalsEventId: 'evt_1',
          changed: true,
          adjustment: { verdict: 'Amber', changed: true },
        };
      }),
    );

    // The Next strip surfaces the top action (the pending change), not the check-in.
    const strip = await screen.findByRole('region', { name: 'Next action' });
    expect(within(strip).getByText("Review today's eased ride")).toBeTruthy();

    // The action override makes Today lead + expand regardless of phase/clock —
    // even though a ride was analysed (which would otherwise lead After-your-ride).
    expect(screen.getByRole('button', { name: /approve & upload/i })).toBeTruthy();

    // After-your-ride is collapsed (its check-in form isn't mounted) but its
    // header carries the "needs a tap" warning dot.
    expect(screen.queryByText('How did it feel?')).toBeNull();
    expect(screen.getByLabelText('Needs attention')).toBeTruthy();
  });

  it('shows an all-clear Next strip when nothing needs a decision (Batch 50)', async () => {
    renderPage(
      buildSnapshot((snapshot) => {
        snapshot.data.manualEntry = {
          id: '12121212-1212-4121-8121-121212121212',
          userId: '11111111-1111-4111-8111-111111111111',
          entryDate: '2026-06-20',
          entryAtUtc: '2026-06-20T07:00:00Z',
          actualWorkoutJson: {},
          supplementsJson: {},
          foodJson: {},
        };
      }),
    );

    await screen.findByText('Cycle day');
    expect(screen.getByText(/you're all set/i)).toBeTruthy();
    // The all-clear state is a quiet status line, not a primary-action region.
    expect(screen.queryByRole('region', { name: 'Next action' })).toBeNull();
  });

  it('shows the offline banner while keeping Home visible', async () => {
    onlineStatus = false;
    renderPage();

    expect((await screen.findByRole('status')).textContent ?? '').toMatch(/showing your last saved brief/i);
    expect(screen.getByText('Cycle day')).toBeTruthy(); // the Today section still renders
  });
});
