import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { IntroTour, isTourSeen } from '@/components/IntroTour';

beforeEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe('IntroTour', () => {
  it('renders the first slide title', () => {
    render(
      <MemoryRouter>
        <IntroTour onClose={vi.fn()} />
      </MemoryRouter>,
    );
    expect(screen.getByText(/how scoring stacks/i)).toBeTruthy();
  });

  it('advances to next slide on Next click', () => {
    render(
      <MemoryRouter>
        <IntroTour onClose={vi.fn()} />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole('button', { name: /next/i }));
    expect(screen.getByText(/predict before kickoff/i)).toBeTruthy();
  });

  it('sets localStorage flag and calls onClose when Get started clicked', () => {
    const onClose = vi.fn();
    render(
      <MemoryRouter>
        <IntroTour onClose={onClose} />
      </MemoryRouter>,
    );
    // Advance to last slide
    const next = screen.getByRole('button', { name: /next/i });
    fireEvent.click(next);
    fireEvent.click(screen.getByRole('button', { name: /next/i }));
    fireEvent.click(screen.getByRole('button', { name: /next/i }));
    // Now on last slide
    fireEvent.click(screen.getByRole('button', { name: /get started/i }));
    expect(isTourSeen()).toBe(true);
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('sets localStorage flag and calls onClose when Skip clicked', () => {
    const onClose = vi.fn();
    render(
      <MemoryRouter>
        <IntroTour onClose={onClose} />
      </MemoryRouter>,
    );
    // 'Skip' (footer button) vs 'Skip tour' (X icon button) — use exact string
    fireEvent.click(screen.getByRole('button', { name: 'Skip' }));
    expect(isTourSeen()).toBe(true);
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('shows skip button only on non-final slides', () => {
    render(
      <MemoryRouter>
        <IntroTour onClose={vi.fn()} />
      </MemoryRouter>,
    );
    // On slide 1, Skip button should be visible (footer 'Skip', distinct from 'Skip tour' X button)
    expect(screen.queryByRole('button', { name: 'Skip' })).toBeTruthy();
    // Advance to last slide (slide 4)
    fireEvent.click(screen.getByRole('button', { name: /next/i }));
    fireEvent.click(screen.getByRole('button', { name: /next/i }));
    fireEvent.click(screen.getByRole('button', { name: /next/i }));
    expect(screen.queryByRole('button', { name: 'Skip' })).toBeNull();
    expect(screen.getByRole('button', { name: /get started/i })).toBeTruthy();
  });

  it('shows a Back button after the first slide and returns to the previous slide', () => {
    render(
      <MemoryRouter>
        <IntroTour onClose={vi.fn()} />
      </MemoryRouter>,
    );

    expect(screen.queryByRole('button', { name: /back/i })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /next/i }));
    fireEvent.click(screen.getByRole('button', { name: /back/i }));

    expect(screen.getByText(/how scoring stacks/i)).toBeTruthy();
  });

  it('includes the goals-only scoring example and points people to /about', () => {
    render(
      <MemoryRouter>
        <IntroTour onClose={vi.fn()} />
      </MemoryRouter>,
    );

    expect(screen.getByText(/you still bank/i)).toBeTruthy();
    expect(screen.getByText(/full worked examples live on/i)).toBeTruthy();
    expect(screen.getByText('/about')).toBeTruthy();
  });
});
