import { useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion, useReducedMotionConfig } from 'framer-motion';
import { Button, type ButtonProps } from './button';
import { cn } from '@/lib/utils';

export type SaveButtonState = 'idle' | 'saving' | 'saved';

export interface SaveButtonProps extends Omit<ButtonProps, 'children'> {
  state: SaveButtonState;
  idleLabel: string;
  savingLabel?: string;
  savedLabel?: string;
  /**
   * How long to hold the `saved` state visually. Default 1200 ms — matches
   * the U5 spec. The button does NOT change `state` itself; callers should
   * flip back to `idle` after this duration. The internal timing here is
   * only for the check-icon draw-in animation.
   */
  savedHoldMs?: number;
}

const CHECK_DRAW_MS = 280;

/**
 * Shared save CTA.
 *
 * Three states:
 *   - `idle`   → shows `idleLabel`
 *   - `saving` → shows `savingLabel` (defaults to "Saving…"), disabled
 *   - `saved`  → shows a checkmark that strokes itself in, then `savedLabel`
 *
 * The caller owns the state lifecycle (typically: set `saving`, await the
 * mutation, set `saved`, then setTimeout back to `idle`). The button itself
 * just animates the visual transitions.
 *
 * Honours `prefers-reduced-motion`: the check icon snaps in fully drawn
 * with no path animation and the label crossfade is replaced by an instant
 * swap.
 */
export function SaveButton({
  state,
  idleLabel,
  savingLabel = 'Saving…',
  savedLabel = 'Saved',
  savedHoldMs: _savedHoldMs = 1200,
  className,
  disabled,
  ...rest
}: SaveButtonProps) {
  const prefersReducedMotion = useReducedMotionConfig();

  // The check needs a fresh key each time we enter "saved" so the path
  // animation re-runs even when state transitions saved → idle → saved.
  const [checkKey, setCheckKey] = useState(0);
  const lastStateRef = useRef<SaveButtonState>(state);
  useEffect(() => {
    if (lastStateRef.current !== 'saved' && state === 'saved') {
      setCheckKey((k) => k + 1);
    }
    lastStateRef.current = state;
  }, [state]);

  const isSaving = state === 'saving';
  const isSaved = state === 'saved';

  return (
    <Button
      type={rest.type ?? 'submit'}
      aria-live="polite"
      disabled={disabled || isSaving || isSaved}
      className={cn('relative overflow-hidden', className)}
      {...rest}
    >
      {/* Invisible spacer ensures the button width never flickers between
          label widths. Picks the widest of the three labels. */}
      <span className="invisible whitespace-nowrap" aria-hidden>
        {[idleLabel, savingLabel, savedLabel].reduce(
          (a, b) => (b.length > a.length ? b : a),
          idleLabel,
        )}
      </span>

      <span className="absolute inset-0 flex items-center justify-center gap-1.5">
        {prefersReducedMotion ? (
          <SaveButtonLabel state={state} idleLabel={idleLabel} savingLabel={savingLabel} savedLabel={savedLabel} reduced />
        ) : (
          <AnimatePresence mode="wait" initial={false}>
            <motion.span
              key={state}
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -4 }}
              transition={{ duration: 0.18 }}
              className="inline-flex items-center gap-1.5"
            >
              {isSaved && (
                <CheckMark key={checkKey} reducedMotion={prefersReducedMotion ?? false} />
              )}
              <span>
                {isSaving ? savingLabel : isSaved ? savedLabel : idleLabel}
              </span>
            </motion.span>
          </AnimatePresence>
        )}
      </span>
    </Button>
  );
}

function SaveButtonLabel({
  state,
  idleLabel,
  savingLabel,
  savedLabel,
  reduced,
}: {
  state: SaveButtonState;
  idleLabel: string;
  savingLabel: string;
  savedLabel: string;
  reduced: boolean;
}) {
  if (state === 'saved') {
    return (
      <span className="inline-flex items-center gap-1.5">
        <CheckMark reducedMotion={reduced} />
        <span>{savedLabel}</span>
      </span>
    );
  }
  return <span>{state === 'saving' ? savingLabel : idleLabel}</span>;
}

/**
 * 16×16 check icon. Draws in via `pathLength: 0 → 1` over 280 ms unless
 * reduced motion is requested, in which case it renders fully drawn.
 */
function CheckMark({ reducedMotion }: { reducedMotion: boolean }) {
  return (
    <svg
      width={14}
      height={14}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={2.4}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      className="shrink-0"
    >
      <motion.path
        d="M3 8.5 L6.5 12 L13 4.5"
        initial={reducedMotion ? { pathLength: 1 } : { pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={reducedMotion ? { duration: 0 } : { duration: CHECK_DRAW_MS / 1000, ease: 'easeOut' }}
      />
    </svg>
  );
}
