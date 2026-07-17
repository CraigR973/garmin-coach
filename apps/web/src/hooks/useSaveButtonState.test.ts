import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useSaveButtonState } from './useSaveButtonState';

// Batch 137 — maps a react-query mutation's (isPending, isSuccess) flags to the
// SaveButton lifecycle: idle → saving → saved (held) → idle, and idle on error.
describe('useSaveButtonState', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('runs idle → saving → saved → idle on a successful save', () => {
    const { result, rerender } = renderHook(
      ({ pending, success }) => useSaveButtonState(pending, success, 1200),
      { initialProps: { pending: false, success: false } },
    );
    expect(result.current).toBe('idle');

    rerender({ pending: true, success: false });
    expect(result.current).toBe('saving');

    rerender({ pending: false, success: true });
    expect(result.current).toBe('saved');

    act(() => vi.advanceTimersByTime(1200));
    expect(result.current).toBe('idle');
  });

  it('returns to idle immediately after a failed save', () => {
    const { result, rerender } = renderHook(
      ({ pending, success }) => useSaveButtonState(pending, success),
      { initialProps: { pending: true, success: false } },
    );
    expect(result.current).toBe('saving');

    rerender({ pending: false, success: false });
    expect(result.current).toBe('idle');
  });
});
