import { focusManager } from '@tanstack/react-query';

/**
 * Make TanStack Query's focus refetch fire reliably on iOS PWA *warm resume*.
 *
 * The problem (U59 → U61): closed matches kept showing as open and live state
 * went stale until the app was fully closed and reopened. `refetchOnWindowFocus`
 * (enabled in App.tsx) is the intended cure, but TanStack's default focus signal
 * only listens to `visibilitychange`. On an iOS home-screen PWA, returning from
 * the background can restore a frozen page snapshot from the back/forward cache
 * and emit a `pageshow` event *without* a preceding `visibilitychange` — so the
 * focus refetch never fires and the user is stuck looking at stale data. The
 * `refetchInterval` polls don't help either: iOS pauses JS timers while the app
 * is suspended, so the only recovery point is the resume itself.
 *
 * We widen the focus signal to cover `pageshow` as well as `visibilitychange`,
 * so a warm resume always triggers a refetch of stale queries. This reuses the
 * existing refetch path (proven dirty-state-safe by usePredictionEditor, which
 * preserves in-progress edits across a focus refetch), so no query needs to know
 * about it.
 *
 * `pageshow` also fires on a normal cold load (`persisted === false`); that path
 * is a harmless no-op because queries are already fresh at mount.
 */
export function resumeFocusSetup(handleFocus: (focused?: boolean) => void): (() => void) | undefined {
  if (typeof window === 'undefined' || !window.addEventListener) return undefined;

  const onResume = () => {
    // Guard against firing while still hidden (a `pageshow` can race ahead of
    // the page actually becoming visible); refetching a hidden tab wastes a
    // request and never reaches the user.
    if (document.visibilityState !== 'hidden') {
      handleFocus();
    }
  };

  window.addEventListener('visibilitychange', onResume, false);
  window.addEventListener('pageshow', onResume, false);

  return () => {
    window.removeEventListener('visibilitychange', onResume);
    window.removeEventListener('pageshow', onResume);
  };
}

/**
 * Install {@link resumeFocusSetup} as TanStack Query's global focus listener.
 * Call once at app startup. Replacing the default listener is safe: it runs
 * before the QueryClient subscribes, so the client keeps using this listener.
 */
export function installResumeRefetch(): void {
  focusManager.setEventListener(resumeFocusSetup);
}
