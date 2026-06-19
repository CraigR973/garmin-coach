import type { ReactNode } from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MotionConfig } from 'framer-motion';
import { AuthProvider } from '@/contexts/AuthContext';
import { LeagueProvider } from '@/contexts/LeagueContext';
import { ScoreInput } from '@/components/ui/score-input';
import { SaveButton } from '@/components/ui/save-button';
import { LeaderboardPage } from '@/pages/LeaderboardPage';
import type { LeaderboardEntry } from '@/lib/types';

// ---------------------------------------------------------------------------
// MotionConfig helpers — framer-motion's `useReducedMotion` reads matchMedia
// once at subscription time, so jsdom matchMedia stubs are unreliable. The
// supported override is `MotionConfig.reducedMotion`, which forces the hook
// to return a deterministic value for everything inside the tree.
// ---------------------------------------------------------------------------

function WithMotion({ reduced, children }: { reduced: boolean; children: ReactNode }) {
  return (
    <MotionConfig reducedMotion={reduced ? 'always' : 'never'}>{children}</MotionConfig>
  );
}

// ---------------------------------------------------------------------------
// ScoreInput — reduced-motion fallback
// ---------------------------------------------------------------------------

describe('ScoreInput', () => {
  it('shows the animated digit overlay when motion is allowed', () => {
    render(
      <WithMotion reduced={false}>
        <ScoreInput value="3" onChange={() => {}} aria-label="Home score" />
      </WithMotion>,
    );

    const input = screen.getByLabelText('Home score') as HTMLInputElement;
    expect(input.value).toBe('3');
    expect(input.className).toContain('text-transparent');
  });

  it('skips the animated overlay under prefers-reduced-motion', () => {
    render(
      <WithMotion reduced>
        <ScoreInput value="3" onChange={() => {}} aria-label="Home score" />
      </WithMotion>,
    );

    const input = screen.getByLabelText('Home score') as HTMLInputElement;
    // Native input renders the value directly with full opacity — no
    // `text-transparent` because the animated overlay isn't mounted.
    expect(input.value).toBe('3');
    expect(input.className).not.toContain('text-transparent');
  });

  it('calls onChange when the increment chevron is clicked', () => {
    const onChange = vi.fn();
    render(
      <WithMotion reduced={false}>
        <ScoreInput value="1" onChange={onChange} aria-label="Home score" />
      </WithMotion>,
    );

    const btn = screen.getByLabelText('Increment Home score');
    btn.click();
    expect(onChange).toHaveBeenCalledWith('2');
  });
});

// ---------------------------------------------------------------------------
// SaveButton — state-machine + reduced-motion check icon
// ---------------------------------------------------------------------------

describe('SaveButton', () => {
  it('renders idle label and is enabled when not saving', () => {
    render(
      <WithMotion reduced={false}>
        <SaveButton state="idle" idleLabel="Save" />
      </WithMotion>,
    );
    expect(screen.getAllByText('Save').length).toBeGreaterThan(0);
  });

  it('renders saved label with check icon when state=saved', () => {
    const { container } = render(
      <WithMotion reduced={false}>
        <SaveButton state="saved" idleLabel="Save" savedLabel="Saved" />
      </WithMotion>,
    );
    expect(screen.getAllByText('Saved').length).toBeGreaterThan(0);
    expect(container.querySelector('svg')).not.toBeNull();
  });

  it('renders the check icon fully drawn under reduced motion (no draw-in animation)', () => {
    const { container } = render(
      <WithMotion reduced>
        <SaveButton state="saved" idleLabel="Save" savedLabel="Saved" />
      </WithMotion>,
    );
    const path = container.querySelector('svg path');
    expect(path).not.toBeNull();
    // Under reduced motion the path's `pathLength` starts at 1 — i.e. it is
    // drawn statically. framer-motion writes the interpolated pathLength into
    // the inline style only while animating from 0 → 1; when it is rendered
    // at its final value from the start, the style does NOT contain the
    // mid-animation dasharray `0px 1px`.
    const style = path!.getAttribute('style') ?? '';
    expect(style).not.toContain('0px 1px');
  });

  it('disables the button while saving', () => {
    render(
      <WithMotion reduced={false}>
        <SaveButton state="saving" idleLabel="Save" />
      </WithMotion>,
    );
    const btn = screen.getByRole('button');
    expect((btn as HTMLButtonElement).disabled).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// LeaderboardPage — rank-delta pulse trigger logic
// ---------------------------------------------------------------------------

const FAKE_JWT = 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJwMSIsImV4cCI6OTk5OTk5OTk5OX0.fake';
const STORED_PLAYER = JSON.stringify({
  id: 'p1',
  displayName: 'Alice',
  role: 'player',
  timezone: 'UTC',
});

function entry(player_id: string, rank: number, total_points: number): LeaderboardEntry {
  return {
    player_id,
    player_name: `Player ${player_id}`,
    rank,
    total_points,
    match_points: total_points,
    knockout_winner_points: 0,
    special_points: 0,
    is_active: true,
    last_match_points: 0,
    today_points: 0,
    round_points: 0,
    snapshot_at: '2026-06-12T20:00:00Z',
  } as LeaderboardEntry;
}

function makeFetch(initial: LeaderboardEntry[]) {
  let current = initial;
  const fetchFn = vi.fn((url: string) => {
    if (url.includes('/leagues/mine')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(MOCK_LEAGUE) });
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve(current) });
  });
  return {
    fetchFn,
    setData(next: LeaderboardEntry[]) {
      current = next;
    },
  };
}

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 } },
  });
}

