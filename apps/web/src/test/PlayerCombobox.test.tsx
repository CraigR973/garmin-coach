/**
 * U14.6 — PlayerCombobox unit tests
 *
 * @radix-ui/react-popover uses portal + animation APIs unavailable in jsdom,
 * so we mock it via an async vi.mock factory (Vitest ESM-safe pattern).
 * The cmdk Command/Input/List components work fine in jsdom.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { HTMLAttributes, PropsWithChildren, ReactNode, ReactElement, Ref } from 'react';
import { PlayerCombobox } from '@/components/PlayerCombobox';
import * as api from '@/lib/api';

// ---------------------------------------------------------------------------
// Mock @radix-ui/react-popover — renders children inline without portals
// ---------------------------------------------------------------------------
vi.mock('@radix-ui/react-popover', async () => {
  const React = await import('react');

  interface CtxValue {
    open: boolean;
    setOpen: (v: boolean) => void;
  }
  const Ctx = React.createContext<CtxValue>({ open: false, setOpen: () => {} });

  function Root({
    children,
    open: ctrl,
    onOpenChange,
  }: PropsWithChildren<{ open?: boolean; onOpenChange?: (v: boolean) => void }>) {
    const [local, setLocal] = React.useState(false);
    const open = ctrl ?? local;
    const setOpen = (v: boolean) => {
      setLocal(v);
      onOpenChange?.(v);
    };
    return <Ctx.Provider value={{ open, setOpen }}>{children}</Ctx.Provider>;
  }

  interface TriggerProps extends HTMLAttributes<HTMLElement> {
    asChild?: boolean;
    children: ReactNode;
  }
  const Trigger = React.forwardRef<HTMLElement, TriggerProps>(
    ({ children, asChild, ...rest }, ref) => {
      const { open, setOpen } = React.useContext(Ctx);
      const toggle = () => setOpen(!open);
      if (asChild && React.isValidElement(children)) {
        const child = children as ReactElement<HTMLAttributes<HTMLElement>>;
        return React.cloneElement(child, {
          onClick: toggle,
          ref: ref as Ref<HTMLElement>,
        } as HTMLAttributes<HTMLElement>);
      }
      return (
        <button {...(rest as HTMLAttributes<HTMLButtonElement>)} ref={ref as Ref<HTMLButtonElement>} onClick={toggle}>
          {children}
        </button>
      );
    },
  );

  function Portal({ children }: PropsWithChildren) {
    return <>{children}</>;
  }

  interface ContentProps extends HTMLAttributes<HTMLDivElement> {
    children: ReactNode;
    sideOffset?: number;
    align?: string;
    side?: string;
    onInteractOutside?: (e: Event) => void;
    onEscapeKeyDown?: (e: KeyboardEvent) => void;
  }
  const Content = React.forwardRef<HTMLDivElement, ContentProps>(
    ({ children, sideOffset: _so, align: _a, side: _s, onInteractOutside: _oio, onEscapeKeyDown: _oek, ...rest }, ref) => {
    const { open } = React.useContext(Ctx);
    if (!open) return null;
    return (
      <div role="dialog" ref={ref} {...rest}>
        {children}
      </div>
    );
  });

  return { Root, Trigger, Portal, Content };
});

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const HAALAND = {
  id: 'uuid-haaland',
  full_name: 'Erling Haaland',
  known_as: 'Haaland',
  position: 'FWD' as const,
  shirt_number: 9,
  team_code: 'NOR',
  team_name: 'Norway',
  flag_emoji: '🇳🇴',
};

const MBAPPE = {
  id: 'uuid-mbappe',
  full_name: 'Kylian Mbappé',
  known_as: 'Mbappé',
  position: 'FWD' as const,
  shirt_number: 10,
  team_code: 'FRA',
  team_name: 'France',
  flag_emoji: '🇫🇷',
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function renderCombobox(overrides: Partial<Parameters<typeof PlayerCombobox>[0]> = {}) {
  const onChange = vi.fn();
  const utils = render(
    <PlayerCombobox
      value=""
      onChange={onChange}
      displayName=""
      aria-label="Golden Boot player"
      {...overrides}
    />,
  );
  return { onChange, ...utils };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('PlayerCombobox', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });
  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it('renders trigger button with placeholder when no value', () => {
    renderCombobox();
    const btn = screen.getByRole('combobox', { name: /golden boot/i });
    expect(btn).toBeInTheDocument();
    expect(btn).toHaveTextContent(/Search for a player/);
  });

  it('shows displayName in trigger when value is set', () => {
    renderCombobox({ value: HAALAND.id, displayName: 'Erling Haaland' });
    expect(screen.getByRole('combobox')).toHaveTextContent('Erling Haaland');
  });

  it('is disabled when disabled prop is true', () => {
    renderCombobox({ disabled: true });
    expect(screen.getByRole('combobox')).toBeDisabled();
  });

  it('opens search input when trigger is clicked', async () => {
    const user = userEvent.setup({ delay: null });
    vi.useRealTimers();
    renderCombobox();

    await user.click(screen.getByRole('combobox'));
    expect(screen.getByPlaceholderText(/Search for a player/)).toBeInTheDocument();
  });

  it('calls apiFetch after debounce and shows results', async () => {
    const fetchSpy = vi.spyOn(api, 'apiFetch').mockResolvedValue([HAALAND, MBAPPE]);
    const user = userEvent.setup({ delay: null });
    vi.useRealTimers();
    renderCombobox();

    await user.click(screen.getByRole('combobox'));
    const input = screen.getByPlaceholderText(/Search for a player/);
    await user.type(input, 'haa');

    // Wait for debounce + fetch
    await waitFor(() => expect(fetchSpy).toHaveBeenCalledOnce(), { timeout: 1000 });

    await waitFor(() => {
      expect(screen.getByText('Haaland')).toBeInTheDocument();
      expect(screen.getByText('Mbappé')).toBeInTheDocument();
    });
  });

  it('shows "No players found" when API returns empty array', async () => {
    vi.spyOn(api, 'apiFetch').mockResolvedValue([]);
    const user = userEvent.setup({ delay: null });
    vi.useRealTimers();
    renderCombobox();

    await user.click(screen.getByRole('combobox'));
    await user.type(screen.getByPlaceholderText(/Search for a player/), 'zzz');

    await waitFor(() => {
      expect(screen.getByText(/no players found/i)).toBeInTheDocument();
    }, { timeout: 1000 });
  });

  it('shows error message when apiFetch rejects', async () => {
    vi.spyOn(api, 'apiFetch').mockRejectedValue(new Error('network error'));
    const user = userEvent.setup({ delay: null });
    vi.useRealTimers();
    renderCombobox();

    await user.click(screen.getByRole('combobox'));
    await user.type(screen.getByPlaceholderText(/Search for a player/), 'err');

    await waitFor(() => {
      expect(screen.getByText(/search failed/i)).toBeInTheDocument();
    }, { timeout: 1000 });
  });

  it('calls onChange with id and full_name when a player is selected', async () => {
    vi.spyOn(api, 'apiFetch').mockResolvedValue([HAALAND]);
    const user = userEvent.setup({ delay: null });
    vi.useRealTimers();
    const { onChange } = renderCombobox();

    await user.click(screen.getByRole('combobox'));
    await user.type(screen.getByPlaceholderText(/Search for a player/), 'haa');

    await waitFor(() => screen.getByText('Haaland'), { timeout: 1000 });

    await user.click(screen.getByText('Haaland'));

    expect(onChange).toHaveBeenCalledWith(HAALAND.id, HAALAND.full_name);
  });

  it('shows flag emoji and team code in results', async () => {
    vi.spyOn(api, 'apiFetch').mockResolvedValue([HAALAND]);
    const user = userEvent.setup({ delay: null });
    vi.useRealTimers();
    renderCombobox();

    await user.click(screen.getByRole('combobox'));
    await user.type(screen.getByPlaceholderText(/Search for a player/), 'haa');

    await waitFor(() => {
      expect(screen.getByText('🇳🇴')).toBeInTheDocument();
      expect(screen.getByText('NOR')).toBeInTheDocument();
      expect(screen.getByText('FWD')).toBeInTheDocument();
    }, { timeout: 1000 });
  });

  it('does not call API when query is empty', async () => {
    const fetchSpy = vi.spyOn(api, 'apiFetch');
    const user = userEvent.setup({ delay: null });
    vi.useRealTimers();
    renderCombobox();

    await user.click(screen.getByRole('combobox'));
    await new Promise((r) => setTimeout(r, 400));

    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
