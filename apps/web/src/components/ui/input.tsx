import * as React from 'react';
import { cn } from '@/lib/utils';

export type InputProps = React.InputHTMLAttributes<HTMLInputElement>;

const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, type, ...props }, ref) => {
    return (
      <input
        type={type}
        className={cn(
          'flex h-11 w-full rounded-md border border-border bg-surface px-4 py-2',
          'text-base sm:text-sm text-text-primary font-sans',
          'placeholder:text-text-muted',
          'transition-shadow duration-fast',
          'focus-visible:outline-none focus-visible:border-primary focus-visible:shadow-glow',
          'disabled:cursor-not-allowed disabled:opacity-50',
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
