/**
 * Lightweight global dirty-state signal for the predictions editor.
 *
 * The UpdateBanner listens to this to defer auto-reloads while the user has
 * unsaved prediction edits. The PredictionsPage (via usePredictionEditor) sets
 * it via setPredictionsDirty(). The signal is intentionally kept outside React
 * state so UpdateBanner can read it synchronously without an extra context dep.
 */

type Listener = (dirty: boolean) => void;

let _dirty = false;
const _listeners = new Set<Listener>();

/** Returns true when there are unsaved prediction edits. */
export function getPredictionsDirty(): boolean {
  return _dirty;
}

/** Called by the predictions editor when dirty count changes. */
export function setPredictionsDirty(dirty: boolean): void {
  if (_dirty === dirty) return;
  _dirty = dirty;
  for (const fn of _listeners) fn(dirty);
}

/** Subscribe to dirty-state changes. Returns an unsubscribe function. */
export function subscribePredictionsDirty(fn: Listener): () => void {
  _listeners.add(fn);
  return () => _listeners.delete(fn);
}
