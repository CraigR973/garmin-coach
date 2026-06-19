import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { RoundLeaderboardPage } from '@/pages/RoundLeaderboardPage';

const apiFetch = vi.fn();

vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
  return {
    ...actual,
    apiFetch: (...args: unknown[]) => apiFetch(...args),
  };
});

const ROUND_ROWS = [
  {
    rank: 1,
    player_id: 'p1',
    player_name: 'Alice',
    points: 18,
    exact_count: 2,
    correct_result_count: 5,
    correct_goals_count: 7,
    ko_winner_correct_count: 1,
  },
  {
    rank: 2,
    player_id: 'p2',
    player_name: 'Bob',
    points: 18,
    exact_count: 1,
    correct_result_count: 5,
    correct_goals_count: 7,
    ko_winner_correct_count: 1,
  },
];

function makeQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function renderPage(stage = 'qf', payload = ROUND_ROWS) {
  apiFetch.mockResolvedValue(payload);

  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <MemoryRouter initialEntries={[`/leagues/steele-spreadsheet/leaderboard/round/${stage}`]}>
        <Routes>
          <Route path="/leagues/:slug/leaderboard/round/:stage" element={<RoundLeaderboardPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
  apiFetch.mockReset();
});

describe('RoundLeaderboardPage', () => {
  it('renders tiebreak columns under a grouped header for the active round', async () => {
    renderPage('qf');

    await waitFor(() => {
      expect(screen.getByRole('columnheader', { name: /tiebreakers/i })).toBeInTheDocument();
      expect(screen.getByText('Ex')).toBeInTheDocument();
      expect(screen.getByText('Res')).toBeInTheDocument();
      expect(screen.getByText('Gls')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Quarter-finals' })).toBeInTheDocument();
    });
  });

  it('renders the round-scoped tiebreak counts from the payload', async () => {
    renderPage('qf');

    await waitFor(() => {
      expect(screen.getByText('Alice')).toBeInTheDocument();
    });

    const aliceRow = screen.getByText('Alice').closest('tr');
    expect(aliceRow).not.toBeNull();
    expect(aliceRow?.textContent).toContain('25718');
  });
});
