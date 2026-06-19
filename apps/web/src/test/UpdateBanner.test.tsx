/**
 * U26.1 — update-scheduling tests for UpdateBanner.
 *
 * Acceptance:
 *  - Defers reload while predictions are dirty (unsaved edits).
 *  - Fires reload on refocus (visibilitychange → visible) when dirty flag cleared.
 *  - No permanent-dismiss path.
 *  - Renders above the iOS overlay (z-[80]).
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, act, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { axe } from 'jest-axe';
import { setPredictionsDirty } from '@/lib/dirtyState';

// Disable color-contrast: jsdom cannot evaluate CSS custom properties.
const AXE_CONFIG = { rules: { 'color-contrast': { enabled: false } } };

// ── Mock virtual:pwa-register ─────────────────────────────────────────────────

const mockSW = vi.fn().mockResolvedValue(undefined);
let _onNeedRefresh: (() => void) | undefined;

vi.mock('virtual:pwa-register', () => ({
  registerSW: vi.fn((callbacks: { onNeedRefresh?: () => void; onOfflineReady?: () => void }) => {
    _onNeedRefresh = callbacks.onNeedRefresh;
    return mockSW;
  }),
}));

// Import component after mock is registered.
import { UpdateBanner } from '@/components/UpdateBanner';

// ── Helpers ───────────────────────────────────────────────────────────────────

function triggerNeedRefresh() {
  act(() => {
    _onNeedRefresh?.();
  });
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('UpdateBanner', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockSW.mockResolvedValue(undefined);
    _onNeedRefresh = undefined;
    // Reset dirty state.
    setPredictionsDirty(false);
    // Tab starts visible.
    Object.defineProperty(document, 'visibilityState', {
      value: 'visible',
      writable: true,
      configurable: true,
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
    setPredictionsDirty(false);
  });

  it('does not render before a new version is available', () => {
    render(<UpdateBanner />);
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('shows the banner when onNeedRefresh fires', () => {
    render(<UpdateBanner />);
    triggerNeedRefresh();
    expect(screen.getByRole('status')).toBeTruthy();
  });

  it('has no permanent dismiss button — only an "Update now" button', () => {
    render(<UpdateBanner />);
    triggerNeedRefresh();
    // Must NOT have a dismiss/close button
    expect(screen.queryByLabelText(/dismiss/i)).toBeNull();
    // Must have the manual trigger
    expect(screen.getByRole('button', { name: /update now/i })).toBeTruthy();
  });

  it('shows deferred copy while predictions are dirty', () => {
    setPredictionsDirty(true);
    render(<UpdateBanner />);
    triggerNeedRefresh();
    expect(screen.getByText(/updating after save/i)).toBeTruthy();
  });

  it('does not auto-reload while predictions are dirty', async () => {
    setPredictionsDirty(true);
    render(<UpdateBanner />);
    triggerNeedRefresh();

    // Advance past the 5-second countdown — should NOT have called reload.
    await act(async () => {
      vi.advanceTimersByTime(10_000);
    });

    expect(mockSW).not.toHaveBeenCalledWith(true);
  });

  it('starts countdown when dirty flag is cleared after needsRefresh', async () => {
    setPredictionsDirty(true);
    render(<UpdateBanner />);
    triggerNeedRefresh();

    // Banner shows deferred copy.
    expect(screen.getByText(/updating after save/i)).toBeTruthy();

    // User saves — clears dirty flag.
    act(() => {
      setPredictionsDirty(false);
    });

    // Countdown should appear.
    await waitFor(() =>
      expect(screen.getByText(/updating in/i)).toBeTruthy(),
    );
  });

  it('auto-reloads after the countdown elapses when not dirty', async () => {
    render(<UpdateBanner />);
    triggerNeedRefresh();

    // Tab visible, not dirty → countdown starts and fires after 5 s.
    await act(async () => {
      vi.advanceTimersByTime(6_000);
    });

    expect(mockSW).toHaveBeenCalledWith(true);
  });

  it('defers reload when tab is hidden, fires when tab becomes visible', async () => {
    // Hide tab before needsRefresh fires.
    Object.defineProperty(document, 'visibilityState', {
      value: 'hidden',
      writable: true,
      configurable: true,
    });

    render(<UpdateBanner />);
    triggerNeedRefresh();

    // Advance well past countdown — should NOT reload while hidden.
    await act(async () => {
      vi.advanceTimersByTime(10_000);
    });
    expect(mockSW).not.toHaveBeenCalledWith(true);

    // Tab becomes visible.
    Object.defineProperty(document, 'visibilityState', {
      value: 'visible',
      writable: true,
      configurable: true,
    });
    act(() => {
      document.dispatchEvent(new Event('visibilitychange'));
    });

    // Countdown runs and fires.
    await act(async () => {
      vi.advanceTimersByTime(6_000);
    });
    expect(mockSW).toHaveBeenCalledWith(true);
  });

  it('"Update now" button calls reload immediately', async () => {
    render(<UpdateBanner />);
    triggerNeedRefresh();

    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime.bind(vi) });
    await user.click(screen.getByRole('button', { name: /update now/i }));

    expect(mockSW).toHaveBeenCalledWith(true);
  });

  it('refresh icon carries animate-spin class', () => {
    render(<UpdateBanner />);
    triggerNeedRefresh();
    // aria-hidden SVG — query by tag inside the banner
    const banner = screen.getByRole('status');
    const svg = banner.querySelector('svg');
    expect(svg?.classList.contains('animate-spin')).toBe(true);
  });

  it('renders with z-[80] class (above iOS overlay z-[70])', () => {
    render(<UpdateBanner />);
    triggerNeedRefresh();
    const banner = screen.getByRole('status');
    expect(banner.className).toMatch(/z-\[80\]/);
  });

  it('has no axe violations when visible', async () => {
    const { container } = render(<UpdateBanner />);
    triggerNeedRefresh();
    const results = await axe(container, AXE_CONFIG);
    expect(results).toHaveNoViolations();
  });
});
