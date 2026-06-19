import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { PointsBreakdownPopover } from '@/components/PointsBreakdownPopover';

const FULL_BREAKDOWN = { goals: 2, result: 3, exact: 5, total: 10, no_prediction: false };

describe('PointsBreakdownPopover', () => {
  it('renders the trigger child', () => {
    render(
      <PointsBreakdownPopover breakdown={FULL_BREAKDOWN}>
        <span data-testid="trigger">10 pts</span>
      </PointsBreakdownPopover>,
    );
    expect(screen.getByTestId('trigger')).toBeInTheDocument();
  });

  it('shows no breakdown detail before tap', () => {
    render(
      <PointsBreakdownPopover breakdown={FULL_BREAKDOWN}>
        <span>10 pts</span>
      </PointsBreakdownPopover>,
    );
    expect(screen.queryByTestId('breakdown-detail')).not.toBeInTheDocument();
  });

  it('reveals Goals · Result · Exact breakdown after tap', () => {
    render(
      <PointsBreakdownPopover breakdown={FULL_BREAKDOWN}>
        <span>10 pts</span>
      </PointsBreakdownPopover>,
    );
    fireEvent.click(screen.getByTestId('breakdown-trigger'));
    const detail = screen.getByTestId('breakdown-detail');
    expect(detail.textContent).toContain('Goals 2');
    expect(detail.textContent).toContain('Result 3');
    expect(detail.textContent).toContain('Exact 5');
  });

  it('hides detail on second tap (toggle)', () => {
    render(
      <PointsBreakdownPopover breakdown={FULL_BREAKDOWN}>
        <span>10 pts</span>
      </PointsBreakdownPopover>,
    );
    const trigger = screen.getByTestId('breakdown-trigger');
    fireEvent.click(trigger);
    fireEvent.click(trigger);
    expect(screen.queryByTestId('breakdown-detail')).not.toBeInTheDocument();
  });

  it('renders children as-is when breakdown is null', () => {
    render(
      <PointsBreakdownPopover breakdown={null}>
        <span data-testid="plain">5 pts</span>
      </PointsBreakdownPopover>,
    );
    expect(screen.getByTestId('plain')).toBeInTheDocument();
    expect(screen.queryByTestId('breakdown-trigger')).not.toBeInTheDocument();
  });

  it('renders children as-is when no_prediction is true', () => {
    const noEntry = { goals: 0, result: 0, exact: 0, total: 0, no_prediction: true };
    render(
      <PointsBreakdownPopover breakdown={noEntry}>
        <span data-testid="plain">0 pts</span>
      </PointsBreakdownPopover>,
    );
    expect(screen.getByTestId('plain')).toBeInTheDocument();
    expect(screen.queryByTestId('breakdown-trigger')).not.toBeInTheDocument();
  });

  it('omits zero-value components from the breakdown text', () => {
    const noExact = { goals: 2, result: 3, exact: 0, total: 5, no_prediction: false };
    render(
      <PointsBreakdownPopover breakdown={noExact}>
        <span>5 pts</span>
      </PointsBreakdownPopover>,
    );
    fireEvent.click(screen.getByTestId('breakdown-trigger'));
    const detail = screen.getByTestId('breakdown-detail');
    expect(detail.textContent).toContain('Goals 2');
    expect(detail.textContent).toContain('Result 3');
    expect(detail.textContent).not.toContain('Exact');
  });
});
