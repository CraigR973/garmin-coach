import * as React from 'react';
import { Slot } from '@radix-ui/react-slot';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';

const buttonVariants = cva(
  [
    'inline-flex items-center justify-center gap-2 whitespace-nowrap',
    'rounded-md text-sm font-medium font-sans tracking-tight',
    'transition-all duration-fast ease-out-quart',
    'focus-visible:outline-none focus-visible:shadow-glow',
    'disabled:pointer-events-none disabled:opacity-50',
    'press-down select-none',
  ].join(' '),
  {
    variants: {
      variant: {
        default: 'bg-primary text-on-primary hover:bg-primary-dark font-semibold',
        accent: 'bg-accent text-on-accent hover:bg-accent-dark font-semibold focus-visible:shadow-glow-accent',
        outline: 'border border-border-strong bg-transparent text-text-primary hover:bg-surface-elevated',
        ghost: 'bg-transparent text-text-secondary hover:bg-surface-elevated hover:text-text-primary',
        subtle: 'bg-surface-elevated text-text-primary hover:bg-surface-overlay',
        destructive: 'bg-error text-white hover:bg-error/90 font-semibold',
        link: 'text-primary underline-offset-4 hover:underline px-0 h-auto',
      },
      size: {
        default: 'h-11 px-5 py-2',
        sm: 'h-9 rounded-sm px-3 text-xs',
        lg: 'h-12 rounded-lg px-7 text-base',
        icon: 'h-11 w-11',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'default',
    },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : 'button';
    return (
      <Comp
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        {...props}
      />
    );
  },
);
Button.displayName = 'Button';

export { Button, buttonVariants };
