import { useEffect, useRef, useState } from 'react';
import type { SaveButtonState } from '@/components/ui/save-button';

/**
 * Adapts a react-query mutation's flags to the `SaveButton` lifecycle
 * (idle → saving → saved → idle) so save CTAs read identically app-wide
 * (Batch 137). Pass `mutation.isPending` and `mutation.isSuccess`.
 *
 *  - `saving` while the mutation is in flight;
 *  - `saved` for `holdMs` after a save that succeeded (drives the check draw-in),
 *    then back to `idle`;
 *  - `idle` at rest, and immediately after a failed save.
 */
export function useSaveButtonState(
  isPending: boolean,
  isSuccess: boolean,
  holdMs = 1200,
): SaveButtonState {
  const [state, setState] = useState<SaveButtonState>('idle');
  const wasPending = useRef(false);

  useEffect(() => {
    if (isPending) {
      wasPending.current = true;
      setState('saving');
      return;
    }
    if (wasPending.current) {
      wasPending.current = false;
      if (isSuccess) {
        setState('saved');
        const timer = setTimeout(() => setState('idle'), holdMs);
        return () => clearTimeout(timer);
      }
      setState('idle');
    }
  }, [isPending, isSuccess, holdMs]);

  return state;
}
