import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { EmptyState, ErrorState, OfflineNotice } from './EmptyState';

describe('ErrorState', () => {
  it('says what happened and offers a single recovery action', async () => {
    const onRetry = vi.fn();
    const user = userEvent.setup();
    render(<ErrorState title="Today's brief couldn't load" description="Network hiccup." onRetry={onRetry} />);

    expect(screen.getByText("Today's brief couldn't load")).toBeTruthy();
    expect(screen.getByText('Network hiccup.')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it('supports a custom retry label', () => {
    render(<ErrorState title="Nope" onRetry={vi.fn()} retryLabel="Reload" />);
    expect(screen.getByRole('button', { name: 'Reload' })).toBeTruthy();
  });
});

describe('EmptyState', () => {
  it('renders without an action when there is nothing to recover', () => {
    render(<EmptyState title="No plan window yet" description="Your schedule will show up here." />);
    expect(screen.getByText('No plan window yet')).toBeTruthy();
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('renders an optional recovery action', async () => {
    const onClick = vi.fn();
    const user = userEvent.setup();
    render(<EmptyState title="Nothing here" action={{ label: 'Go to Home', onClick }} />);
    await user.click(screen.getByRole('button', { name: 'Go to Home' }));
    expect(onClick).toHaveBeenCalledOnce();
  });
});

describe('OfflineNotice', () => {
  it('renders a status region with the given copy', () => {
    render(<OfflineNotice description="You're offline — showing your last saved brief." />);
    expect(screen.getByRole('status')).toBeTruthy();
    expect(screen.getByText(/showing your last saved brief/)).toBeTruthy();
  });
});
