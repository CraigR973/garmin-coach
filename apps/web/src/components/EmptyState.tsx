import { type ReactNode } from 'react';
import { cn } from '@/lib/utils';

interface EmptyStateProps {
  icon?: ReactNode;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
}

export function EmptyState({ icon, title, description, action, className }: EmptyStateProps) {
  return (
    <div
      role="status"
      className={cn(
        'flex flex-col items-center justify-center text-center py-12 px-4 rounded-lg border border-dashed border-border bg-surface/30',
        className,
      )}
    >
      {icon && (
        <div className="mb-3 text-text-muted/70 [&>svg]:w-10 [&>svg]:h-10" aria-hidden="true">
          {icon}
        </div>
      )}
      <p className="text-base font-semibold text-text-primary font-sans tracking-tight">{title}</p>
      {description && (
        <div className="mt-1 text-sm font-sans text-text-muted max-w-sm">{description}</div>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
