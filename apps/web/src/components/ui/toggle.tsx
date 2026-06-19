import { type ButtonHTMLAttributes, forwardRef } from 'react';
import { cn } from '@/lib/utils';

interface ToggleProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'onChange'> {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  label?: string;
}

/** iOS-style boolean switch. */
export const Toggle = forwardRef<HTMLButtonElement, ToggleProps>(
  ({ checked, onCheckedChange, label, className, ...props }, ref) => {
    return (
      <button
        ref={ref}
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        onClick={() => onCheckedChange(!checked)}
        className={cn(
          'relative inline-flex h-7 w-12 shrink-0 cursor-pointer items-center rounded-full',
          'transition-colors duration-base focus-visible:outline-none focus-visible:shadow-glow',
          checked ? 'bg-primary' : 'bg-surface-elevated border border-border',
          className,
        )}
        {...props}
      >
        <span
          className={cn(
            'pointer-events-none inline-block h-5 w-5 rounded-full bg-white shadow-md',
            'transform transition-transform duration-base ease-out-quart',
            checked ? 'translate-x-6' : 'translate-x-1',
          )}
        />
      </button>
    );
  },
);
Toggle.displayName = 'Toggle';