const MOCK_LEAGUE = [{ slug: 'steele-spreadsheet', name: 'The Steele Spreadsheet', description: null, privacy: 'private', member_count: 2, max_members: null, created_at: '2026-01-01T00:00:00Z' }];

function setupAuthStorage() {
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => {
      if (k === 'wc2026_player') return STORED_PLAYER;
      if (k === 'wc2026_access') return FAKE_JWT;
      return null;
    },
    setItem: vi.fn(),
    removeItem: vi.fn(),
    clear: vi.fn(),
  });
}

function renderLeaderboard(client: QueryClient, reduced: boolean) {
  return render(
    <WithMotion reduced={reduced}>
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <AuthProvider>
            <LeagueProvider>
              <LeaderboardPage />
            </LeagueProvider>
          </AuthProvider>
        </MemoryRouter>
      </QueryClientProvider>
    </WithMotion>,
  );
}

describe('LeaderboardPage — rank pulse trigger', () => {
  beforeEach(() => {
    setupAuthStorage();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('does not pulse on initial mount (no prior rank to compare against)', async () => {
    const { fetchFn } = makeFetch([entry('p1', 1, 10), entry('p2', 2, 8)]);
    vi.stubGlobal('fetch', fetchFn);

    renderLeaderboard(makeQueryClient(), false);

    await waitFor(() => expect(screen.getByTestId('leaderboard-row-p1')).toBeTruthy());
    const arrows = screen.getAllByTestId('rank-arrow');
    // Every arrow on the first render has data-pulsing="false" — there is
    // no previous snapshot to diff against.
    for (const a of arrows) {
      expect(a.getAttribute('data-pulsing')).toBe('false');
    }
  });

  it('pulses arrows whose rank changed between refetches', async () => {
    const handle = makeFetch([entry('p1', 1, 10), entry('p2', 2, 8)]);
    vi.stubGlobal('fetch', handle.fetchFn);

    const client = makeQueryClient();
    renderLeaderboard(client, false);

    await waitFor(() => expect(screen.getByTestId('leaderboard-row-p1')).toBeTruthy());

    // Now p2 overtakes p1.
    handle.setData([entry('p2', 1, 12), entry('p1', 2, 10)]);
    await act(async () => {
      await client.refetchQueries({ queryKey: ['leaderboard'] });
    });

    await waitFor(() => {
      const p1Row = screen.getByTestId('leaderboard-row-p1');
      const p1Arrow = p1Row.querySelector('[data-testid="rank-arrow"]');
      const p2Row = screen.getByTestId('leaderboard-row-p2');
      const p2Arrow = p2Row.querySelector('[data-testid="rank-arrow"]');
      expect(p1Arrow?.getAttribute('data-pulsing')).toBe('true');
      expect(p2Arrow?.getAttribute('data-pulsing')).toBe('true');
    });
  });

  it('does not pulse when reduced motion is preferred, even after a rank change', async () => {
    const handle = makeFetch([entry('p1', 1, 10), entry('p2', 2, 8)]);
    vi.stubGlobal('fetch', handle.fetchFn);

    const client = makeQueryClient();
    renderLeaderboard(client, true);

    await waitFor(() => expect(screen.getByTestId('leaderboard-row-p1')).toBeTruthy());

    handle.setData([entry('p2', 1, 12), entry('p1', 2, 10)]);
    await act(async () => {
      await client.refetchQueries({ queryKey: ['leaderboard'] });
    });

    // Even though the ranks swapped, reduced motion suppresses the pulse.
    await waitFor(() => {
      const arrows = screen.getAllByTestId('rank-arrow');
      for (const a of arrows) {
        expect(a.getAttribute('data-pulsing')).toBe('false');
      }
    });
  });
});
