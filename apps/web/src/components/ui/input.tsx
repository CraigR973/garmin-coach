import * as React from 'react';
import { cn } from '@/lib/utils';

/**
 * Shared control-field base (Batch 52). Inputs, textareas, and native selects
 * all render on the raised `--control` fill with a stronger idle border and a
 * clear focus ring, so forms are legible on the dark surface ramp. Textareas
 * (see components/ui/textarea.tsx) reuse this so the two never drift.
 */
export const controlFieldClassName = cn(
  'w-full rounded-md border border-control-border bg-control text-text-primary font-sans',
  'placeholder:text-text-muted',
  'transition-shadow duration-fast',
  'focus-visible:outline-none focus-visible:border-primary focus-visible:shadow-glow',
  'disabled:cursor-not-allowed disabled:opacity-50',
);

export type InputProps = React.InputHTMLAttributes<HTMLInputElement>;

const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, type, ...props }, ref) => {
    return (
      <input
        type={type}
        className={cn(
          controlFieldClassName,
          'flex h-11 px-4 py-2 text-base sm:text-sm',
          className,
        )}
        ref={ref}
        {...props}
      />
    );
  },
);
Input.displayName = 'Input';

export { Input };
