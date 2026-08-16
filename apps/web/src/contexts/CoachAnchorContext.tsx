import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';

interface AnchorEntry {
  key: symbol;
  analysisId: string;
}

/**
 * Which read the screen is currently showing, for the app-wide coach (Batch 207).
 *
 * Before this, `/brief` carried two chat affordances — an inline "Ask about this
 * read" box beside a launcher headed "Ask about this morning's brief" — and
 * membership between them ran one way only: a launcher question asked while
 * standing on the brief was stored with `analysis_id = NULL` and could never
 * appear in that brief's own chat, though inline questions appeared in both. Two
 * boxes, two names, and a question that vanished from the read it was obviously
 * about depending on which one Mark typed into (UX192-07).
 *
 * Decision (Craig, 2026-08-16): one coach everywhere. The inline views are gone
 * and the launcher is the only way to talk to the coach.
 *
 * That would have thrown away the useful half of anchoring along with the
 * confusing half, so it is kept here instead: a screen showing a specific read
 * registers it, and the launcher anchors that screen's questions to it. The
 * coach still knows which read Mark is looking at; there is simply only ever one
 * box and one thread. The anchor *seeds* the question, exactly as `originKind`
 * already does — it never fences what Mark may ask.
 */

interface CoachAnchorContextValue {
  analysisId: string | null;
  register: (key: symbol, analysisId: string) => void;
  unregister: (key: symbol) => void;
}

// A default value keeps `useRegisterCoachAnchor` a no-op outside the provider,
// so page-level unit tests can render a screen in isolation (the same idiom
// ThemeContext uses).
const CoachAnchorContext = createContext<CoachAnchorContextValue>({
  analysisId: null,
  register: () => {
    /* no-op outside provider */
  },
  unregister: () => {
    /* no-op outside provider */
  },
});

/**
 * Registrations are a *stack*, not a single value.
 *
 * A single value looked sufficient and is not: a workout sheet opens over a page
 * that has already registered its own read, and when the sheet closes its
 * cleanup would clear the anchor while the page's effect — whose dependencies
 * never changed — does not re-run to restore it. The screen would then be
 * showing a read with no anchor attached. Keeping every live registration and
 * reading the top entry means closing the sheet simply uncovers the page again.
 */
export function CoachAnchorProvider({ children }: { children: ReactNode }) {
  const [entries, setEntries] = useState<AnchorEntry[]>([]);

  const register = useCallback((key: symbol, analysisId: string) => {
    setEntries((current) => [...current.filter((entry) => entry.key !== key), { key, analysisId }]);
  }, []);

  const unregister = useCallback((key: symbol) => {
    setEntries((current) => current.filter((entry) => entry.key !== key));
  }, []);

  const value = useMemo(
    () => ({
      analysisId: entries.length > 0 ? entries[entries.length - 1].analysisId : null,
      register,
      unregister,
    }),
    [entries, register, unregister],
  );

  return <CoachAnchorContext.Provider value={value}>{children}</CoachAnchorContext.Provider>;
}

/** The read on screen, or `null` when the current view is not showing one. */
export function useCoachAnchor(): string | null {
  return useContext(CoachAnchorContext).analysisId;
}

/**
 * Register the read this screen is showing, for as long as it is on screen.
 *
 * Pass `null` when the read exists but is not visible (a collapsed analysis), so
 * the anchor tracks what Mark can actually see.
 */
export function useRegisterCoachAnchor(analysisId: string | null | undefined): void {
  const { register, unregister } = useContext(CoachAnchorContext);
  const keyRef = useRef<symbol | null>(null);
  if (keyRef.current === null) keyRef.current = Symbol('coach-anchor');
  const key = keyRef.current;

  useEffect(() => {
    if (!analysisId) {
      unregister(key);
      return;
    }
    register(key, analysisId);
    return () => unregister(key);
  }, [analysisId, key, register, unregister]);
}
