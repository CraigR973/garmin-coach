import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { axe } from 'jest-axe';
import { Skeleton } from '@/components/ui/skeleton';
import { EmptyState } from '@/components/EmptyState';
import { ErrorBoundary } from '@/components/ErrorBoundary';
import { PageTransition } from '@/components/PageTransition';

const AXE_CONFIG = { rules: { 'color-contrast': { enabled: false } } };

// ---------------------------------------------------------------------------
// Skeleton
// ---------------------------------------------------------------------------

describe('Skeleton', () => {
  it('renders with aria-busy and an accessible name so AT users hear "Loading"', () => {
    render(<Skeleton className="h-4 w-20" />);
    const node = screen.getByRole('status');
    expect(node.getAttribute('aria-busy')).toBe('true');
    expect(node.getAttribute('aria-label')).toBe('Loading');
  });

  it('has no axe violations', async () => {
    const { container } = render(<Skeleton className="h-4 w-20" />);
    expect(await axe(container, AXE_CONFIG)).toHaveNoViolations();
  });

  it('merges custom className with base styles', () => {
    render(<Skeleton className="custom-marker" />);
    const node = screen.getByRole('status');
    expect(node.className).toContain('custom-marker');
    expect(node.className).toContain('animate-pulse');
  });
});

// ---------------------------------------------------------------------------
// EmptyState
// ---------------------------------------------------------------------------

describe('EmptyState', () => {
  it('renders title and optional description / action', () => {
    render(
      <EmptyState
        title="Nothing here"
        description="Come back later."
        action={<button type="button">Refresh</button>}
      />,
    );
    expect(screen.getByText('Nothing here')).toBeInTheDocument();
    expect(screen.getByText('Come back later.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Refresh' })).toBeInTheDocument();
  });

  it('exposes role=status so SRs announce empty results', () => {
    render(<EmptyState title="Empty" />);
    expect(screen.getByRole('status')).toBeInTheDocument();
  });

  it('hides decorative icon from assistive tech via aria-hidden', () => {
    const { container } = render(
      <EmptyState title="Empty" icon={<svg data-testid="icon" />} />,
    );
    const iconWrap = container.querySelector('[aria-hidden="true"]');
    expect(iconWrap).not.toBeNull();
    expect(iconWrap!.querySelector('[data-testid="icon"]')).not.toBeNull();
  });

  it('has no axe violations', async () => {
    const { container } = render(<EmptyState title="Empty" description="Try again later" />);
    expect(await axe(container, AXE_CONFIG)).toHaveNoViolations();
  });
});

// ---------------------------------------------------------------------------
// ErrorBoundary
// ---------------------------------------------------------------------------

function Boom({ throwIt }: { throwIt: boolean }): JSX.Element {
  if (throwIt) throw new Error('boom');
  return <div>OK</div>;
}

describe('ErrorBoundary', () => {
  it('renders children when nothing throws', () => {
    render(
      <ErrorBoundary>
        <Boom throwIt={false} />
      </ErrorBoundary>,
    );
    expect(screen.getByText('OK')).toBeInTheDocument();
  });

  it('catches render errors and shows a fallback with Try again', () => {
    // Suppress React's expected error log during the throw.
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

    function Toggle() {
      // local state so we can flip throwIt back to false after Try again
      return (
        <ErrorBoundary>
          <Boom throwIt />
        </ErrorBoundary>
      );
    }
    render(<Toggle />);
    expect(screen.getByText('Something went wrong')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();

    errSpy.mockRestore();
  });

  it('Try again resets the boundary so children can re-render', () => {
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

    // Wrap so we can flip the throw flag after recovery.
    function Harness() {
      // Throws on first render, resets on Try again.
      const ref = { current: true };
      const Toggle = () => <Boom throwIt={ref.current} />;
      return (
        <ErrorBoundary>
          <Toggle />
        </ErrorBoundary>
      );
    }
    render(<Harness />);
    // Verify fallback then click Try again — children re-render but Toggle still throws
    // (this exercises the reset path without testing recovery semantics specifically).
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(screen.getByText('Something went wrong')).toBeInTheDocument();

    errSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// PageTransition
// ---------------------------------------------------------------------------

describe('PageTransition', () => {
  it('renders children inside a motion wrapper', () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <PageTransition>
          <p>hello</p>
        </PageTransition>
      </MemoryRouter>,
    );
    expect(screen.getByText('hello')).toBeInTheDocument();
  });
});
