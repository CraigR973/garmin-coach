/**
 * U26.2 — scoring-examples render tests.
 *
 * Asserts that both ScoringGuide and AboutPage render all five achievable
 * per-match totals (0, 2, 3, 5, 10), that both pull from the same shared
 * source (scoringData), and that the specials grand total is correct.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { axe } from 'jest-axe';
import { ScoringGuide } from '@/components/ScoringGuide';
import { AboutPage } from '@/pages/AboutPage';
import {
  WORKED_EXAMPLES,
  SPECIALS_TOTAL,
  GRAND_TOTAL,
  SPECIAL_ROWS,
} from '@/lib/scoringData';

// Disable color-contrast: jsdom cannot evaluate CSS custom properties.
const AXE_CONFIG = { rules: { 'color-contrast': { enabled: false } } };

// ── Mocks required by AboutPage ───────────────────────────────────────────────

vi.mock('@/lib/api', () => ({
  apiFetch: vi.fn(),
}));

// ── Helpers ───────────────────────────────────────────────────────────────────

function makeQC() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function renderScoringGuide() {
  // Force open by clearing localStorage state.
  localStorage.clear();
  return render(<ScoringGuide />);
}

function renderAboutPage() {
  return render(
    <QueryClientProvider client={makeQC()}>
      <MemoryRouter>
        <AboutPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

// ── scoringData shape ─────────────────────────────────────────────────────────

describe('scoringData module', () => {
  it('has worked examples for all five achievable per-match totals', () => {
    const totals = WORKED_EXAMPLES.map((e) => e.total).sort((a, b) => a - b);
    expect(totals).toEqual([0, 2, 3, 5, 10]);
  });

  it('SPECIALS_TOTAL is 80 (6 specials: 20+15+15+10+10+10)', () => {
    expect(SPECIAL_ROWS).toHaveLength(6);
    expect(SPECIALS_TOTAL).toBe(80);
  });

  it('GRAND_TOTAL is 1415 (720+320+295+80)', () => {
    expect(GRAND_TOTAL).toBe(1415);
  });
});

// ── ScoringGuide ──────────────────────────────────────────────────────────────

describe('ScoringGuide — worked examples', () => {
  beforeEach(() => localStorage.clear());

  it('renders a cell for every achievable total (0, 2, 3, 5, 10)', () => {
    renderScoringGuide();
    for (const total of [0, 2, 3, 5, 10]) {
      const cells = document.querySelectorAll(`[data-example-total="${total}"]`);
      expect(cells.length).toBeGreaterThanOrEqual(1);
    }
  });

  it('renders the worked-examples section heading', () => {
    renderScoringGuide();
    expect(screen.getByText(/worked examples/i)).toBeTruthy();
  });

  it('has no axe violations', async () => {
    const { container } = renderScoringGuide();
    const results = await axe(container, AXE_CONFIG);
    expect(results).toHaveNoViolations();
  });
});

// ── AboutPage ─────────────────────────────────────────────────────────────────

describe('AboutPage — scoring clarity', () => {
  beforeEach(() => {
    vi.stubGlobal('IntersectionObserver', class {
      observe = vi.fn();
      disconnect = vi.fn();
      unobserve = vi.fn();
    });
  });

  it('renders all five achievable totals in the worked examples table', () => {
    renderAboutPage();
    // Each total rendered in a Pill — look for all five in the document.
    // The page renders them inside table cells; query by text content.
    for (const total of [0, 2, 3, 5, 10]) {
      // Find any element whose text is the string representation of the total
      // inside the worked-examples table (aria-label="Scoring worked examples").
      const table = document.querySelector('[aria-label="Scoring worked examples"]');
      expect(table).toBeTruthy();
      const cells = table!.querySelectorAll('td');
      const totalsFound = Array.from(cells).some(
        (td) => td.textContent?.trim() === String(total),
      );
      expect(totalsFound, `Expected total ${total} in worked examples`).toBe(true);
    }
  });

  it('shows 6 special predictions with a total of 80', () => {
    renderAboutPage();
    // SpecialsTable renders 6 rows + a total row reading "80"
    const allCells = Array.from(document.querySelectorAll('td'));
    const hasEighty = allCells.some((td) => td.textContent?.trim() === '80');
    expect(hasEighty).toBe(true);
  });

  it('shows grand total 1,415', () => {
    renderAboutPage();
    // Grand total pill renders "1,415"
    expect(screen.getByText('1,415')).toBeTruthy();
  });

  it('includes the end-of-rules handoff back to Predict', () => {
    renderAboutPage();
    expect(screen.getByText(/use predict → specials/i)).toBeTruthy();
  });

  it('has no axe violations', async () => {
    const { container } = renderAboutPage();
    const results = await axe(container, AXE_CONFIG);
    expect(results).toHaveNoViolations();
  });
});
