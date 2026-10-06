import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { NEXT_PLAN_BUTTON, NEXT_PLAN_TITLE } from '@/lib/nextPlan';
import { NextPlanCard } from './NextPlanCard';

const PLAN = { planName: 'Plan No. 3', startDate: '2026-10-19', endDate: '2027-01-17' };

function renderCard(nextPlan: typeof PLAN | null | undefined, today: string) {
  return render(
    <MemoryRouter>
      <NextPlanCard nextPlan={nextPlan} today={today} />
    </MemoryRouter>,
  );
}

// Batch 323: his next plan is proposed in the app, and he decides.
describe('next plan card', () => {
  it('says the plan is ready, when it starts, and leads to the plan builder', () => {
    renderCard(PLAN, '2026-10-12');
    expect(screen.getByText(NEXT_PLAN_TITLE)).toBeTruthy();
    expect(
      screen.getByText(
        'Plan No. 3 starts Monday 19 October. Review it, change any day you like, then accept it.',
      ),
    ).toBeTruthy();
    const link = screen.getByRole('link', { name: NEXT_PLAN_BUTTON });
    expect(link.getAttribute('href')).toBe('/builder');
  });

  it('once its start has come, says it is ready to start', () => {
    renderCard(PLAN, '2026-10-19');
    expect(
      screen.getByText(
        'Plan No. 3 is ready to start. Review it, change any day you like, then accept it.',
      ),
    ).toBeTruthy();
  });

  it('shows nothing when no plan is waiting, or from an older server', () => {
    expect(renderCard(null, '2026-10-12').container.textContent).toBe('');
    expect(renderCard(undefined, '2026-10-12').container.textContent).toBe('');
  });
});
