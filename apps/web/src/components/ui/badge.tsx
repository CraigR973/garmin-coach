import * as React from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';

const badgeVariants = cva(
  'inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold transition-colors',
  {
    variants: {
      variant: {
        default: 'bg-primary/20 text-primary border border-primary/30',
        accent: 'bg-accent/20 text-accent border border-accent/30',
        gold: 'bg-gold/20 text-gold border border-gold/30',
        silver: 'bg-silver/20 text-silver border border-silver/30',
        bronze: 'bg-bronze/20 text-bronze border border-bronze/30',
        success: 'bg-success/20 text-success border border-success/30',
        warning: 'bg-warning/20 text-warning border border-warning/30',
        error: 'bg-error/20 text-error border border-error/30',
        muted: 'bg-surface-elevated text-text-muted border border-border',
        live: 'bg-live/20 text-live border border-live/30 animate-pulse-live',
      },
    },
    defaultVariants: {
      variant: 'default',
    },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge, badgeVariants };
