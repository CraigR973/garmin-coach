import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import userEvent from '@testing-library/user-event';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { DailyLoopEnvelope } from '@/hooks/useDailyLoop';
import { SettingsPage } from './SettingsPage';

const apiFetchMock = vi.fn();

vi.mock('@/lib/api', () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock('../hooks/usePushSubscription', () => ({
  usePushSubscription: () => ({ isSubscribed: false, isLoading: false, subscribe: vi.fn(), unsubscribe: vi.fn() }),
}));

vi.mock('../hooks/useInstallPrompt', () => ({
  useInstallPrompt: () => ({ canInstall: false, prompt: vi.fn() }),
}));

vi.mock('../contexts/ThemeContext', () => ({
  useTheme: () => ({ mode: 'system', setMode: vi.fn() }),
}));

function makeSnapshot(hostedTtsConsent: boolean): DailyLoopEnvelope {
  return {
    data: {
      subjectDate: '2026-07-14',
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
      hostedTtsConsent,
      holiday: { isActive: false, activeWindow: null },
      thermalState: {
        latestTemperatureC: null,
        targetTemperatureC: null,
        capturedAtUtc: null,
        overnightLowC: null,
        overnightWindMaxMph: null,
        overnightWindGustMph: null,
        thermalReview: {},
        fans: [],
      },
      dataQualityWarnings: [],
      walkingBrief: {
        asOfDate: '2026-07-14',
        window4w: { sessionCount: 0, totalDistanceM: 0, totalDurationMin: 0, sessionsPerWeek: 0 },
        window12w: { sessionCount: 0, totalDistanceM: 0, totalDurationMin: 0, sessionsPerWeek: 0 },
        recentSessions: [],
        trend: 'insufficient_data',
        trendReason: 'Only 0 walk(s) in the last 28 days.',
      },
    },
    meta: { generatedAtUtc: '2026-07-14T06:00:00Z' },
    errors: [],
  } as unknown as DailyLoopEnvelope;
}

function renderWithQuery(ui: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  apiFetchMock.mockReset();
});

describe('SettingsPage Voice section', () => {
  it('reflects the current hostedTtsConsent value from the daily-loop payload', async () => {
    apiFetchMock.mockResolvedValue(makeSnapshot(true));
    renderWithQuery(<SettingsPage />);

    const toggle = await screen.findByRole('switch', { name: 'Enable hosted read-aloud voice' });
    await waitFor(() => expect(toggle.getAttribute('aria-checked')).toBe('true'));
  });

  it('toggling the switch PUTs the new consent value', async () => {
    apiFetchMock.mockImplementation((path: string) => {
      if (path.startsWith('/api/v1/daily-loop')) return Promise.resolve(makeSnapshot(false));
      return Promise.resolve(undefined);
    });
    const user = userEvent.setup();
    renderWithQuery(<SettingsPage />);

    const toggle = await screen.findByRole('switch', { name: 'Enable hosted read-aloud voice' });
    await waitFor(() => expect(toggle.getAttribute('aria-checked')).toBe('false'));

    await user.click(toggle);

    await waitFor(() =>
      expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/tts/consent', {
        method: 'PUT',
        body: JSON.stringify({ enabled: true }),
      }),
    );
  });
});
