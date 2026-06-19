import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { focusManager } from '@tanstack/react-query';
import { resumeFocusSetup, installResumeRefetch } from '@/lib/resumeRefetch';

function setVisibility(state: 'visible' | 'hidden') {
  Object.defineProperty(document, 'visibilityState', {
    configurable: true,
    get: () => state,
  });
}

describe('resumeFocusSetup', () => {
  beforeEach(() => {
    setVisibility('visible');
  });

  it('fires the focus handler on pageshow (bfcache/snapshot restore) when visible', () => {
    const handleFocus = vi.fn();
    const cleanup = resumeFocusSetup(handleFocus);
    window.dispatchEvent(new Event('pageshow'));
    expect(handleFocus).toHaveBeenCalledTimes(1);
    cleanup?.();
  });

  it('fires the focus handler on visibilitychange when visible', () => {
    const handleFocus = vi.fn();
    const cleanup = resumeFocusSetup(handleFocus);
    window.dispatchEvent(new Event('visibilitychange'));
    expect(handleFocus).toHaveBeenCalledTimes(1);
    cleanup?.();
  });

  it('does not fire while the document is hidden (avoids refetching a backgrounded tab)', () => {
    setVisibility('hidden');
    const handleFocus = vi.fn();
    const cleanup = resumeFocusSetup(handleFocus);
    window.dispatchEvent(new Event('pageshow'));
    window.dispatchEvent(new Event('visibilitychange'));
    expect(handleFocus).not.toHaveBeenCalled();
    cleanup?.();
  });

  it('removes its listeners on cleanup', () => {
    const handleFocus = vi.fn();
    const cleanup = resumeFocusSetup(handleFocus);
    cleanup?.();
    window.dispatchEvent(new Event('pageshow'));
    expect(handleFocus).not.toHaveBeenCalled();
  });
});

describe('installResumeRefetch', () => {
  beforeEach(() => {
    setVisibility('visible');
  });

  afterEach(() => {
    // Detach our window listeners so they don't leak into other test files'
    // focusManager (it is a process-wide singleton).
    focusManager.setEventListener(() => undefined);
  });

  it('notifies focusManager subscribers on warm resume so refetchOnWindowFocus fires', () => {
    installResumeRefetch();
    const listener = vi.fn();
    const unsubscribe = focusManager.subscribe(listener);

    window.dispatchEvent(new Event('pageshow'));

    expect(listener).toHaveBeenCalledWith(true);
    unsubscribe();
  });
});
