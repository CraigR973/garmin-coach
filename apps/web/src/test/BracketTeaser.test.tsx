import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BracketTeaser } from '@/components/BracketTeaser';

vi.mock('@/lib/api', () => ({
  apiFetch: vi.fn(),
}));

import { apiFetch } from '@/lib/api';
const mockApiFetch = vi.mocked(apiFetch);

function makeQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function renderTeaser(props?: Partial<Parameters<typeof BracketTeaser>[0]>) {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <MemoryRouter>
        <BracketTeaser
          title={props?.title ?? 'The bracket arrives after group stage'}
          ctaLabel={props?.ctaLabel ?? 'Make your group-stage picks →'}
          ctaTo={props?.ctaTo ?? '/predictions'}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockApiFetch.mockReset();
  // Default: no R32 matches available
  mockApiFetch.mockResolvedValue([]);
});

describe('BracketTeaser', () => {
  it('renders the title', async () => {
    renderTeaser();
    await waitFor(() =>
      expect(screen.getByText('The bracket arrives after group stage')).toBeTruthy(),
    );
  });

  it('renders the CTA link with correct text and href', async () => {
    renderTeaser();
    await waitFor(() => {
      const link = screen.getByRole('link', { name: /group-stage picks/i });
      expect(link).toBeTruthy();
      expect(link.getAttribute('href')).toBe('/predictions');
    });
  });

  it('shows "—" when no R32 match kickoff is available', async () => {
    renderTeaser();
    await waitFor(() => expect(screen.getByText('—')).toBeTruthy());
  });

  it('shows countdown when an R32 kickoff is returned', async () => {
    const futureKickoff = new Date(Date.now() + 2 * 24 * 60 * 60 * 1000).toISOString();
    mockApiFetch.mockResolvedValue([
      {
        id: 'm-r32',
        match_number: 73,
        stage: 'r32',
        group_id: null,
        home_team: null,
        away_team: null,
        home_team_placeholder: '1A',
        away_team_placeholder: '2B',
        kickoff_utc: futureKickoff,
        venue: null,
        status: 'scheduled',
        actual_home_score: null,
        actual_away_score: null,
        extra_time: false,
        penalties: false,
        postponed_reason: null,
      },
    ]);

    renderTeaser();
    await waitFor(
      () => expect(screen.getByText(/Kicks off in/i)).toBeTruthy(),
      { timeout: 3000 },
    );
  });

  it('renders the R32 SVG silhouette', async () => {
    renderTeaser();
    await waitFor(() => {
      const svg = document.querySelector('svg[aria-hidden="true"]');
      expect(svg).not.toBeNull();
      expect(svg!.querySelectorAll('rect').length).toBe(16);
    });
  });

  it('renders different title for knockout variant', async () => {
    renderTeaser({ title: 'Knockout picks open after group stage', ctaTo: '/predictions/specials' });
    await waitFor(() =>
      expect(screen.getByText('Knockout picks open after group stage')).toBeTruthy(),
    );
  });
});
