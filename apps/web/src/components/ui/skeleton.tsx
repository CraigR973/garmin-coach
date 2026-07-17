import * as React from 'react';
import { cn } from '@/lib/utils';

const Skeleton = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      role="status"
      aria-busy="true"
      aria-label="Loading"
      className={cn(
        // Batch 137: the bespoke shimmer sweep (index.css, light/dark-tuned
        // --shimmer-stripe) over the surface-elevated fill — reads more premium
        // than a flat opacity pulse. Reduced motion falls back to a static fill.
        'animate-shimmer rounded-md bg-surface-elevated motion-reduce:animate-none',
        className,
      )}
      {...props}
    />
  ),
);
Skeleton.displayName = 'Skeleton';

export { Skeleton };
